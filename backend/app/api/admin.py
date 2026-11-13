"""Admin endpoints. Admins manage accounts, devices and assignments but can never decrypt clinical data."""
from __future__ import annotations

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import services
from ..config import get_settings
from ..db import get_db
from ..ml import realdata
from ..ml.synth import EPISODES
from ..models import Assignment, AuditLog, Device, Patient, User
from ..security import audit, auth, server_keys
from ..security.hashing import sha512_hex
from ..security.sealing import public_bytes
from ..simulator import runner

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_only = auth.require_role("admin")


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    full_name: str = Field(min_length=1, max_length=128)
    role: str = Field(pattern="^(admin|clinician|patient)$")
    password: str = Field(min_length=12, max_length=256)
    dob: str | None = Field(None, max_length=32)
    phone: str | None = Field(None, max_length=32)
    address: str | None = Field(None, max_length=200)
    with_device: bool = True


@router.get("/users")
def list_users(_: User = Depends(admin_only), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "active": u.active,
         "mfa_enrolled": u.totp_confirmed, "patient_id": u.patient.id if u.patient else None}
        for u in db.execute(select(User).order_by(User.role, User.username)).scalars()
    ]


@router.post("/users")
def create_user(body: UserIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    try:
        user = services.create_user(db, username=body.username, full_name=body.full_name, role=body.role,
                                    password=body.password, dob=body.dob, phone=body.phone, address=body.address)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Username already exists") from exc
    if user.patient and body.with_device:
        services.provision_simulated_device(db, user.patient.id, "Wearable monitor", created_by=admin.id)
    audit.append("user_created", actor_id=admin.id, actor=admin.username, target=f"user:{user.id}",
                 detail=f"role={user.role}")
    return {"id": user.id}


class ActiveIn(BaseModel):
    active: bool


@router.post("/users/{user_id}/active")
def set_active(user_id: int, body: ActiveIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(400, "You cannot deactivate yourself")
    u.active = body.active
    db.commit()
    audit.append("user_activated" if body.active else "user_deactivated", actor_id=admin.id,
                 actor=admin.username, target=f"user:{u.id}")
    return {"ok": True}


@router.post("/users/{user_id}/reset-mfa")
def reset_mfa(user_id: int, admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    u.totp_secret_enc, u.totp_key_version, u.totp_confirmed = None, None, False
    db.commit()
    audit.append("mfa_reset", actor_id=admin.id, actor=admin.username, target=f"user:{u.id}")
    return {"ok": True}


@router.get("/patients")
def list_patients(_: User = Depends(admin_only), db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for p in db.execute(select(Patient)).scalars():
        devices = db.execute(select(Device).where(Device.patient_id == p.id, Device.active.is_(True))).scalars().all()
        out.append({"id": p.id, "name": p.user.full_name, "username": p.user.username,
                    "consent_active": p.consent_active, "key_version": p.key_version,
                    "devices": [{"id": d.id, "label": d.label} for d in devices],
                    "simulating": runner.enabled.get(p.id, False),
                    "simulator_status": runner.last_result.get(p.id),
                    "source": runner.source_for_patient(p.id)})
    return out


class AssignmentIn(BaseModel):
    clinician_id: int
    patient_id: int


@router.get("/assignments")
def list_assignments(_: User = Depends(admin_only), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(Assignment)).scalars().all()
    out = []
    for a in rows:
        c, p = db.get(User, a.clinician_id), db.get(Patient, a.patient_id)
        out.append({"id": a.id, "clinician_id": c.id, "clinician": c.full_name,
                    "patient_id": p.id, "patient": p.user.full_name})
    return out


@router.post("/assignments")
def add_assignment(body: AssignmentIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    c, p = db.get(User, body.clinician_id), db.get(Patient, body.patient_id)
    if c is None or c.role != "clinician" or p is None:
        raise HTTPException(400, "Need an existing clinician and patient")
    try:
        db.add(Assignment(clinician_id=c.id, patient_id=p.id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Already assigned") from exc
    audit.append("assignment_added", actor_id=admin.id, actor=admin.username,
                 target=f"patient:{p.id}", detail=f"clinician={c.id}")
    return {"ok": True}


@router.delete("/assignments/{assignment_id}")
def remove_assignment(assignment_id: int, admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    a = db.get(Assignment, assignment_id)
    if a is None:
        raise HTTPException(404, "Not found")
    db.delete(a)
    db.commit()
    audit.append("assignment_removed", actor_id=admin.id, actor=admin.username,
                 target=f"patient:{a.patient_id}", detail=f"clinician={a.clinician_id}")
    return {"ok": True}


class DeviceIn(BaseModel):
    patient_id: int
    label: str = Field("Wearable monitor", max_length=64)


@router.post("/devices")
def add_device(body: DeviceIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    if db.get(Patient, body.patient_id) is None:
        raise HTTPException(404, "Patient not found")
    d = services.provision_simulated_device(db, body.patient_id, body.label, created_by=admin.id)
    audit.append("device_registered", actor_id=admin.id, actor=admin.username,
                 target=f"patient:{body.patient_id}", detail=f"device={d.id}")
    return {"id": d.id}


@router.get("/audit")
def audit_log(before: int | None = None, limit: int = Query(50, le=200),
              _: User = Depends(admin_only), db: Session = Depends(get_db)) -> list[dict]:
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if before:
        q = q.where(AuditLog.id < before)
    return [{"id": r.id, "ts": r.ts, "actor": r.actor, "action": r.action, "target": r.target,
             "detail": r.detail, "hash": r.hash[:16]} for r in db.execute(q).scalars()]


@router.post("/audit/verify")
def audit_verify(admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    result = audit.verify(db)
    audit.append("audit_verified", actor_id=admin.id, actor=admin.username, detail=f"ok={result['ok']}")
    return result


@router.post("/audit/checkpoint")
def audit_checkpoint(admin: User = Depends(admin_only)) -> dict:
    audit.checkpoint_now()
    return {"ok": True}


class SimIn(BaseModel):
    patient_id: int
    enabled: bool


@router.post("/simulator")
def simulator_toggle(body: SimIn, admin: User = Depends(admin_only)) -> dict:
    runner.set_enabled(body.patient_id, body.enabled)
    runner.start()
    audit.append("simulator_on" if body.enabled else "simulator_off", actor_id=admin.id,
                 actor=admin.username, target=f"patient:{body.patient_id}")
    return {"ok": True}


class EpisodeIn(BaseModel):
    patient_id: int
    kind: str


@router.post("/simulator/episode")
def simulator_episode(body: EpisodeIn, admin: User = Depends(admin_only)) -> dict:
    if body.kind not in EPISODES:
        raise HTTPException(400, f"kind must be one of {sorted(EPISODES)}")
    if not runner.trigger(body.patient_id, body.kind):
        raise HTTPException(404, "No simulated device for this patient")
    audit.append("simulator_episode", actor_id=admin.id, actor=admin.username,
                 target=f"patient:{body.patient_id}", detail=body.kind)
    return {"ok": True}


@router.get("/simulator/sources")
def simulator_sources(_: User = Depends(admin_only)) -> dict:
    return {"available": realdata.available(), "sources": realdata.replay_sources()}


class SourceIn(BaseModel):
    patient_id: int
    source: str = Field(max_length=64)


@router.post("/simulator/source")
def simulator_source(body: SourceIn, admin: User = Depends(admin_only)) -> dict:
    if body.source != "synthetic" and realdata.stream_for_source(body.source) is None:
        raise HTTPException(400, "Unknown data source")
    if not runner.set_source(body.patient_id, body.source):
        raise HTTPException(404, "No simulated device for this patient")
    audit.append("simulator_source", actor_id=admin.id, actor=admin.username,
                 target=f"patient:{body.patient_id}", detail=body.source)
    return {"ok": True}


class SimPairIn(BaseModel):
    pairing_id: str = Field(max_length=32)
    code: str = Field(min_length=12, max_length=20)
    source: str = Field("synthetic", max_length=64)


@router.post("/simulator/pair")
def simulator_pair(body: SimPairIn, admin: User = Depends(admin_only)) -> dict:
    """Make the simulator act as a new physical device that was handed a pairing code."""
    try:
        device_id = runner.pair_over_http(body.pairing_id, body.code, body.source)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"device_id": device_id}


@router.get("/keys")
def key_status(_: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    keys = server_keys.load_or_create()
    by_version = dict(db.execute(select(Patient.key_version, func.count()).group_by(Patient.key_version)).all())
    return {
        "master_key_version": get_settings().master_key_version,
        "patients_by_key_version": {str(k): v for k, v in by_version.items()},
        "dh_public_fingerprint": sha512_hex(public_bytes(keys.dh_private.public_key()))[:32],
        "audit_key_fingerprint": sha512_hex(
            keys.ecdsa_public.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        )[:32],
        "algorithms": {
            "readings_at_rest": "AES-256-GCM, per-patient DEK wrapped by AES-256-GCM master key",
            "device_payload": "Diffie-Hellman ffdhe3072 + HKDF-SHA-512 + AES-256-GCM",
            "device_signature": "RSA-3072-PSS, sign-the-digest (SHA-512)",
            "audit_checkpoint": "ECDSA P-384 with SHA-512",
            "passwords": "PBKDF2-HMAC-SHA-512, 210000 iterations",
            "mfa": "TOTP with HMAC-SHA-512",
        },
    }
