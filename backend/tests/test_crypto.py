import json
import random

import pytest


def test_aes_gcm_round_trip_and_tamper(env):
    from app.security import aead

    key = aead.new_key()
    nonce, ct = aead.encrypt(key, b"spo2=97", b"aad")
    assert aead.decrypt(key, nonce, ct, b"aad") == b"spo2=97"
    with pytest.raises(aead.DecryptionError):
        aead.decrypt(key, nonce, ct[:-1] + bytes([ct[-1] ^ 1]), b"aad")      # flipped bit
    with pytest.raises(aead.DecryptionError):
        aead.decrypt(aead.new_key(), nonce, ct, b"aad")                      # wrong key


def test_reading_ciphertext_cannot_be_moved_to_another_row(env):
    from app.security import crypto

    class Row:  # minimal stand-in for models.Reading
        pass

    dek = crypto.new_dek()
    nonce, ct = crypto.encrypt_reading(dek, {"hr": 80}, patient_id=1, device_id="d", seq=5, ts=100)
    row = Row()
    row.nonce, row.ciphertext, row.patient_id, row.device_id, row.seq, row.ts = nonce, ct, 1, "d", 5, 100
    assert crypto.decrypt_reading(dek, row) == {"hr": 80}
    row.patient_id = 2  # AAD swap: same blob attached to another patient
    with pytest.raises(Exception):
        crypto.decrypt_reading(dek, row)


def test_envelope_wrap_and_master_key_rotation(env, monkeypatch):
    import base64
    import secrets

    from app import config
    from app.security import crypto

    dek = crypto.new_dek()
    wrapped, v1 = crypto.wrap_dek(dek, 7)
    assert crypto.unwrap_dek(wrapped, 7, v1) == dek
    with pytest.raises(Exception):
        crypto.unwrap_dek(wrapped, 8, v1)  # bound to patient id

    old = config.get_settings().master_key
    monkeypatch.setenv("RPM_PREVIOUS_MASTER_KEYS", f"{v1}:{base64.b64encode(old).decode()}")
    monkeypatch.setenv("RPM_MASTER_KEY", base64.b64encode(secrets.token_bytes(32)).decode())
    monkeypatch.setenv("RPM_MASTER_KEY_VERSION", str(v1 + 1))
    config.reset_settings()
    try:
        assert crypto.unwrap_dek(wrapped, 7, v1) == dek          # old data still readable
        rewrapped, v2 = crypto.wrap_dek(dek, 7)                  # re-wrap under the new key
        assert v2 == v1 + 1 and crypto.unwrap_dek(rewrapped, 7, v2) == dek
    finally:
        monkeypatch.undo()
        config.reset_settings()


def _is_probable_prime(n: int, rounds: int = 8) -> bool:
    if n % 2 == 0:
        return False
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    rng = random.Random(1)
    for _ in range(rounds):
        a = rng.randrange(2, n - 2)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def test_dh_group_is_a_3072_bit_safe_prime(env):
    from app.security import sealing

    assert sealing.P.bit_length() == 3072 and sealing.G == 2
    assert _is_probable_prime(sealing.P) and _is_probable_prime(sealing.Q)


def test_dh_sealing_round_trip_and_header_binding(env):
    from app.security import sealing

    server = sealing.generate_private_key()
    spk = sealing.public_bytes(server.public_key())
    sealed = sealing.seal(spk, b'{"hr":70}', device_id="d1", seq=1, ts=10)
    assert sealing.unseal(server, sealed, device_id="d1", seq=1, ts=10) == b'{"hr":70}'
    with pytest.raises(sealing.SealError):
        sealing.unseal(server, sealed, device_id="d1", seq=2, ts=10)
    with pytest.raises(sealing.SealError):
        sealing.unseal(sealing.generate_private_key(), sealed, device_id="d1", seq=1, ts=10)
    with pytest.raises(sealing.SealError):
        sealing.load_public((1).to_bytes(sealing.PUB_BYTES, "big"))  # trivial DH value rejected


def test_rsa_sign_the_digest(env):
    from app.security import signatures

    k = signatures.rsa_generate()
    sig = signatures.rsa_sign_digest(k, b"packet")
    assert signatures.rsa_verify_digest(k.public_key(), b"packet", sig)
    assert not signatures.rsa_verify_digest(k.public_key(), b"packet!", sig)
    assert not signatures.rsa_verify_digest(signatures.rsa_generate().public_key(), b"packet", sig)


def test_ecdsa(env):
    from app.security import signatures

    k = signatures.ecdsa_generate()
    sig = signatures.ecdsa_sign(k, b"head")
    assert signatures.ecdsa_verify(k.public_key(), b"head", sig)
    assert not signatures.ecdsa_verify(k.public_key(), b"other", sig)


def test_pbkdf2_passwords(env):
    from app.security.hashing import hash_password, verify_password

    h = hash_password("s3cret-password", iterations=1000)
    assert h.startswith("pbkdf2_sha512$1000$")
    assert verify_password("s3cret-password", h)
    assert not verify_password("wrong", h)
    assert hash_password("s3cret-password", 1000) != h  # random salt


def test_model_integrity_pin(env, tmp_path, monkeypatch):
    from app.ml import infer

    assert infer.load_model() is not None
    fake = tmp_path / "model.joblib"
    fake.write_bytes(b"not the pinned model")
    monkeypatch.setattr(infer, "ML_DIR", tmp_path)
    monkeypatch.setattr(infer, "_model", None)
    with pytest.raises(infer.ModelIntegrityError):
        infer.load_model()


def test_rules_force_critical_on_hypoxia(env):
    from app.ml import infer
    from app.ml.features import new_state

    s = infer.score({"hr": 112, "spo2": 86, "sbp": 118, "dbp": 74, "temp": 37.0, "rr": 27}, new_state())
    assert s.band == "critical"
    assert "SPO2_LOW" in {c for c, _ in s.reasons}
    calm = infer.score({"hr": 72, "spo2": 98, "sbp": 120, "dbp": 78, "temp": 36.7, "rr": 14}, new_state())
    assert calm.band == "normal"
    json.dumps(s.state)  # baseline state is serialisable (it is stored encrypted)
