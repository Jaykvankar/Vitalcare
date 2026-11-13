"""Device pairing protocol (our own design).

1. An admin, or a clinician assigned to the patient, asks for a pairing code.
   Server stores: pairing_id, patient, AES-GCM(master_key, code), expiry (10 min), attempts.
   The person types the code into the device (or scans it).
2. The device generates its own RSA-3072 key pair (the private key never leaves it) and sends
       pairing_id, public_key_pem, proof = HMAC-SHA-512(key=code, canonical("RPM-pair-v1", pairing_id, public_key_pem))
3. Server recomputes the HMAC. Constant-time compare; max 5 wrong proofs, then the code is burned.
   On success the device is registered with its public key and the code is marked used (one-time).
   The response gives the device its id and the server's DH public value to pin.

The code itself never travels in step 2, so a network observer learns nothing reusable,
and a stolen public key without the code cannot be registered.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Device, PairingCode
from . import signatures
from .crypto import decrypt_with_master, encrypt_with_master
from .hashing import canonical, hmac_sha512

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L: easy to read and type


class PairingError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))  # ~59 bits
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def normalize(code: str) -> str:
    c = code.replace("-", "").replace(" ", "").upper()
    return f"{c[:4]}-{c[4:8]}-{c[8:]}"


def proof(code: str, pairing_id: str, public_key_pem: str) -> bytes:
    return hmac_sha512(normalize(code).encode(), canonical("RPM-pair-v1", pairing_id, public_key_pem))


def create(db: Session, *, patient_id: int, label: str, created_by: int) -> tuple[PairingCode, str]:
    code = new_code()
    pid = secrets.token_hex(8)
    blob, version = encrypt_with_master(code.encode(), f"pairing:{pid}")
    pc = PairingCode(id=pid, patient_id=patient_id, label=label, code_enc=blob, key_version=version,
                     created_by=created_by, expires_at=_now() + CODE_TTL)
    db.add(pc)
    db.commit()
    return pc, code


def complete(db: Session, *, pairing_id: str, public_key_pem: str, proof_bytes: bytes) -> Device:
    pc = db.get(PairingCode, pairing_id)
    if pc is None:
        raise PairingError(404, "Unknown pairing request")
    if pc.used_at is not None:
        raise PairingError(409, "Pairing code already used")
    if _aware(pc.expires_at) < _now():
        raise PairingError(410, "Pairing code expired")
    if pc.attempts >= MAX_ATTEMPTS:
        raise PairingError(429, "Too many wrong attempts; ask for a new code")
    try:
        signatures.load_rsa_public(public_key_pem)
    except ValueError as exc:
        raise PairingError(400, f"Invalid device key: {exc}") from exc

    code = decrypt_with_master(pc.code_enc, f"pairing:{pc.id}", pc.key_version).decode()
    if not hmac.compare_digest(proof(code, pc.id, public_key_pem), proof_bytes):
        pc.attempts += 1
        db.commit()
        raise PairingError(401, "Pairing proof does not match the code")

    device = Device(id=f"dev-{secrets.token_hex(6)}", patient_id=pc.patient_id, label=pc.label,
                    public_key_pem=public_key_pem, paired_by=pc.created_by)
    db.add(device)
    pc.used_at, pc.device_id = _now(), device.id
    db.commit()
    return device
