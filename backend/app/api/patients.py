"""Clinical data endpoints. Every decrypt goes through rbac.patient_for_read and is audited."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, Assignment, Device, Patient, Reading, User
from ..security import audit, auth, crypto, rbac

router = APIRouter(prefix="/api", tags=["patients"])

BAND_ORDER = {"critical": 0, "warning": 1, "normal": 2, None: 3}
RANGES = {"6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
MAX_POINTS = 240


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _summary(db: Session, p: Patient) -> dict:
    open_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.patient_id == p.id, Alert.status == "open"))
    return {"id": p.id, "name": p.user.full_name, "band": p.last_band, "risk": p.last_score,
            "last_reading_at": _iso(p.last_reading_at), "open_alerts": open_alerts,
            "consent_active": p.consent_active, "data_source": _source(p.id)}


def _source(patient_id: int) -> str:
    """Where this patient's (simulated) device gets its numbers: synthetic generator or a real-data replay."""
    from ..simulator import runner

    try:
        return runner.source_for_patient(patient_id) or "none"
    except RuntimeError:
        return "unknown"


@router.get("/patients")
def worklist(user: User = Depends(auth.require_role("clinician")), db: Session = Depends(get_db)) -> list[dict]:
    """Assigned patients sorted by risk (critical first, then highest model score)."""
    rows = db.execute(
        select(Patient).join(Assignment, Assignment.patient_id == Patient.id)
        .where(Assignment.clinician_id == user.id)
    ).scalars().all()
    items = [_summary(db, p) for p in rows]
    items.sort(key=lambda x: (BAND_ORDER.get(x["band"], 3), -(x["risk"] or 0), -x["open_alerts"]))
    return items


@router.get("/patients/{patient_id}")
def profile(patient_id: int, user: User = Depends(auth.require_role("clinician", "patient")),
            db: Session = Depends(get_db)) -> dict:
    p = rbac.patient_for_read(db, user, patient_id, need_consent=False)
    out = _summary(db, p)
    out["devices"] = [
        {"id": d.id, "label": d.label, "active": d.active, "last_seen": _iso(d.last_seen)}
        for d in db.execute(select(Device).where(Device.patient_id == p.id)).scalars()
    ]
    out["consent_changed_at"] = _iso(p.consent_changed_at)
    if p.consent_active or user.role == "patient":
        dek = crypto.patient_dek(p)
        for f in ("dob", "phone", "address"):
            out[f] = crypto.decrypt_field(dek, getattr(p, f"{f}_enc"), patient_id=p.id, field=f)
        audit.append("decrypt_profile", actor_id=user.id, actor=user.username, target=f"patient:{p.id}")
    return out


@router.get("/patients/{patient_id}/readings")
def readings(patient_id: int, range: str = Query("6h", pattern="^(6h|24h|7d)$"),  # noqa: A002
             user: User = Depends(auth.require_role("clinician", "patient")),
             db: Session = Depends(get_db)) -> dict:
    p = rbac.patient_for_read(db, user, patient_id)
    since = int(time.time()) - RANGES[range]
    rows = db.execute(
        select(Reading).where(Reading.patient_id == p.id, Reading.ts >= since).order_by(Reading.ts)
    ).scalars().all()
    dek = crypto.patient_dek(p)
    points = []
    for r in rows:
        v = crypto.decrypt_reading(dek, r)
        points.append({"ts": r.ts, **v, "band": r.band, "risk": r.risk_score,
                       "reasons": [c for c in r.reason_codes.split(",") if c]})
    audit.append("decrypt_readings", actor_id=user.id, actor=user.username, target=f"patient:{p.id}",
                 detail=f"range={range}")
    latest = points[-1] if points else None
    return {"patient_id": p.id, "range": range, "count": len(points),
            "latest": latest, "points": _downsample(points)}


def _downsample(points: list[dict]) -> list[dict]:
    """Average into at most MAX_POINTS buckets; keep the worst band in each bucket."""
    if len(points) <= MAX_POINTS:
        return points
    size = len(points) / MAX_POINTS
    out = []
    keys = ("hr", "spo2", "sbp", "dbp", "temp", "rr", "risk")
    for i in range(MAX_POINTS):
        chunk = points[int(i * size):int((i + 1) * size)] or [points[-1]]
        avg = {k: round(sum(c[k] for c in chunk) / len(chunk), 2) for k in keys}
        worst = min(chunk, key=lambda c: BAND_ORDER[c["band"]])
        out.append({"ts": chunk[-1]["ts"], **avg, "band": worst["band"], "reasons": worst["reasons"]})
    return out


@router.get("/patients/{patient_id}/alerts")
def alerts(patient_id: int, status: str = Query("all", pattern="^(open|all)$"),
           user: User = Depends(auth.require_role("clinician", "patient")),
           db: Session = Depends(get_db)) -> list[dict]:
    p = rbac.patient_for_read(db, user, patient_id)
    q = select(Alert).where(Alert.patient_id == p.id)
    if status == "open":
        q = q.where(Alert.status == "open")
    rows = db.execute(q.order_by(Alert.status.desc(), Alert.last_seen.desc()).limit(100)).scalars().all()
    dek = crypto.patient_dek(p)
    out = []
    for a in rows:
        ack_by = db.get(User, a.acknowledged_by) if a.acknowledged_by else None
        out.append({
            "id": a.id, "reason_code": a.reason_code, "severity": a.severity, "status": a.status,
            "first_seen": _iso(a.first_seen), "last_seen": _iso(a.last_seen), "occurrences": a.occurrences,
            "acknowledged_by": ack_by.full_name if ack_by else None, "acknowledged_at": _iso(a.acknowledged_at),
            "note": crypto.decrypt_field(dek, a.ack_note_enc, patient_id=p.id, field=f"ack:{a.id}"),
        })
    return out


class AckIn(BaseModel):
    note: str = Field("", max_length=500)


@router.post("/alerts/{alert_id}/ack")
def acknowledge(alert_id: int, body: AckIn, user: User = Depends(auth.require_role("clinician")),
                db: Session = Depends(get_db)) -> dict:
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    p = rbac.patient_for_read(db, user, a.patient_id)
    if a.status != "open":
        raise HTTPException(409, "Alert already acknowledged")
    a.status = "acknowledged"
    a.acknowledged_by = user.id
    a.acknowledged_at = datetime.now(timezone.utc)
    if body.note.strip():
        a.ack_note_enc = crypto.encrypt_field(crypto.patient_dek(p), body.note.strip(),
                                              patient_id=p.id, field=f"ack:{a.id}")
    db.commit()
    audit.append("alert_ack", actor_id=user.id, actor=user.username, target=f"patient:{p.id}",
                 detail=f"alert={a.id} code={a.reason_code}")
    return {"ok": True}


class ConsentIn(BaseModel):
    active: bool


@router.put("/me/consent")
def set_consent(body: ConsentIn, user: User = Depends(auth.require_role("patient")),
                db: Session = Depends(get_db)) -> dict:
    p = user.patient
    if p is None:
        raise HTTPException(404, "No patient record")
    if p.consent_active != body.active:
        p.consent_active = body.active
        p.consent_changed_at = datetime.now(timezone.utc)
        db.commit()
        audit.append("consent_granted" if body.active else "consent_revoked",
                     actor_id=user.id, actor=user.username, target=f"patient:{p.id}")
    return {"consent_active": p.consent_active}
