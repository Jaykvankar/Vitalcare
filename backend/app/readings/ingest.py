"""Device ingest: verify -> anti-replay -> consent -> unseal -> validate -> score -> encrypt -> alert.

Telemetry packet (our own format, JSON over HTTPS):
    {v, device_id, seq, ts, epk, nonce, ct, sig}
    epk/nonce/ct : DH-sealed AES-256-GCM payload (see security/sealing.py)
    sig          : RSA-3072-PSS over SHA-512(canonical(header, epk, nonce, ct))   (sign-the-digest)
Plaintext vitals exist only in memory inside process(); they are never logged or stored.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..ml import infer
from ..ml.features import new_state
from ..ml.rules import news2_inputs_present, validate
from ..models import Alert, Device, Patient, Reading
from ..security import audit, crypto, inspector, labels, sealing, server_keys, signatures
from ..security.hashing import b64d, canonical
from . import rollups

PROTOCOL_VERSION = 1


class Packet(BaseModel):
    v: int = Field(PROTOCOL_VERSION)
    device_id: str = Field(min_length=1, max_length=64)
    seq: int = Field(ge=1)
    ts: int
    epk: str = Field(max_length=1024)
    nonce: str = Field(max_length=64)
    ct: str = Field(max_length=4096)
    sig: str = Field(max_length=1024)


class IngestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def signed_message(device_id: str, seq: int, ts: int, epk: bytes, nonce: bytes, ct: bytes) -> bytes:
    return canonical("RPM1-packet", device_id, seq, ts, epk, nonce, ct)


def _reject(status: int, message: str, device_id: str) -> IngestError:
    audit.append("ingest_rejected", actor=f"device:{device_id}"[:64], target=device_id, detail=message)
    return IngestError(status, message)


def process(db: Session, pkt: Packet, *, now: int | None = None) -> dict:
    if pkt.v != PROTOCOL_VERSION:
        raise IngestError(400, "unsupported protocol version")
    try:
        epk, nonce, ct, sig = b64d(pkt.epk), b64d(pkt.nonce), b64d(pkt.ct), b64d(pkt.sig)
    except ValueError as exc:
        raise IngestError(400, "malformed packet encoding") from exc

    device = db.get(Device, pkt.device_id)
    if device is None or not device.active:
        raise _reject(401, "unknown or inactive device", pkt.device_id)

    # 1. Authenticity: RSA signature over the SHA-512 digest of the whole packet.
    pub = signatures.load_rsa_public(device.public_key_pem)
    signed = signed_message(pkt.device_id, pkt.seq, pkt.ts, epk, nonce, ct)
    if not signatures.rsa_verify_digest(pub, signed, sig):
        raise _reject(401, "bad signature", pkt.device_id)

    # 2. Freshness: timestamp window (now=None means live traffic; seeding passes historical times).
    current = int(time.time()) if now is None else now
    if abs(current - pkt.ts) > get_settings().ingest_skew_seconds:
        raise _reject(400, "timestamp outside allowed window", pkt.device_id)

    # 3. Anti-replay: sequence must strictly increase (atomic compare-and-set).
    prev_seq = device.last_seq
    res = db.execute(
        update(Device).where(Device.id == device.id, Device.last_seq < pkt.seq).values(last_seq=pkt.seq)
    )
    if res.rowcount != 1:
        db.rollback()
        raise _reject(409, "replayed or out-of-order sequence number", pkt.device_id)

    patient = db.get(Patient, device.patient_id)
    if patient is None or patient.erased_at is not None:
        db.rollback()
        raise IngestError(410, "patient record has been erased")
    if not patient.consent_active:
        db.rollback()
        raise IngestError(403, "patient consent is not active")

    # 4. Confidentiality: unseal the DH + AES-GCM payload.
    keys = server_keys.load_or_create()
    try:
        plaintext = sealing.unseal(
            keys.dh_private, sealing.Sealed(epk, nonce, ct),
            device_id=pkt.device_id, seq=pkt.seq, ts=pkt.ts,
        )
        vitals = validate(json.loads(plaintext))
    except sealing.SealError as exc:
        db.rollback()
        raise _reject(400, f"payload rejected: {exc}", pkt.device_id) from exc
    except (ValueError, TypeError) as exc:
        db.rollback()
        raise IngestError(422, f"invalid vitals: {exc}") from exc

    # 5. Score using the encrypted per-patient baseline.
    dek = crypto.patient_dek(patient)
    state = (crypto.decrypt_json(dek, patient.state_enc, patient_id=patient.id, field="state")
             if patient.state_enc else new_state())
    result = infer.score(vitals, state)

    # 6. Encrypt and store. Vitals AND the clinical labels (band, AI score, reasons) are ciphertext.
    codes = [code for code, _ in result.reasons]
    payload = {**vitals, "news2": result.news2, "news2_inputs": news2_inputs_present(vitals),
               "band": result.band, "risk": result.risk, "reasons": codes}
    r_nonce, r_ct = crypto.encrypt_reading(
        dek, payload, patient_id=patient.id, device_id=device.id, seq=pkt.seq, ts=pkt.ts
    )
    db.add(Reading(patient_id=patient.id, device_id=device.id, seq=pkt.seq, ts=pkt.ts,
                   nonce=r_nonce, ciphertext=r_ct))
    patient.state_enc = crypto.encrypt_json(dek, result.state, patient_id=patient.id, field="state")
    when = datetime.fromtimestamp(pkt.ts, UTC)
    if patient.last_reading_at is None or _aware(patient.last_reading_at) <= when:
        labels.set_patient_status(dek, patient, result.band, result.risk)
        patient.last_reading_at = when
    device.last_seen = when
    rollups.add(db, patient_id=patient.id, dek=dek, ts=pkt.ts, values={**vitals, "risk": result.risk}, band=result.band)
    # (partial readings: missing vitals and a missing AI score are simply absent from every stored copy)
    upsert_alerts(db, patient.id, dek, result.reasons, when)
    db.commit()
    inspector.record(packet=pkt.model_dump(), epk=epk, server_pub=keys.dh_public_raw, nonce=nonce, ct=ct, sig=sig,
                     signed=signed, prev_seq=prev_seq, skew_s=current - pkt.ts, patient_id=patient.id,
                     key_version=patient.key_version, store_nonce=r_nonce, store_ct=r_ct,
                     vitals_count=len(vitals), scored=result.risk is not None)
    del plaintext, vitals, payload, dek  # drop plaintext references promptly
    return {"accepted": True, "band": result.band, "reasons": codes}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def upsert_alerts(db: Session, patient_id: int, dek: bytes, reasons: list[tuple[str, str]], when: datetime) -> None:
    """One open alert per patient per reason code; repeated hits update it instead of spamming.

    The reason is stored only as a blind index (HMAC-SHA-512 under a key derived from the patient's DEK) plus an
    AES-256-GCM copy, see security/labels.py. A partial unique index on the blind index guarantees the "one open
    alert" rule even when two readings for the same patient are processed at the same time; the loser of the race
    updates the winner's row.
    """
    for code, severity in reasons:
        tag = labels.alert_tag(dek, patient_id, code)
        for _ in range(3):
            existing = db.execute(
                select(Alert).where(Alert.patient_id == patient_id, Alert.reason_tag == tag, Alert.status == "open")
            ).scalar_one_or_none()
            if existing:
                existing.occurrences += 1
                existing.last_seen = max(_aware(existing.last_seen), when)
                if severity == "critical" and labels.alert_details(dek, existing)[1] != "critical":
                    existing.details_enc = labels.encrypt_alert(dek, patient_id, tag, code, "critical")
                break
            try:
                with db.begin_nested():
                    db.add(Alert(patient_id=patient_id, reason_tag=tag,
                                 details_enc=labels.encrypt_alert(dek, patient_id, tag, code, severity),
                                 first_seen=when, last_seen=when))
                break
            except IntegrityError:
                continue
