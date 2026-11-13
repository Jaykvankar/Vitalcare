"""Envelope encryption (our own scheme on top of AES-256-GCM).

    master key (env, versioned) --AES-256-GCM wraps--> per-patient DEK --AES-256-GCM--> readings, PII, state

* Each patient has a random 256-bit data encryption key (DEK).
* The DEK is stored only in wrapped form: AES-GCM(master_key[v], DEK, AAD="dek"|patient_id|v).
* Each reading is its own AES-GCM ciphertext under the DEK, with AAD binding
  patient_id, device_id, seq and timestamp, so a ciphertext cannot be moved to another row.
* Rotating the master key only re-wraps DEKs; readings are never re-encrypted.
"""
from __future__ import annotations

import json

from ..config import get_settings
from . import aead
from .hashing import canonical


def new_dek() -> bytes:
    return aead.new_key()


def _dek_aad(patient_id: int, version: int) -> bytes:
    return canonical("dek", patient_id, version)


def wrap_dek(dek: bytes, patient_id: int, version: int | None = None) -> tuple[bytes, int]:
    s = get_settings()
    version = s.master_key_version if version is None else version
    return aead.seal_blob(s.key_for_version(version), dek, _dek_aad(patient_id, version)), version


def unwrap_dek(wrapped: bytes, patient_id: int, version: int) -> bytes:
    key = get_settings().key_for_version(version)
    return aead.open_blob(key, wrapped, _dek_aad(patient_id, version))


def patient_dek(patient) -> bytes:
    return unwrap_dek(patient.wrapped_dek, patient.id, patient.key_version)


# ---------------------------------------------------------------- readings

def reading_aad(patient_id: int, device_id: str, seq: int, ts: int) -> bytes:
    return canonical("reading", patient_id, device_id, seq, ts)


def encrypt_reading(dek: bytes, vitals: dict, *, patient_id: int, device_id: str, seq: int, ts: int):
    data = json.dumps(vitals, separators=(",", ":"), sort_keys=True).encode()
    return aead.encrypt(dek, data, reading_aad(patient_id, device_id, seq, ts))


def decrypt_reading(dek: bytes, reading) -> dict:
    data = aead.decrypt(
        dek, reading.nonce, reading.ciphertext,
        reading_aad(reading.patient_id, reading.device_id, reading.seq, reading.ts),
    )
    return json.loads(data)


# ---------------------------------------------------------------- small fields

def encrypt_field(dek: bytes, value: str | None, *, patient_id: int, field: str) -> bytes | None:
    if value is None:
        return None
    return aead.seal_blob(dek, value.encode(), canonical("field", patient_id, field))


def decrypt_field(dek: bytes, blob: bytes | None, *, patient_id: int, field: str) -> str | None:
    if blob is None:
        return None
    return aead.open_blob(dek, blob, canonical("field", patient_id, field)).decode()


def encrypt_json(dek: bytes, obj, *, patient_id: int, field: str) -> bytes:
    return aead.seal_blob(dek, json.dumps(obj).encode(), canonical("json", patient_id, field))


def decrypt_json(dek: bytes, blob: bytes, *, patient_id: int, field: str):
    return json.loads(aead.open_blob(dek, blob, canonical("json", patient_id, field)))


# ---------------------------------------------------------------- master-key secrets

def encrypt_with_master(value: bytes, purpose: str, version: int | None = None) -> tuple[bytes, int]:
    s = get_settings()
    version = s.master_key_version if version is None else version
    return aead.seal_blob(s.key_for_version(version), value, canonical("master", purpose, version)), version


def decrypt_with_master(blob: bytes, purpose: str, version: int) -> bytes:
    key = get_settings().key_for_version(version)
    return aead.open_blob(key, blob, canonical("master", purpose, version))
