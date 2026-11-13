"""Tests for hardening, onboarding and clinical-workflow features."""
import hashlib
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update


def raw_client(world):
    c = TestClient(world["app"], base_url="https://testserver")
    c.headers["X-RPM-Request"] = "1"
    return c


def reset_totp_guard():
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    db.execute(update(User).values(totp_last_step=0))
    db.commit()
    db.close()


# ---------------------------------------------------------------- phase 1: hardening

def test_audit_chain_cannot_fork(world):
    """UNIQUE(prev_hash) rejects a second row appended after the same head (another process racing)."""
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal
    from app.models import AuditLog
    from app.security import audit

    audit.append("fork_probe")
    db = SessionLocal()
    head = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    db.add(AuditLog(ts="x", actor="evil", action="fork", target="", detail="", prev_hash=head.prev_hash, hash="f" * 128))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()
    audit.append("after_fork_probe")  # normal appends still work


def test_totp_code_cannot_be_reused(world):
    from app.db import SessionLocal
    from app.models import User
    from app.security import auth

    reset_totp_guard()
    db = SessionLocal()
    u = db.query(User).filter_by(username="clin2").one()
    code = pyotp.TOTP(world["totp"]["clin2"], digest=hashlib.sha512).now()
    assert auth.verify_totp(db, u, code)
    assert not auth.verify_totp(db, u, code)  # same code again: replay blocked (stored in DB)
    db.close()
    reset_totp_guard()


def test_recovery_codes_work_once(world, client_for):
    c = client_for("clin2")
    codes = c.post("/api/auth/recovery-codes").json()["recovery_codes"]
    assert len(codes) == 10
    assert c.get("/api/auth/me").json()["recovery_codes_left"] == 10

    fresh = raw_client(world)
    assert fresh.post("/api/auth/login", json={"username": "clin2", "password": world["pw"]}).json()["mfa"] == "verify"
    assert fresh.post("/api/auth/mfa", json={"code": codes[0]}).status_code == 200
    assert fresh.get("/api/auth/me").json()["recovery_codes_left"] == 9

    again = raw_client(world)
    again.post("/api/auth/login", json={"username": "clin2", "password": world["pw"]})
    assert again.post("/api/auth/mfa", json={"code": codes[0]}).status_code == 401  # used up


def test_admin_created_user_must_change_password(world, client_for):
    admin = client_for("admin")
    r = admin.post("/api/admin/users", json={"username": "newnurse", "full_name": "New Nurse", "role": "patient",
                                             "password": "initial-pass-1234", "with_device": False})
    assert r.status_code == 200
    c = raw_client(world)
    r = c.post("/api/auth/login", json={"username": "newnurse", "password": "initial-pass-1234"})
    assert r.json()["user"]["must_change_password"] is True
    pid = r.json()["user"]["patient_id"]
    assert c.get(f"/api/patients/{pid}").status_code == 403  # blocked until changed
    assert c.post("/api/auth/password", json={"current_password": "initial-pass-1234",
                                              "new_password": "short"}).status_code == 422
    r = c.post("/api/auth/password", json={"current_password": "initial-pass-1234",
                                           "new_password": "a-much-better-passphrase"})
    assert r.status_code == 200
    assert c.get(f"/api/patients/{pid}").status_code == 200


def test_readiness_endpoint(world):
    r = raw_client(world).get("/api/health/ready")
    assert r.status_code == 200 and r.json()["ready"] is True
    assert "X-Request-ID" in r.headers


# ---------------------------------------------------------------- phase 2: onboarding

PEOPLE_CSV = """username,full_name,role,dob,phone,address,care_team
dr.import,Dr Import Test,clinician,,,,
p.import1,Imported One,patient,1970-05-01,+1 555 0100,1 Main St,dr.import;clin1
p.import2,Imported Two,patient,1980-02-02,,,dr.import
"""


def test_people_import_preview_then_commit(world, client_for):
    admin = client_for("admin")
    bad = PEOPLE_CSV + "BAD NAME,x,doctor,31-12-2000,,,nobody\n"
    r = admin.post("/api/admin/import/people", json={"csv": bad, "commit": True})
    assert r.status_code == 200 and r.json()["committed"] is False and r.json()["invalid"] == 1
    errors = next(row for row in r.json()["rows"] if row["errors"])["errors"]
    assert any("username" in e for e in errors) and any("role" in e for e in errors)

    r = admin.post("/api/admin/import/people", json={"csv": PEOPLE_CSV, "commit": False})
    assert r.json()["valid"] == 3 and r.json()["committed"] is False
    r = admin.post("/api/admin/import/people", json={"csv": PEOPLE_CSV, "commit": True})
    assert r.json()["committed"] is True and r.json()["created"] == 3
    creds = r.json()["credentials_csv"].splitlines()
    assert creds[0] == "username,full_name,role,temporary_password" and len(creds) == 4

    # imported patient is on dr.import's and clin1's care teams; personal details are encrypted
    p1_pw = creds[2].split(",")[-1]
    c = raw_client(world)
    r = c.post("/api/auth/login", json={"username": "p.import1", "password": p1_pw})
    assert r.json()["user"]["must_change_password"] is True
    names = [p["name"] for p in client_for("clin1").get("/api/patients").json()]
    assert "Imported One" in names
    # importing the same file again fails validation (usernames exist)
    assert admin.post("/api/admin/import/people", json={"csv": PEOPLE_CSV, "commit": True}).json()["invalid"] == 3


def test_vitals_import(world, client_for):
    c = client_for("clin1")
    pid = world["ids"]["p1"]
    base = datetime.now(UTC) - timedelta(hours=20)
    lines = ["timestamp,hr,spo2,sbp,dbp,temp,rr"]
    for i in range(30):
        ts = (base + timedelta(minutes=10 * i)).isoformat()
        lines.append(f"{ts},{75 + i % 5},{97},{120},{78},{36.8},{15}")
    lines.append(f"{(base + timedelta(hours=6)).isoformat()},130,85,85,50,39.5,30")  # one critical row
    csv_text = "\n".join(lines) + "\n"
    bad = csv_text + "not-a-date,70,98,120,80,36.7,14\n"
    assert c.post(f"/api/patients/{pid}/import/vitals", json={"csv": bad, "commit": True}).json()["invalid"] == 1
    r = c.post(f"/api/patients/{pid}/import/vitals", json={"csv": csv_text, "commit": True})
    assert r.status_code == 200, r.text
    assert r.json()["committed"] and r.json()["bands"]["critical"] >= 1
    pts = c.get(f"/api/patients/{pid}/readings?range=24h").json()
    assert pts["count"] >= 31  # served from encrypted rollups
    # admin cannot import vitals; unassigned clinician cannot either
    assert client_for("admin").post(f"/api/patients/{pid}/import/vitals", json={"csv": csv_text}).status_code == 403
    assert client_for("clin2").post(f"/api/patients/{pid}/import/vitals", json={"csv": csv_text}).status_code == 404


# ---------------------------------------------------------------- phase 3: workflow

def test_critical_alert_escalates(world):
    from app import jobs
    from app.db import SessionLocal
    from app.models import Alert

    db = SessionLocal()
    a = db.query(Alert).filter_by(patient_id=world["ids"]["p1"], status="open", severity="critical").first()
    assert a is not None
    db.close()
    assert jobs.escalate_alerts(now=datetime.now(UTC) + timedelta(minutes=20)) >= 1
    assert jobs.escalate_alerts(now=datetime.now(UTC) + timedelta(minutes=21)) == 0  # idempotent


def test_patient_can_export_own_data(world, client_for):
    r = client_for("pat1").get("/api/me/export")
    assert r.status_code == 200
    data = r.json()
    assert data["patient"]["dob"] == "1960-01-01" and len(data["readings"]) >= 1
    assert "spo2" in data["readings"][0]
    assert client_for("clin1").get("/api/me/export").status_code == 403


def test_erasure_crypto_shreds_patient(world, client_for):
    from app.db import SessionLocal
    from app.models import Patient
    from app.security import crypto

    admin = client_for("admin")
    admin.post("/api/admin/users", json={"username": "p.erase", "full_name": "To Erase", "role": "patient",
                                         "password": "erase-me-please-123", "dob": "1990-01-01", "with_device": False})
    db = SessionLocal()
    p = db.query(Patient).join(Patient.user).filter_by(username="p.erase").one()
    pid, wrapped = p.id, p.wrapped_dek
    db.close()

    assert admin.post(f"/api/admin/patients/{pid}/erase", json={"confirm_username": "wrong"}).status_code == 400
    assert admin.post(f"/api/admin/patients/{pid}/erase", json={"confirm_username": "p.erase"}).status_code == 200

    db = SessionLocal()
    p = db.get(Patient, pid)
    assert p.erased_at is not None and p.wrapped_dek != wrapped and p.dob_enc is None
    with pytest.raises(Exception):
        crypto.patient_dek(p)  # the key is gone: nothing encrypted under it can be read again
    db.close()
    c = raw_client(world)
    assert c.post("/api/auth/login", json={"username": "p.erase", "password": "erase-me-please-123"}).status_code == 401


def test_retention_purges_old_readings(world):
    from app import jobs
    from app.db import SessionLocal
    from app.models import Reading

    db = SessionLocal()
    before = db.query(Reading).count()
    db.close()
    far_future = datetime.now(UTC) + timedelta(days=4000)
    assert jobs.apply_retention(now=far_future) == before


def test_access_log_carries_request_id(world, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="rpm.access")
    r = raw_client(world).get("/api/health", headers={"X-Request-ID": "trace-12345678"})
    assert r.headers["X-Request-ID"] == "trace-12345678"
    from app.logging_setup import JsonFormatter

    line = next(rec for rec in caplog.records if rec.name == "rpm.access")
    assert '"request_id":"trace-12345678"' in JsonFormatter().format(line)


def test_demo_code_only_in_demo_mode_for_seeded_accounts_after_password(world):
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import User
    from app.security import auth

    c = raw_client(world)
    assert c.get("/api/auth/demo-code").status_code == 404           # demo mode off by default
    settings = get_settings()
    settings.demo_mode = True
    try:
        assert c.get("/api/auth/demo-code").status_code == 401       # no password yet
        c.post("/api/auth/login", json={"username": "clin2", "password": world["pw"]})
        assert c.get("/api/auth/demo-code").status_code == 404       # not a seeded demo account

        db = SessionLocal()
        db.query(User).filter_by(username="clin2").update({"demo_account": True})
        db.commit()
        db.close()
        r = c.get("/api/auth/demo-code")
        assert r.status_code == 200
        expected = pyotp.TOTP(world["totp"]["clin2"], digest=hashlib.sha512).now()
        assert r.json()["code"] == expected and 0 < r.json()["seconds_left"] <= 30
        reset_totp_guard()
        assert c.post("/api/auth/mfa", json={"code": r.json()["code"]}).status_code == 200
        assert c.get("/api/auth/demo-code").status_code == 404       # nothing to show once signed in
    finally:
        settings.demo_mode = False
        db = SessionLocal()
        db.query(User).filter_by(username="clin2").update({"demo_account": False})
        db.commit()
        db.close()
        auth.mfa_limiter.reset()
