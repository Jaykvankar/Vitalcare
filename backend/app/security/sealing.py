"""Hybrid Diffie-Hellman + AES-256-GCM sealing of device payloads (DHIES / ElGamal-style).

Classic finite-field Diffie-Hellman, g^(ab) mod p, over the RFC 7919 group ffdhe3072
(p is a 3072-bit safe prime, g = 2).

Per reading:
    device   : picks fresh secret e,  E = g^e mod p           (ephemeral public value)
    device   : K = S^e mod p   where S = g^s is the server's static public value
    server   : K = E^s mod p   (same K, never sent on the wire)
    both     : aes_key = HKDF-SHA-512(K, salt=SHA-512(E||S), info=header)
    device   : AES-256-GCM(aes_key, vitals, AAD=header)

A new e for every reading means a key leak only affects one reading.
"""
from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dh

from . import aead
from .hashing import canonical, hkdf_sha512, sha512

# RFC 7919 ffdhe3072, exported with: openssl genpkey -genparam -algorithm DH -pkeyopt group:ffdhe3072
FFDHE3072_PEM = b"""-----BEGIN DH PARAMETERS-----
MIIBiAKCAYEA//////////+t+FRYortKmq/cViAnPTzx2LnFg84tNpWp4TZBFGQz
+8yTnc4kmz75fS/jY2MMddj2gbICrsRhetPfHtXV/WVhJDP1H18GbtCFY2VVPe0a
87VXE15/V8k1mE8McODmi3fipona8+/och3xWKE2rec1MKzKT0g6eXq8CrGCsyT7
YdEIqUuyyOP7uWrat2DX9GgdT0Kj3jlN9K5W7edjcrsZCwenyO4KbXCeAvzhzffi
7MA0BM0oNC9hkXL+nOmFg/+OTxIy7vKBg8P+OxtMb61zO7X8vC7CIAXFjvGDfRaD
ssbzSibBsu/6iGtCOGEfz9zeNVs7ZRkDW7w09N75nAI4YbRvydbmyQd62R0mkff3
7lmMsPrBhtkcrv4TCYUTknC0EwyTvEN5RPT9RFLi103TZPLiHnH1S/9croKrnJ32
nuhtK8UiNjoNq8Uhl5sN6todv5pC1cRITgq80Gv6U93vPBsg7j/VnXwl5B0rZsYu
N///////////AgEC
-----END DH PARAMETERS-----
"""

_base = serialization.load_pem_parameters(FFDHE3072_PEM).parameter_numbers()
P: int = _base.p
G: int = _base.g
Q: int = (P - 1) // 2  # safe prime: q is also prime; passing q enables subgroup checks
PUB_BYTES = (P.bit_length() + 7) // 8  # 384

PARAMETERS = dh.DHParameterNumbers(P, G, Q).parameters()


class SealError(Exception):
    pass


def generate_private_key() -> dh.DHPrivateKey:
    return PARAMETERS.generate_private_key()


def public_bytes(pub: dh.DHPublicKey) -> bytes:
    return pub.public_numbers().y.to_bytes(PUB_BYTES, "big")


def load_public(raw: bytes) -> dh.DHPublicKey:
    if len(raw) != PUB_BYTES:
        raise SealError("bad DH public value length")
    y = int.from_bytes(raw, "big")
    # Reject trivial values; the q-subgroup check is done by OpenSSL during exchange.
    if not 1 < y < P - 1:
        raise SealError("DH public value out of range")
    try:
        return dh.DHPublicNumbers(y, PARAMETERS.parameter_numbers()).public_key()
    except ValueError as exc:
        raise SealError("invalid DH public value") from exc


def private_to_pem(key: dh.DHPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def private_from_pem(pem: bytes) -> dh.DHPrivateKey:
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, dh.DHPrivateKey):
        raise SealError("not a DH key")
    return key


def _derive(shared: bytes, epk: bytes, spk: bytes, header: bytes) -> bytes:
    return hkdf_sha512(shared, salt=sha512(epk + spk), info=b"RPM-seal-v1" + header, length=32)


@dataclass
class Sealed:
    epk: bytes          # device's ephemeral DH public value E = g^e mod p
    nonce: bytes
    ciphertext: bytes   # AES-256-GCM ciphertext || tag


def header_bytes(device_id: str, seq: int, ts: int) -> bytes:
    return canonical("RPM1", device_id, seq, ts)


def seal(server_pub_raw: bytes, plaintext: bytes, *, device_id: str, seq: int, ts: int) -> Sealed:
    server_pub = load_public(server_pub_raw)
    eph = generate_private_key()
    epk = public_bytes(eph.public_key())
    shared = eph.exchange(server_pub)
    header = header_bytes(device_id, seq, ts)
    key = _derive(shared, epk, server_pub_raw, header)
    nonce, ct = aead.encrypt(key, plaintext, aad=header + epk)
    return Sealed(epk=epk, nonce=nonce, ciphertext=ct)


def unseal(server_priv: dh.DHPrivateKey, sealed: Sealed, *, device_id: str, seq: int, ts: int) -> bytes:
    epk_key = load_public(sealed.epk)
    try:
        shared = server_priv.exchange(epk_key)
    except ValueError as exc:
        raise SealError("DH exchange rejected the public value") from exc
    spk = public_bytes(server_priv.public_key())
    header = header_bytes(device_id, seq, ts)
    key = _derive(shared, sealed.epk, spk, header)
    try:
        return aead.decrypt(key, sealed.nonce, sealed.ciphertext, aad=header + sealed.epk)
    except aead.DecryptionError as exc:
        raise SealError("payload authentication failed") from exc
