"""Digital signatures.

Devices: RSA-3072 with PSS padding, **sign-the-digest**:
    d   = SHA-512(canonical packet bytes)
    sig = RSA-PSS-Sign(device_private_key, d)
This is a *direct* digital signature: only sender and receiver are involved, and the server
verifies with the device's registered public key (no arbiter).

Audit checkpoints: ECDSA P-384 over SHA-512 (the DSA algorithm on an elliptic curve, FIPS 186-5).
"""
from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from .hashing import sha512

RSA_BITS = 3072
_PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA512()), salt_length=padding.PSS.DIGEST_LENGTH)


# ------------------------------------------------------------------ RSA (devices)

def rsa_generate() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=RSA_BITS)


def rsa_sign_digest(private_key: rsa.RSAPrivateKey, message: bytes) -> bytes:
    digest = sha512(message)  # step 1: hash the message
    return private_key.sign(digest, _PSS, Prehashed(hashes.SHA512()))  # step 2: sign the digest


def rsa_verify_digest(public_key: rsa.RSAPublicKey, message: bytes, signature: bytes) -> bool:
    digest = sha512(message)
    try:
        public_key.verify(signature, digest, _PSS, Prehashed(hashes.SHA512()))
        return True
    except InvalidSignature:
        return False


# ------------------------------------------------------------------ ECDSA (audit)

def ecdsa_generate() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP384R1())


def ecdsa_sign(private_key: ec.EllipticCurvePrivateKey, message: bytes) -> bytes:
    return private_key.sign(message, ec.ECDSA(hashes.SHA512()))


def ecdsa_verify(public_key: ec.EllipticCurvePublicKey, message: bytes, signature: bytes) -> bool:
    try:
        public_key.verify(signature, message, ec.ECDSA(hashes.SHA512()))
        return True
    except InvalidSignature:
        return False


# ------------------------------------------------------------------ PEM helpers

def public_pem(key) -> str:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def load_public_pem(pem: str):
    return serialization.load_pem_public_key(pem.encode())


def private_pem(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def load_private_pem(pem: bytes):
    return serialization.load_pem_private_key(pem, password=None)


def load_rsa_public(pem: str) -> rsa.RSAPublicKey:
    key = load_public_pem(pem)
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < RSA_BITS:
        raise ValueError("device key must be RSA-3072 or larger")
    return key
