"""Bulk onboarding: people (staff + patients) and historical vitals, both from CSV.

Both imports run in two steps: preview (validate every row, change nothing) then commit
(all-or-nothing transaction). Each commit is recorded as an ImportBatch with the SHA-512 of the
uploaded file, and appended to the audit ledger.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
import string
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..config import get_settings
from ..db import get_db
from ..ml import infer
from ..ml.features import new_state
from ..ml.rules import validate
from ..models import Assignment, Device, ImportBatch, Patient, Reading, User
from ..readings import rollups
from ..security import audit, auth, crypto, rbac
from ..security.hashing import hash_password, sha512_hex

router = APIRouter(prefix="/api", tags=["imports"])

MAX_PEOPLE = 500
MAX_VITALS = 20_000
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,64}$")
PEOPLE_COLUMNS = ["username", "full_name", "role", "dob", "phone", "address", "care_team"]
VITAL_COLUMNS = ["timestamp", "hr", "spo2", "sbp", "dbp", "temp", "rr"]


class CsvIn(BaseModel):
    csv: str = Field(max_length=3_000_000)
    commit: bool = False


def _rows(text: str, required: list[str], limit: int) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        raise HTTPException(422, "The file is empty")
    header = [h.strip().lower() for h in reader.fieldnames]
    missing = [c for c in required if c not in header]
    if missing:
        raise HTTPException(422, f"Missing column(s): {', '.join(missing)}. Expected: {', '.join(required)}")
    reader.fieldnames = header
    rows: list[dict] = []
    for i, r in enumerate(reader, start=2):
        if len(rows) >= limit:
            raise HTTPException(422, f"Too many rows; the limit is {limit} per file")
        clean = {k: (v or "").strip() for k, v in r.items() if k}
        if any(clean.values()):
            rows.append({"line": i, **clean})
    if not rows:
        raise HTTPException(422, "No data rows found")
    return rows


def _temp_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%*-_"
    return "".join(secrets.choice(alphabet) for _ in range(16))


# ---------------------------------------------------------------- people

def _validate_people(db: Session, rows: list[dict]) -> list[dict]:
    existing = {u for (u,) in db.execute(select(User.username)).all()}
    db_clinicians = {u for (u,) in db.execute(select(User.username).where(User.role == "clinician")).all()}
    file_clinicians = {r["username"].lower() for r in rows if r.get("role", "").lower() == "clinician"}
    seen: set[str] = set()
    out = []
    for r in rows:
        errors = []
        username = r.get("username", "").lower()
        role = r.get("role", "").lower()
        if not USERNAME_RE.match(username):
            errors.append("username must be 3-64 characters: letters, digits, . _ -")
        elif username in existing:
            errors.append("username already exists")
        elif username in seen:
            errors.append("username repeated in this file")
        seen.add(username)
        if not r.get("full_name") or len(r["full_name"]) > 128:
            errors.append("full_name is required (max 128)")
        if role not in services.ROLES:
            errors.append("role must be patient, clinician or admin")
        if r.get("dob"):
            try:
                if date.fromisoformat(r["dob"]) > date.today():
                    errors.append("dob is in the future")
            except ValueError:
                errors.append("dob must be YYYY-MM-DD")
        if len(r.get("phone", "")) > 32:
            errors.append("phone too long")
        if len(r.get("address", "")) > 200:
            errors.append("address too long")
        team = [c.strip().lower() for c in r.get("care_team", "").split(";") if c.strip()]
        if team and role != "patient":
            errors.append("care_team only applies to patients")
        unknown = [c for c in team if c not in db_clinicians and c not in file_clinicians]
        if unknown:
            errors.append(f"unknown clinician(s) in care_team: {', '.join(unknown)}")
        if role != "patient" and (r.get("dob") or r.get("phone") or r.get("address")):
            errors.append("dob/phone/address are only stored for patients")
        out.append({"line": r["line"], "username": username, "full_name": r.get("full_name", ""), "role": role,
                    "care_team": team, "errors": errors,
                    "_pii": {k: r.get(k) or None for k in ("dob", "phone", "address")}})
    return out


@router.post("/admin/import/people")
def import_people(body: CsvIn, admin: User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> dict:
    auth.import_limiter.check(f"{admin.id}")
    checked = _validate_people(db, _rows(body.csv, PEOPLE_COLUMNS[:3], MAX_PEOPLE))
    n_err = sum(1 for r in checked if r["errors"])
    preview = [{k: v for k, v in r.items() if k != "_pii"} for r in checked]
    if not body.commit or n_err:
        return {"committed": False, "rows": preview, "valid": len(checked) - n_err, "invalid": n_err}

    # PBKDF2 with 210k iterations is deliberately slow; hash the temporary passwords in parallel
    # (hashlib releases the GIL), then create every account in one transaction.
    passwords = [_temp_password() for _ in checked]
    iterations = get_settings().pbkdf2_iterations
    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = list(pool.map(lambda pw: hash_password(pw, iterations), passwords))

    batch_id = secrets.token_hex(8)
    try:
        users: dict[str, User] = {}
        for r, pw_hash in zip(checked, hashes, strict=False):
            u = services.create_user(db, username=r["username"], full_name=r["full_name"], role=r["role"],
                                     password="", password_hash=pw_hash, must_change_password=True,
                                     commit=False, **r["_pii"])
            users[r["username"]] = u
        db.flush()
        for r in checked:
            for c in r["care_team"]:
                clinician = users.get(c) or db.execute(select(User).where(User.username == c)).scalar_one()
                patient = users[r["username"]].patient
                assert patient is not None  # created above as role=patient (care_team is validated)
                db.add(Assignment(clinician_id=clinician.id, patient_id=patient.id))
        db.add(ImportBatch(id=batch_id, kind="people", created_by=admin.id, rows=len(checked),
                           sha512=sha512_hex(body.csv.encode())))
        db.commit()
    except Exception:
        db.rollback()
        raise
    audit.append("people_imported", actor_id=admin.id, actor=admin.username, target=f"batch:{batch_id}",
                 detail=f"rows={len(checked)} sha512={sha512_hex(body.csv.encode())[:32]}")
    lines = ["username,full_name,role,temporary_password"] + [
        f'{r["username"]},"{r["full_name"]}",{r["role"]},{pw}' for r, pw in zip(checked, passwords, strict=False)
    ]
    return {"committed": True, "batch_id": batch_id, "created": len(checked), "rows": preview,
            "credentials_csv": "\n".join(lines) + "\n"}


# ---------------------------------------------------------------- historical vitals

def _parse_ts(value: str) -> int:
    if re.fullmatch(r"\d{9,11}", value):
        return int(value)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


@router.post("/patients/{patient_id}/import/vitals")
def import_vitals(patient_id: int, body: CsvIn, user: User = Depends(auth.require_role("clinician")),
                  db: Session = Depends(get_db)) -> dict:
    """Past readings from another system. Only a clinician on the care team may import them.

    Imported rows skip the device-signature check (a person uploaded them, not a device), so they are
    stored under a dedicated inactive 'import' device, tagged with the importer, and audited.
    """
    auth.import_limiter.check(f"{user.id}")
    p = rbac.patient_for_read(db, user, patient_id)
    raw = _rows(body.csv, VITAL_COLUMNS, MAX_VITALS)
    now = int(datetime.now(UTC).timestamp())
    parsed, errors, seen = [], [], set()
    for r in raw:
        try:
            ts = _parse_ts(r["timestamp"])
            if ts > now + 60:
                raise ValueError("timestamp is in the future")
            if ts in seen:
                raise ValueError("duplicate timestamp")
            seen.add(ts)
            parsed.append((ts, validate({k: r[k] for k in VITAL_COLUMNS[1:]})))
        except (ValueError, KeyError) as exc:
            errors.append({"line": r["line"], "error": str(exc)})
    parsed.sort(key=lambda x: x[0])
    summary = {"rows": len(raw), "valid": len(parsed), "invalid": len(errors), "errors": errors[:50],
               "from": datetime.fromtimestamp(parsed[0][0], UTC).isoformat() if parsed else None,
               "to": datetime.fromtimestamp(parsed[-1][0], UTC).isoformat() if parsed else None}
    if not body.commit or errors:
        return {"committed": False, **summary}

    batch_id = secrets.token_hex(8)
    device = Device(id=f"imp-{batch_id}", patient_id=p.id, kind="import", active=False, public_key_pem="",
                    label=f"Historical import by {user.full_name}"[:64], paired_by=user.id)
    db.add(device)
    db.flush()
    dek = crypto.patient_dek(p)
    state = new_state()  # scored on its own baseline so old data never disturbs the live one
    bands = {"normal": 0, "warning": 0, "critical": 0}
    for seq, (ts, vitals) in enumerate(parsed, start=1):
        result = infer.score(vitals, state)
        state = result.state
        nonce, ct = crypto.encrypt_reading(dek, {**vitals, "news2": result.news2}, patient_id=p.id,
                                           device_id=device.id, seq=seq, ts=ts)
        db.add(Reading(patient_id=p.id, device_id=device.id, seq=seq, ts=ts, nonce=nonce, ciphertext=ct,
                       band=result.band, risk_score=result.risk,
                       reason_codes=",".join(c for c, _ in result.reasons)))
        rollups.add(db, patient_id=p.id, dek=dek, ts=ts, values={**vitals, "risk": result.risk}, band=result.band)
        bands[result.band] += 1
    device.last_seq = len(parsed)
    digest = sha512_hex(body.csv.encode())
    db.add(ImportBatch(id=batch_id, kind="vitals", created_by=user.id, rows=len(parsed), sha512=digest, patient_id=p.id))
    db.commit()
    audit.append("vitals_imported", actor_id=user.id, actor=user.username, target=f"patient:{p.id}",
                 detail=f"batch={batch_id} rows={len(parsed)} sha512={digest[:32]}")
    return {"committed": True, "batch_id": batch_id, "bands": bands, **summary}


@router.get("/admin/import/batches")
def list_batches(_: User = Depends(auth.require_role("admin")), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(50)).scalars().all()
    out = []
    for b in rows:
        by = db.get(User, b.created_by)
        pat = db.get(Patient, b.patient_id) if b.patient_id else None
        out.append({"id": b.id, "kind": b.kind, "rows": b.rows, "by": by.full_name if by else "?",
                    "patient": pat.user.full_name if pat else None, "sha512": b.sha512[:32],
                    "created_at": b.created_at.isoformat()})
    return out
