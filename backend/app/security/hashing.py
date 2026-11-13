"""Hash-family helpers. Everything here is built from SHA-512 only.

- SHA-512            (FIPS 180-4)   digests, audit hash chain, model pinning
- HMAC-SHA-512       (FIPS 198-1)   keyed hashing
- HKDF-SHA-512       (RFC 5869)     derive AES keys from a Diffie-Hellman secret
- PBKDF2-HMAC-SHA-512 (SP 800-132)  password storage
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def sha512_hex(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def hmac_sha512(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha512).digest()


def hkdf_sha512(secret: bytes, *, salt: bytes, info: bytes, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA512(), length=length, salt=salt, info=info).derive(secret)


def canonical(*parts: bytes | str | int) -> bytes:
    """Unambiguous encoding of several fields: each part is 4-byte length + bytes.

    Used for anything that is hashed, signed or bound as AES-GCM associated data, so
    two different field lists can never produce the same byte string.
    """
    out = bytearray()
    for part in parts:
        if isinstance(part, int):
            part = str(part)
        if isinstance(part, str):
            part = part.encode("utf-8")
        out += struct.pack(">I", len(part)) + part
    return bytes(out)


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    return base64.b64decode(data, validate=True)


# ---------------------------------------------------------------- passwords

PBKDF2_SCHEME = "pbkdf2_sha512"


def hash_password(password: str, iterations: int = 210_000) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_SCHEME}${iterations}${b64e(salt)}${b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_b64, dk_b64 = stored.split("$")
        if scheme != PBKDF2_SCHEME:
            return False
        dk = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), b64d(salt_b64), int(iters))
        return hmac.compare_digest(dk, b64d(dk_b64))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH: str | None = None


def burn_password_time(password: str) -> None:
    """Spend the same time as a real check so unknown usernames are not revealed by timing."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password")
    verify_password(password, _DUMMY_HASH)
