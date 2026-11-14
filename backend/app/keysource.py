"""Where the master key comes from (RPM_MASTER_KEY_SOURCE).

    env      (default) RPM_MASTER_KEY / RPM_PREVIOUS_MASTER_KEYS in the environment or .env. Fine for a laptop demo.
    file     A sealed key file: the master keys encrypted with AES-256-GCM under a key derived from a passphrase with
             PBKDF2-HMAC-SHA-512 (600,000 rounds). The passphrase is typed when the server starts (or supplied by the
             operating system's secret store as RPM_MASTER_PASSPHRASE), so the key is never stored readable on disk.
             Create it with: python scripts/seal_master_key.py
    command  RPM_MASTER_KEY_COMMAND is run at start-up and prints the key bundle as JSON. This is how a hospital plugs in
             a hardware security module or a cloud key service (KMS / Vault): the command asks the HSM for the key, so
             no key is stored on the server at all.

Key bundle JSON (sealed file plaintext and command output):
    {"version": 2, "key": "<base64 32 bytes>", "previous": {"1": "<base64 32 bytes>"}}
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import secrets
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SEALED_FORMAT = "vitalcare-sealed-master-keys-v1"
PBKDF2_ROUNDS = 600_000


class KeySourceError(RuntimeError):
    pass


@dataclass
class KeyBundle:
    version: int
    key: bytes
    previous: dict[int, bytes] = field(default_factory=dict)

    def to_json(self) -> bytes:
        return json.dumps({"version": self.version, "key": base64.b64encode(self.key).decode(),
                           "previous": {str(v): base64.b64encode(k).decode() for v, k in sorted(self.previous.items())}
                           }).encode()

    @classmethod
    def from_json(cls, data: bytes | str) -> KeyBundle:
        try:
            doc = json.loads(data)
            bundle = cls(version=int(doc["version"]), key=_key32(doc["key"]),
                         previous={int(v): _key32(k) for v, k in (doc.get("previous") or {}).items()})
        except (ValueError, KeyError, TypeError) as exc:
            raise KeySourceError(f"key bundle is not valid: {exc}") from exc
        if bundle.version < 1 or bundle.version in bundle.previous:
            raise KeySourceError("key bundle version must be >= 1 and not repeated in 'previous'")
        return bundle


def _key32(b64: str) -> bytes:
    key = base64.b64decode(b64, validate=True)
    if len(key) != 32:
        raise ValueError("each key must be 32 bytes (AES-256)")
    return key


def _kek(passphrase: str, salt: bytes, rounds: int) -> bytes:
    if not passphrase:
        raise KeySourceError("empty passphrase")
    return hashlib.pbkdf2_hmac("sha512", passphrase.encode("utf-8"), salt, rounds, dklen=32)


def _aad(rounds: int) -> bytes:
    from .security.hashing import canonical

    return canonical(SEALED_FORMAT, rounds)


def seal(bundle: KeyBundle, passphrase: str, rounds: int = PBKDF2_ROUNDS) -> bytes:
    """Sealed file contents: AES-256-GCM(PBKDF2-HMAC-SHA-512(passphrase), key bundle)."""
    from .security import aead

    salt = secrets.token_bytes(16)
    blob = aead.seal_blob(_kek(passphrase, salt, rounds), bundle.to_json(), _aad(rounds))
    return json.dumps({"format": SEALED_FORMAT, "kdf": "pbkdf2-hmac-sha512", "rounds": rounds,
                       "salt": base64.b64encode(salt).decode(), "blob": base64.b64encode(blob).decode()},
                      indent=2).encode()


def unseal(contents: bytes, passphrase: str) -> KeyBundle:
    from .security import aead

    try:
        doc = json.loads(contents)
        if doc.get("format") != SEALED_FORMAT:
            raise ValueError("unknown format")
        rounds, salt, blob = int(doc["rounds"]), base64.b64decode(doc["salt"]), base64.b64decode(doc["blob"])
    except (ValueError, KeyError, TypeError) as exc:
        raise KeySourceError(f"sealed key file is damaged: {exc}") from exc
    try:
        plain = aead.open_blob(_kek(passphrase, salt, rounds), blob, _aad(rounds))
    except aead.DecryptionError as exc:
        raise KeySourceError("wrong passphrase, or the sealed key file was changed") from exc
    return KeyBundle.from_json(plain)


def default_sealed_path() -> Path:
    from .config import PROJECT_DIR

    return Path(os.environ.get("RPM_MASTER_KEY_FILE", PROJECT_DIR / "secrets" / "master_keys.sealed"))


def passphrase(prompt: str = "Master key passphrase: ") -> str:
    """From RPM_MASTER_PASSPHRASE (removed from the environment once read), else typed at the terminal."""
    value = os.environ.pop("RPM_MASTER_PASSPHRASE", None)
    if value:
        return value
    if not sys.stdin or not sys.stdin.isatty():
        raise KeySourceError("the sealed master key needs a passphrase: run in a terminal or set RPM_MASTER_PASSPHRASE "
                             "from the operating system's secret store")
    return getpass.getpass(prompt)


def _split(command: str) -> list[str]:
    """Split a command line without a shell. Windows paths keep their backslashes; quotes are removed."""
    if os.name != "nt":
        return shlex.split(command)
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in shlex.split(command, posix=False)]


def from_command(command: str) -> KeyBundle:
    try:
        out = subprocess.run(_split(command), capture_output=True, timeout=30, check=True)  # noqa: S603 (no shell)
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeySourceError(f"RPM_MASTER_KEY_COMMAND failed: {exc}") from exc
    return KeyBundle.from_json(out.stdout)


def load() -> KeyBundle | None:
    """The key bundle for the configured source, or None for 'env' (handled by config.load_settings)."""
    source = os.environ.get("RPM_MASTER_KEY_SOURCE", "env").strip().lower()
    if source == "env":
        return None
    if source == "file":
        path = default_sealed_path()
        if not path.is_file():
            raise KeySourceError(f"sealed key file not found: {path} (create it with scripts/seal_master_key.py)")
        return unseal(path.read_bytes(), passphrase())
    if source == "command":
        command = os.environ.get("RPM_MASTER_KEY_COMMAND", "")
        if not command:
            raise KeySourceError("RPM_MASTER_KEY_SOURCE=command needs RPM_MASTER_KEY_COMMAND")
        return from_command(command)
    raise KeySourceError(f"RPM_MASTER_KEY_SOURCE must be env, file or command (got {source!r})")
