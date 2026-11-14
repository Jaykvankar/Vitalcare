"""Master key sources: .env (default), passphrase-sealed file, external command (HSM / KMS hook)."""
import base64
import json
import secrets
import sys

import pytest


@pytest.fixture
def keys():
    from app.keysource import KeyBundle

    return KeyBundle(version=3, key=secrets.token_bytes(32), previous={1: secrets.token_bytes(32), 2: secrets.token_bytes(32)})


def test_sealed_file_round_trip_and_tamper(keys):
    from app import keysource

    sealed = keysource.seal(keys, "correct horse battery", rounds=1000)
    assert keys.key not in sealed and base64.b64encode(keys.key) not in sealed      # nothing readable on disk
    back = keysource.unseal(sealed, "correct horse battery")
    assert (back.version, back.key, back.previous) == (keys.version, keys.key, keys.previous)
    with pytest.raises(keysource.KeySourceError, match="wrong passphrase"):
        keysource.unseal(sealed, "wrong horse battery")
    doc = json.loads(sealed)
    blob = bytearray(base64.b64decode(doc["blob"]))
    blob[-1] ^= 1                                                                    # flip one bit
    doc["blob"] = base64.b64encode(bytes(blob)).decode()
    with pytest.raises(keysource.KeySourceError):
        keysource.unseal(json.dumps(doc).encode(), "correct horse battery")
    doc = json.loads(sealed)
    doc["rounds"] = 1                                                                # weaken the KDF: AAD mismatch
    with pytest.raises(keysource.KeySourceError):
        keysource.unseal(json.dumps(doc).encode(), "correct horse battery")


def _load_with(monkeypatch, **env):
    from app import config

    for k in ("RPM_MASTER_KEY_SOURCE", "RPM_MASTER_KEY_FILE", "RPM_MASTER_PASSPHRASE", "RPM_MASTER_KEY_COMMAND"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return config.load_settings()


def test_settings_from_sealed_file(env, keys, tmp_path, monkeypatch):
    from app import config, keysource

    path = tmp_path / "master_keys.sealed"
    path.write_bytes(keysource.seal(keys, "a long passphrase", rounds=1000))
    s = _load_with(monkeypatch, RPM_MASTER_KEY_SOURCE="file", RPM_MASTER_KEY_FILE=str(path),
                   RPM_MASTER_PASSPHRASE="a long passphrase")
    assert (s.master_key, s.master_key_version, s.previous_master_keys) == (keys.key, 3, keys.previous)
    assert s.key_for_version(1) == keys.previous[1]
    import os
    assert "RPM_MASTER_PASSPHRASE" not in os.environ                                 # removed once used
    with pytest.raises(config.ConfigError, match="wrong passphrase"):
        _load_with(monkeypatch, RPM_MASTER_KEY_SOURCE="file", RPM_MASTER_KEY_FILE=str(path), RPM_MASTER_PASSPHRASE="nope")
    with pytest.raises(config.ConfigError, match="not found"):
        _load_with(monkeypatch, RPM_MASTER_KEY_SOURCE="file", RPM_MASTER_KEY_FILE=str(tmp_path / "missing"),
                   RPM_MASTER_PASSPHRASE="x")


def test_settings_from_command(env, keys, tmp_path, monkeypatch):
    from app import config

    script = tmp_path / "fake_hsm.py"
    script.write_text(f"print({keys.to_json().decode()!r})\n")
    s = _load_with(monkeypatch, RPM_MASTER_KEY_SOURCE="command", RPM_MASTER_KEY_COMMAND=f'"{sys.executable}" "{script}"')
    assert (s.master_key, s.master_key_version) == (keys.key, 3)
    with pytest.raises(config.ConfigError, match="needs RPM_MASTER_KEY_COMMAND"):
        _load_with(monkeypatch, RPM_MASTER_KEY_SOURCE="command")
    with pytest.raises(config.ConfigError, match="must be env, file or command"):
        _load_with(monkeypatch, RPM_MASTER_KEY_SOURCE="cloud")


def test_env_source_is_unchanged(env, monkeypatch):
    s = _load_with(monkeypatch)
    assert len(s.master_key) == 32 and s.master_key_version == 1
