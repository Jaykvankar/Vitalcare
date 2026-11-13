"""Step-by-step walkthrough of every cryptographic step, for the viva / demo.

    python scripts/crypto_demo.py
Uses throwaway keys; touches no database.
"""
import json
import os

import _path  # noqa: F401

os.environ.setdefault("RPM_MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
from app.readings.ingest import signed_message  # noqa: E402
from app.security import aead, sealing, signatures  # noqa: E402
from app.security.hashing import hash_password, sha512_hex, verify_password  # noqa: E402


def show(title: str, value) -> None:  # noqa: ANN001
    text = value.hex() if isinstance(value, bytes) else str(value)
    print(f"  {title:<34} {text[:96]}{'...' if len(text) > 96 else ''}")


print("\n1) DIFFIE-HELLMAN (RFC 7919 ffdhe3072, g^ab mod p)")
show("p bits / g", f"{sealing.P.bit_length()} / {sealing.G}")
server = sealing.generate_private_key()
device = sealing.generate_private_key()
S, E = sealing.public_bytes(server.public_key()), sealing.public_bytes(device.public_key())
show("server public S = g^s mod p", S)
show("device ephemeral E = g^e mod p", E)
k1, k2 = device.exchange(server.public_key()), server.exchange(device.public_key())
show("device computes S^e mod p", k1)
show("server computes E^s mod p", k2)
print(f"  {'shared secrets equal?':<34} {k1 == k2}")

print("\n2) AES-256-GCM sealing of a reading (key = HKDF-SHA-512 of the DH secret)")
vitals = {"hr": 88, "spo2": 96, "sbp": 124, "dbp": 79, "temp": 36.9, "rr": 16}
sealed = sealing.seal(S, json.dumps(vitals).encode(), device_id="dev-demo", seq=1, ts=1700000000)
show("plaintext", json.dumps(vitals))
show("ciphertext||tag", sealed.ciphertext)
opened = sealing.unseal(server, sealed, device_id="dev-demo", seq=1, ts=1700000000)
show("server decrypts", opened.decode())
try:
    sealing.unseal(server, sealed, device_id="dev-demo", seq=2, ts=1700000000)
except sealing.SealError as e:
    show("same ciphertext, header seq=2", f"REJECTED ({e})")

print("\n3) RSA-3072 DIGITAL SIGNATURE: sign-the-digest (PSS, SHA-512)")
rsa_key = signatures.rsa_generate()
msg = signed_message("dev-demo", 1, 1700000000, sealed.epk, sealed.nonce, sealed.ciphertext)
show("digest d = SHA-512(packet)", sha512_hex(msg))
sig = signatures.rsa_sign_digest(rsa_key, msg)
show("signature = RSA-PSS-sign(d)", sig)
show("verify (direct, device public key)", signatures.rsa_verify_digest(rsa_key.public_key(), msg, sig))
show("verify after flipping one byte", signatures.rsa_verify_digest(rsa_key.public_key(), msg[:-1] + b"\x00", sig))

print("\n4) ECDSA P-384 (DSA on an elliptic curve) for audit checkpoints")
ec_key = signatures.ecdsa_generate()
head = sha512_hex(b"audit row 1" + b"audit row 2")
ec_sig = signatures.ecdsa_sign(ec_key, head.encode())
show("chain head (SHA-512)", head)
show("ECDSA signature (r,s DER)", ec_sig)
show("verify", signatures.ecdsa_verify(ec_key.public_key(), head.encode(), ec_sig))
show("verify with rewritten head", signatures.ecdsa_verify(ec_key.public_key(), b"0" * 128, ec_sig))

print("\n5) ENVELOPE ENCRYPTION (AES-256-GCM key wrapping)")
master, dek = aead.new_key(), aead.new_key()
wrapped = aead.seal_blob(master, dek, b"dek|patient:1|v1")
show("patient DEK", dek)
show("wrapped DEK stored in DB", wrapped)
show("unwrap with master key ok?", aead.open_blob(master, wrapped, b"dek|patient:1|v1") == dek)

print("\n6) PASSWORDS: PBKDF2-HMAC-SHA-512, 210,000 iterations, random salt")
h = hash_password("correct horse battery staple")
show("stored", h)
show("verify correct password", verify_password("correct horse battery staple", h))
show("verify wrong password", verify_password("wrong", h))
print()
