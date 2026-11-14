"""Clinical data endpoints. Every decrypt goes through rbac.patient_for_read and is audited."""
from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..ml import infer
from ..models import Alert, Assignment, Device, Patient, Reading, User
from ..readings import rollups
from ..security import audit, auth, crypto, labels, rbac

router = APIRouter(prefix="/api", tags=["patients"])

BAND_ORDER = {"critical": 0, "warning": 1, "normal": 2, None: 3}
RANGES = {"6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
MAX_POINTS = 240


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


def _alert_counts(db: Session, patient_ids: list[int]) -> dict[int, tuple[int, int]]:
    """{patient_id: (open alerts, escalated alerts)} in one query."""
    if not patient_ids:
        return {}
    rows = db.execute(
        select(Alert.patient_id, func.count(Alert.id), func.count(Alert.escalated_at))
        .where(Alert.patient_id.in_(patient_ids), Alert.status == "open").group_by(Alert.patient_id)
    ).all()
    return {pid: (n, esc) for pid, n, esc in rows}


def _summary(db: Session, p: Patient, counts: dict[int, tuple[int, int]] | None = None, *,
             decrypt: bool = True) -> dict:
    """decrypt=False (sharing paused, clinician view): the band and score stay encrypted and are not shown."""
    if counts is None:
        counts = _alert_counts(db, [p.id])
    open_alerts, escalated = counts.get(p.id, (0, 0))
    band, risk = labels.patient_status(crypto.patient_dek(p) if decrypt and p.last_status_enc else None, p)
    return {"escalated_alerts": escalated, "id": p.id, "name": p.user.full_name, "band": band, "risk": risk,
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
        select(Patient).options(joinedload(Patient.user)).join(Assignment, Assignment.patient_id == Patient.id)
        .where(Assignment.clinician_id == user.id, Patient.erased_at.is_(None))
    ).scalars().all()
    counts = _alert_counts(db, [p.id for p in rows])
    items = [_summary(db, p, counts, decrypt=p.consent_active) for p in rows]
    items.sort(key=lambda x: (BAND_ORDER.get(x["band"], 3), -(x["risk"] or 0), -x["open_alerts"]))
    return items


@router.get("/patients/{patient_id}")
def profile(patient_id: int, user: User = Depends(auth.require_role("clinician", "patient")),
            db: Session = Depends(get_db)) -> dict:
    p = rbac.patient_for_read(db, user, patient_id, need_consent=False)
    out = _summary(db, p, decrypt=p.consent_active or user.role == "patient")
    out["devices"] = [
        {"id": d.id, "label": d.label, "active": d.active, "last_seen": _iso(d.last_seen),
         "device_type": d.device_type}
        for d in db.execute(select(Device).where(Device.patient_id == p.id, Device.kind == "device")).scalars()
    ]
    out["consent_changed_at"] = _iso(p.consent_changed_at)
    if p.consent_active or user.role == "patient":
        dek = crypto.patient_dek(p)
        for f in ("dob", "phone", "address"):
            out[f] = crypto.decrypt_field(dek, getattr(p, f"{f}_enc"), patient_id=p.id, field=f)
        audit.append("decrypt_profile", actor_id=user.id, actor=user.username, target=f"patient:{p.id}")
    return out


@router.get("/patients/{patient_id}/readings")
def readings(patient_id: int, range: str = Query("6h", pattern="^(6h|24h|7d)$"),
             user: User = Depends(auth.require_role("clinician", "patient")),
             db: Session = Depends(get_db)) -> dict:
    """6 h: every reading. 24 h / 7 d: encrypted 5-minute rollups (a few hundred decrypts, not 100k)."""
    p = rbac.patient_for_read(db, user, patient_id)
    since = int(time.time()) - RANGES[range]
    dek = crypto.patient_dek(p)
    last = db.execute(select(Reading).where(Reading.patient_id == p.id)
                      .order_by(Reading.ts.desc(), Reading.id.desc()).limit(1)).scalar_one_or_none()
    latest = _point(dek, last) if last else None
    if range == "6h":
        rows = db.execute(
            select(Reading).where(Reading.patient_id == p.id, Reading.ts >= since).order_by(Reading.ts)
        ).scalars().all()
        points = [_point(dek, r) for r in rows]
        count = len(points)
    else:
        points = rollups.series(db, patient_id=p.id, dek=dek, since=since)
        count = sum(pt.pop("n") for pt in points)
    audit.append("decrypt_readings", actor_id=user.id, actor=user.username, target=f"patient:{p.id}",
                 detail=f"range={range}")
    return {"patient_id": p.id, "range": range, "count": count, "latest": latest, "points": _downsample(points),
            "model_threshold": infer.ML_THRESHOLD}   # pinned with the model's SHA-512 (model_hash.py)


def _point(dek: bytes, r: Reading) -> dict:
    v = crypto.decrypt_reading(dek, r)
    band, risk, reasons = labels.reading_labels(v, r)
    for k in ("band", "risk", "reasons"):
        v.pop(k, None)
    return {"ts": r.ts, **v, "band": band, "risk": risk, "reasons": reasons}


def _downsample(points: list[dict]) -> list[dict]:
    """Average into at most MAX_POINTS buckets; keep the worst band in each bucket."""
    if len(points) <= MAX_POINTS:
        return points
    size = len(points) / MAX_POINTS
    out = []
    keys = ("hr", "spo2", "sbp", "dbp", "temp", "rr", "risk")
    for i in range(MAX_POINTS):
        chunk = points[int(i * size):int((i + 1) * size)] or [points[-1]]
        avg = {}
        for k in keys:  # partial readings: average only the values that were measured
            vals = [c[k] for c in chunk if c.get(k) is not None]
            if vals:
                avg[k] = round(sum(vals) / len(vals), 2)
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
        code, severity = labels.alert_details(dek, a)
        out.append({
            "id": a.id, "reason_code": code, "severity": severity, "status": a.status,
            "first_seen": _iso(a.first_seen), "last_seen": _iso(a.last_seen), "occurrences": a.occurrences,
            "acknowledged_by": ack_by.full_name if ack_by else None, "acknowledged_at": _iso(a.acknowledged_at),
            "escalated_at": _iso(a.escalated_at),
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
    a.acknowledged_at = datetime.now(UTC)
    if body.note.strip():
        a.ack_note_enc = crypto.encrypt_field(crypto.patient_dek(p), body.note.strip(),
                                              patient_id=p.id, field=f"ack:{a.id}")
    db.commit()
    audit.append("alert_ack", actor_id=user.id, actor=user.username, target=f"patient:{p.id}",
                 detail=f"alert={a.id}")   # the reason stays encrypted: the ledger itself is not
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
        p.consent_changed_at = datetime.now(UTC)
        db.commit()
        audit.append("consent_granted" if body.active else "consent_revoked",
                     actor_id=user.id, actor=user.username, target=f"patient:{p.id}")
    return {"consent_active": p.consent_active}



@router.get("/me/export")
def export_my_data(user: User = Depends(auth.require_role("patient")), db: Session = Depends(get_db)) -> dict:
    """Right of access: everything held about the signed-in patient, decrypted, as one JSON document."""
    p = rbac.patient_for_read(db, user, user.patient.id if user.patient else -1, need_consent=False)
    dek = crypto.patient_dek(p)
    rows = db.execute(select(Reading).where(Reading.patient_id == p.id).order_by(Reading.ts)).scalars().all()
    alerts_rows = db.execute(select(Alert).where(Alert.patient_id == p.id).order_by(Alert.first_seen)).scalars().all()
    audit.append("data_exported", actor_id=user.id, actor=user.username, target=f"patient:{p.id}",
                 detail=f"readings={len(rows)}")
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "patient": {"name": user.full_name, "username": user.username,
                    **{f: crypto.decrypt_field(dek, getattr(p, f"{f}_enc"), patient_id=p.id, field=f)
                       for f in ("dob", "phone", "address")},
                    "consent_active": p.consent_active, "consent_changed_at": _iso(p.consent_changed_at)},
        "devices": [{"id": d.id, "label": d.label, "kind": d.kind, "active": d.active, "paired_at": _iso(d.created_at)}
                    for d in db.execute(select(Device).where(Device.patient_id == p.id)).scalars()],
        "readings": [_export_reading(dek, r) for r in rows],
        "alerts": [{"reason": code, "severity": severity, "status": a.status,
                    "first_seen": _iso(a.first_seen), "last_seen": _iso(a.last_seen)}
                   for a in alerts_rows for code, severity in [labels.alert_details(dek, a)]],
    }


def _export_reading(dek: bytes, r: Reading) -> dict:
    v = crypto.decrypt_reading(dek, r)
    band, risk, reasons = labels.reading_labels(v, r)
    for k in ("band", "risk", "reasons"):
        v.pop(k, None)
    return {"time": datetime.fromtimestamp(r.ts, UTC).isoformat(), "device": r.device_id, **v,
            "band": band, "ai_risk": risk, "reasons": ",".join(reasons)}
