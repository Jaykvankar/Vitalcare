"""Security inspector: show the cryptography applied to recent packets, and demonstrate attacks being blocked."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Assignment, AuditCheckpoint, AuditLog, Device, Patient, User
from ..readings import ingest
from ..security import audit, auth, inspector, server_keys, signatures

router = APIRouter(prefix="/api/security", tags=["security"])

ATTACKS = {
    "replay": ("Replay the last packet",
               "An attacker records a genuine packet and sends it again. The sequence number is not newer, so it is refused."),
    "tamper": ("Change one bit of the encrypted payload",
               "An attacker flips a single bit in transit. The SHA-512 digest no longer matches the RSA signature, "
               "so it is refused."),
    "forge": ("Sign with a stolen-looking key",
              "An attacker builds a packet but signs it with a key that is not the device's registered one. Verification fails."),
}


def _visible_devices(db: Session, user: User) -> list[Device]:
    q = select(Device).where(Device.kind == "device", Device.active.is_(True))
    if user.role == "clinician":
        q = q.join(Assignment, Assignment.patient_id == Device.patient_id).where(Assignment.clinician_id == user.id)
    return list(db.execute(q.order_by(Device.last_seen.desc())).scalars())


def _ledger(db: Session) -> dict:
    rows = db.scalar(select(func.count(AuditLog.id))) or 0
    head = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    cp = db.execute(select(AuditCheckpoint).order_by(AuditCheckpoint.id.desc()).limit(1)).scalar_one_or_none()
    out: dict = {"rows": rows, "head_hash": head.hash[:48] + "…" if head else None, "checkpoint": None}
    if cp:
        ok = signatures.ecdsa_verify(server_keys.load_or_create().ecdsa_public,
                                     audit.checkpoint_message(cp.last_audit_id, cp.head_hash), cp.signature)
        out["checkpoint"] = {"through_row": cp.last_audit_id, "signature": cp.signature.hex()[:40] + "…",
                             "algorithm": "ECDSA P-384 over SHA-512", "verified": ok}
    return out


@router.get("/inspector")
def inspector_view(user: User = Depends(auth.require_role("admin", "clinician")), db: Session = Depends(get_db)) -> dict:
    devices = _visible_devices(db, user)
    ev = inspector.evidence({d.id for d in devices})
    names = {p.id: p.user.full_name for p in db.execute(select(Patient)).scalars()}
    return {
        "devices": [{"id": d.id, "label": d.label, "device_type": d.device_type, "patient": names.get(d.patient_id, "?"),
                     "last_seen": d.last_seen.isoformat() if d.last_seen else None, "packets": ev.get(d.id, [])}
                    for d in devices],
        "ledger": _ledger(db),
        "attacks": [{"id": k, "title": v[0], "explanation": v[1]} for k, v in ATTACKS.items()],
        "can_attack": user.role == "admin",
    }


class AttackIn(BaseModel):
    device_id: str = Field(max_length=64)
    kind: str = Field(pattern="^(replay|tamper|forge)$")


@router.post("/attack")
def attack(body: AttackIn, admin: User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> dict:
    """Send a deliberately bad copy of the device's last real packet through the real ingest checks."""
    pkt = inspector.last_packet(body.device_id)
    if pkt is None:
        raise HTTPException(404, "No packet from this device yet; wait for it to send a reading")
    if body.kind == "tamper":
        ct = bytearray(base64.b64decode(pkt["ct"]))
        ct[len(ct) // 2] ^= 0x01
        pkt["ct"] = base64.b64encode(bytes(ct)).decode()
    elif body.kind == "forge":
        pkt["seq"] = pkt["seq"] + 10_000_000  # newer sequence, so only the signature can stop it
        fake = signatures.rsa_generate()
        signed = ingest.signed_message(pkt["device_id"], pkt["seq"], pkt["ts"], base64.b64decode(pkt["epk"]),
                                       base64.b64decode(pkt["nonce"]), base64.b64decode(pkt["ct"]))
        pkt["sig"] = base64.b64encode(signatures.rsa_sign_digest(fake, signed)).decode()
    audit.append("attack_demo", actor_id=admin.id, actor=admin.username, target=f"device:{body.device_id}"[:64],
                 detail=body.kind)
    try:
        ingest.process(db, ingest.Packet(**pkt))
    except ingest.IngestError as exc:
        db.rollback()
        return {"kind": body.kind, "blocked": True, "status": exc.status, "message": exc.message,
                "explanation": ATTACKS[body.kind][1]}
    return {"kind": body.kind, "blocked": False, "status": 200, "message": "accepted (this should never happen)",
            "explanation": ATTACKS[body.kind][1]}
