"""AES-256-GCM (FIPS 197 + SP 800-38D).

AES-256 does the encryption (14 rounds of SubBytes, ShiftRows, MixColumns, AddRoundKey).
GCM runs AES in counter mode and adds a 128-bit authentication tag, so any change to the
ciphertext or to the associated data (AAD) makes decryption fail.
"""
from __future__ import annotations

import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12


class DecryptionError(Exception):
    """Ciphertext, key, nonce or associated data did not match (tampering or wrong key)."""


def new_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """Return (nonce, ciphertext||tag). A fresh random 96-bit nonce is used every call."""
    if len(key) != 32:
        raise ValueError("AES-256 key must be 32 bytes")
    nonce = secrets.token_bytes(NONCE_BYTES)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise DecryptionError("authentication failed") from exc


def seal_blob(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """nonce || ciphertext||tag in one blob (handy for single DB columns)."""
    nonce, ct = encrypt(key, plaintext, aad)
    return nonce + ct


def open_blob(key: bytes, blob: bytes, aad: bytes) -> bytes:
    return decrypt(key, blob[:NONCE_BYTES], blob[NONCE_BYTES:], aad)
