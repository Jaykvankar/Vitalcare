"""Clinical labels kept encrypted at rest: band, AI score and reason codes (our own scheme).

What a stolen database used to reveal in clear: which patients are critical, their AI scores and why. Now:

* Reading: band, risk and reasons are inside the reading's AES-256-GCM ciphertext (same AAD as the vitals).
* 5-minute rollup: the worst band is inside the rollup's AES-256-GCM blob.
* Patient: latest band and score in `last_status_enc` = AES-256-GCM(DEK, {"band", "risk"}).
* Alert: the reason code is replaced by a blind index
      reason_tag = HMAC-SHA-512(index_key, canonical("alert-reason", patient_id, code))
      index_key  = HKDF-SHA-512(DEK, info = canonical("RPM-blind-index-v1", patient_id))
  so the database can still enforce "one open alert per patient and reason", but the tag means nothing without the
  patient's key. Reason and severity are stored as AES-256-GCM(DEK, {...}, AAD binds the tag).

Rows written before this change (clear columns) are still read correctly; migration 0005 converts them.
"""
from __future__ import annotations

from .crypto import decrypt_json, encrypt_json
from .hashing import canonical, hkdf_sha512, hmac_sha512


def _index_key(dek: bytes, patient_id: int) -> bytes:
    return hkdf_sha512(dek, salt=b"", info=canonical("RPM-blind-index-v1", patient_id), length=32)


def alert_tag(dek: bytes, patient_id: int, code: str) -> str:
    return hmac_sha512(_index_key(dek, patient_id), canonical("alert-reason", patient_id, code)).hex()


def encrypt_alert(dek: bytes, patient_id: int, tag: str, code: str, severity: str) -> bytes:
    return encrypt_json(dek, {"reason_code": code, "severity": severity}, patient_id=patient_id, field=f"alert:{tag}")


def alert_details(dek: bytes, alert) -> tuple[str, str]:
    """(reason_code, severity) of an alert row, encrypted or legacy."""
    if alert.details_enc is not None:
        d = decrypt_json(dek, alert.details_enc, patient_id=alert.patient_id, field=f"alert:{alert.reason_tag}")
        return d["reason_code"], d["severity"]
    return alert.reason_code, alert.severity


def set_patient_status(dek: bytes, patient, band: str, risk: float | None) -> None:
    patient.last_status_enc = encrypt_json(dek, {"band": band, "risk": risk}, patient_id=patient.id,
                                           field="last_status")
    patient.last_band = patient.last_score = None


def patient_status(dek: bytes | None, patient) -> tuple[str | None, float | None]:
    """(band, risk) of a patient's latest reading. dek=None means "do not decrypt" (consent paused)."""
    if patient.last_status_enc is not None:
        if dek is None:
            return None, None
        d = decrypt_json(dek, patient.last_status_enc, patient_id=patient.id, field="last_status")
        return d["band"], d["risk"]
    return patient.last_band, patient.last_score


def reading_labels(payload: dict, reading) -> tuple[str | None, float | None, list[str]]:
    """(band, risk, reasons) from a decrypted reading payload, falling back to legacy clear columns."""
    if "band" in payload:
        return payload["band"], payload.get("risk"), list(payload.get("reasons") or [])
    codes = reading.reason_codes or ""
    return reading.band, reading.risk_score, [c for c in codes.split(",") if c]
