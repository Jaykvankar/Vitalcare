"""Encrypted 5-minute rollups of readings (uses the existing AES-256-GCM envelope scheme).

Each rollup stores count, sums, min and max per vital, encrypted under the patient's DEK with
AAD = ("rollup", patient_id, bucket_ts). Only the worst band in the bucket is kept in clear,
the same level of detail already stored per reading.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import ReadingRollup
from ..security import aead
from ..security.hashing import canonical

BUCKET_S = 300
KEYS = ("hr", "spo2", "sbp", "dbp", "temp", "rr", "risk")
BAND_RANK = {"normal": 0, "warning": 1, "critical": 2}


def _aad(patient_id: int, bucket_ts: int) -> bytes:
    return canonical("rollup", patient_id, bucket_ts)


def _empty() -> dict:
    return {"n": 0, "sum": {k: 0.0 for k in KEYS}, "min": {}, "max": {}}


def decrypt(dek: bytes, r: ReadingRollup) -> dict:
    import json

    return json.loads(aead.open_blob(dek, r.blob, _aad(r.patient_id, r.bucket_ts)))


def _encrypt(dek: bytes, patient_id: int, bucket_ts: int, data: dict) -> bytes:
    import json

    return aead.seal_blob(dek, json.dumps(data, separators=(",", ":")).encode(), _aad(patient_id, bucket_ts))


def add(db: Session, *, patient_id: int, dek: bytes, ts: int, values: dict, band: str) -> None:
    """Fold one reading into its bucket. Retries if another writer created the bucket first."""
    bucket = ts - ts % BUCKET_S
    for _ in range(3):
        row = db.execute(select(ReadingRollup).where(ReadingRollup.patient_id == patient_id,
                                                     ReadingRollup.bucket_ts == bucket)).scalar_one_or_none()
        data = decrypt(dek, row) if row else _empty()
        data["n"] += 1
        for k in KEYS:
            v = float(values[k])
            data["sum"][k] += v
            data["min"][k] = min(v, data["min"].get(k, v))
            data["max"][k] = max(v, data["max"].get(k, v))
        blob = _encrypt(dek, patient_id, bucket, data)
        if row:
            row.blob = blob
            if BAND_RANK[band] > BAND_RANK[row.worst_band]:
                row.worst_band = band
            return
        try:
            with db.begin_nested():
                db.add(ReadingRollup(patient_id=patient_id, bucket_ts=bucket, blob=blob, worst_band=band))
            return
        except IntegrityError:
            continue


def series(db: Session, *, patient_id: int, dek: bytes, since: int) -> list[dict]:
    """Rollups as chart points (bucket means)."""
    rows = db.execute(select(ReadingRollup).where(ReadingRollup.patient_id == patient_id,
                                                  ReadingRollup.bucket_ts >= since)
                      .order_by(ReadingRollup.bucket_ts)).scalars().all()
    out = []
    for r in rows:
        d = decrypt(dek, r)
        n = max(1, d["n"])
        out.append({"ts": r.bucket_ts + BUCKET_S // 2, "n": d["n"],
                    **{k: round(d["sum"][k] / n, 2) for k in KEYS}, "band": r.worst_band, "reasons": []})
    return out
