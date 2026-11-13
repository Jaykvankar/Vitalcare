"""Device pairing and revocation. Allowed for admins and for clinicians assigned to the patient."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Device, Patient, User
from ..security import audit, auth, pairing, rbac, server_keys
from ..security.hashing import b64d, b64e

router = APIRouter(prefix="/api/devices", tags=["devices"])
pair_limiter = auth.RateLimiter(limit=20, window_s=60)


def _can_manage(db: Session, user: User, patient_id: int) -> Patient:
    p = db.get(Patient, patient_id)
    if p is None or (user.role == "clinician" and not rbac.can_access_patient(db, user, p)) \
            or user.role not in ("admin", "clinician"):
        raise HTTPException(404, "Patient not found")
    return p


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


@router.get("")
def list_devices(patient_id: int, user: User = Depends(auth.require_role("admin", "clinician")),
                 db: Session = Depends(get_db)) -> list[dict]:
    p = _can_manage(db, user, patient_id)
    out = []
    for d in db.execute(select(Device).where(Device.patient_id == p.id).order_by(Device.created_at)).scalars():
        by = db.get(User, d.paired_by) if d.paired_by else None
        out.append({"id": d.id, "label": d.label, "active": d.active, "last_seen": _iso(d.last_seen),
                    "paired_at": _iso(d.created_at), "paired_by": by.full_name if by else "System",
                    "revoked_at": _iso(d.revoked_at)})
    return out


class CodeIn(BaseModel):
    patient_id: int
    label: str = Field("Wearable monitor", min_length=1, max_length=64)


@router.post("/pairing-codes")
def create_code(body: CodeIn, user: User = Depends(auth.require_role("admin", "clinician")),
                db: Session = Depends(get_db)) -> dict:
    p = _can_manage(db, user, body.patient_id)
    pc, code = pairing.create(db, patient_id=p.id, label=body.label.strip(), created_by=user.id)
    audit.append("pairing_code_issued", actor_id=user.id, actor=user.username, target=f"patient:{p.id}",
                 detail=f"pairing={pc.id} label={pc.label}")
    return {"pairing_id": pc.id, "code": code, "expires_at": _iso(pc.expires_at)}


@router.get("/pairing-codes/{pairing_id}")
def code_status(pairing_id: str, user: User = Depends(auth.require_role("admin", "clinician")),
                db: Session = Depends(get_db)) -> dict:
    from ..models import PairingCode

    pc = db.get(PairingCode, pairing_id)
    if pc is None:
        raise HTTPException(404, "Not found")
    _can_manage(db, user, pc.patient_id)
    expired = (pc.expires_at if pc.expires_at.tzinfo else pc.expires_at.replace(tzinfo=timezone.utc)) < datetime.now(timezone.utc)
    status = "paired" if pc.used_at else "locked" if pc.attempts >= pairing.MAX_ATTEMPTS else "expired" if expired else "waiting"
    return {"status": status, "device_id": pc.device_id}


class PairIn(BaseModel):
    pairing_id: str = Field(max_length=32)
    public_key_pem: str = Field(max_length=2000)
    proof: str = Field(max_length=200)


@router.post("/pair")
def pair(body: PairIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Called by the device itself (no user session). Authenticated by the HMAC proof of the code."""
    pair_limiter.check(auth.client_ip(request))
    try:
        device = pairing.complete(db, pairing_id=body.pairing_id, public_key_pem=body.public_key_pem,
                                  proof_bytes=b64d(body.proof))
    except pairing.PairingError as exc:
        audit.append("pairing_failed", actor="device", target=f"pairing:{body.pairing_id}"[:64], detail=exc.message)
        raise HTTPException(exc.status, exc.message) from exc
    except ValueError as exc:
        raise HTTPException(400, "Malformed proof") from exc
    audit.append("device_paired", actor=f"device:{device.id}", target=f"patient:{device.patient_id}",
                 detail=f"pairing={body.pairing_id} label={device.label}")
    return {"device_id": device.id, "server_dh_public": b64e(server_keys.load_or_create().dh_public_raw),
            "group": "ffdhe3072"}


@router.post("/{device_id}/revoke")
def revoke(device_id: str, user: User = Depends(auth.require_role("admin", "clinician")),
           db: Session = Depends(get_db)) -> dict:
    d = db.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "Device not found")
    _can_manage(db, user, d.patient_id)
    d.active, d.revoked_at = False, datetime.now(timezone.utc)
    db.commit()
    audit.append("device_revoked", actor_id=user.id, actor=user.username, target=f"patient:{d.patient_id}",
                 detail=f"device={d.id}")
    return {"ok": True}
