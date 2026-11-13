"""Seed demo data: 1 admin, 2 clinicians, 4 patients, devices, assignments, and 24 h of encrypted history.

    python -m app.seed            (from backend/, server stopped)

History readings go through the same seal -> sign -> ingest.process() path as live traffic.
Credentials (passwords + TOTP secrets) are written to seed_credentials.txt (gitignored), never to the UI.
"""
from __future__ import annotations

import os
import secrets
import string
import sys
import time
from pathlib import Path

from sqlalchemy import select

from . import services
from .config import PROJECT_DIR, get_settings
from .db import SessionLocal, create_schema, init_engine
from .ml import realdata
from .ml.synth import PatientStream
from .models import Assignment, User
from .readings import ingest
from .security import audit, auth, server_keys
from .simulator import build_packet, runner, stream_for

HISTORY_HOURS = int(os.environ.get("RPM_SEED_HISTORY_HOURS", "24"))
HISTORY_STEP_S = 600  # one historical reading every 10 minutes

PEOPLE: list[tuple[str, str, str, dict[str, str]]] = [
    ("admin", "Asha Admin", "admin", {}),
    ("dr.mehta", "Dr. Kiran Mehta", "clinician", {}),
    ("dr.rao", "Dr. Priya Rao", "clinician", {}),
    ("p.sharma", "Rohan Sharma", "patient", {"dob": "1958-03-14", "phone": "+91 98200 11111", "address": "12 Lake Road, Pune"}),
    ("p.iyer", "Meera Iyer", "patient", {"dob": "1971-09-02", "phone": "+91 98200 22222", "address": "4 MG Road, Bengaluru"}),
    ("p.khan", "Imran Khan", "patient", {"dob": "1949-12-23", "phone": "+91 98200 33333", "address": "88 Park Street, Kolkata"}),
    ("p.das", "Ananya Das", "patient", {"dob": "1985-06-30", "phone": "+91 98200 44444", "address": "7 Marine Drive, Mumbai"}),
]
# clinician -> patients
ASSIGN = {"dr.mehta": ["p.sharma", "p.iyer", "p.khan"], "dr.rao": ["p.khan", "p.das"]}
# history episodes so charts and alerts have something to show: patient -> (hours ago, kind)
# This patient's device replays a real ICU stay from the MIMIC-III demo (if downloaded)
REAL_PATIENT = "p.khan"


def pick_mimic_stay() -> str:
    """A long stay of a patient who died in hospital: real deterioration for the demo."""
    stays = realdata.load_mimic()
    died = [(len(s["rows"]), k) for k, s in stays.items() if s["died_in_hospital"] and len(s["rows"]) >= 144]
    pool = died or [(len(s["rows"]), k) for k, s in stays.items()]
    return max(pool)[1]


HISTORY_EPISODES = {"p.khan": [(5, "hypoxia")], "p.iyer": [(14, "fever")], "p.sharma": [(9, "activity")]}


def strong_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%^*-_"
    return "".join(secrets.choice(alphabet) for _ in range(16))


def main() -> None:
    s = get_settings()
    init_engine(s.database_url)
    db_path = s.database_url.removeprefix("sqlite:///")
    create_schema()
    db = SessionLocal()
    if db.execute(select(User)).first():
        print("Database already has users; delete backend/data/ and simulator_keys/ to reseed.")
        sys.exit(1)
    keys = server_keys.load_or_create()

    creds = []
    recovery: dict[str, list[str]] = {}
    users: dict[str, User] = {}
    for username, name, role, pii in PEOPLE:
        pw = strong_password()
        u = services.create_user(db, username=username, full_name=name, role=role, password=pw,
                                 dob=pii.get("dob"), phone=pii.get("phone"), address=pii.get("address"))
        totp_secret = ""
        if role in auth.MFA_ROLES:
            totp_secret = auth.new_totp_secret()
            auth.store_totp_secret(u, totp_secret)
            u.totp_confirmed = True
            db.commit()
            recovery[username] = auth.issue_recovery_codes(db, u)
        users[username] = u
        creds.append((username, role, pw, totp_secret))
        audit.append("user_created", actor="seed", target=f"user:{u.id}", detail=f"role={role}")

    for clin, pats in ASSIGN.items():
        for p in pats:
            patient = users[p].patient
            assert patient is not None
            db.add(Assignment(clinician_id=users[clin].id, patient_id=patient.id))
    db.commit()

    now = int(time.time())
    for username, *_ in PEOPLE:
        u = users[username]
        if u.role != "patient":
            continue
        source = "synthetic"
        assert u.patient is not None
        if username == REAL_PATIENT and realdata.available()["mimic"]:
            source = f"mimic:{pick_mimic_stay()}"
        dev = services.provision_simulated_device(db, u.patient.id, "Wearable monitor",
                                                  created_by=users["admin"].id, source=source)
        priv = runner.keystore.private_key(dev.id)
        stream = stream_for(dev.id, source)
        starts: dict[int, str] = {}
        if isinstance(stream, PatientStream):
            stream.episode_rate = stream.activity_rate = 0.0
        if source == "synthetic":
            starts = {now - h * 3600: kind for h, kind in HISTORY_EPISODES.get(username, [])}
        t0 = now - HISTORY_HOURS * 3600
        n = 0
        for ts in range(t0, now - 60, HISTORY_STEP_S):
            for st, kind in list(starts.items()):
                if ts >= st:
                    stream.start(kind, scale=0.15)
                    del starts[st]
            vitals, _, _ = stream.step()
            pkt = build_packet(dev.id, priv, keys.dh_public_raw, vitals, ts=ts, seq=ts * 1000)
            ingest.process(db, ingest.Packet(**pkt), now=ts)
            n += 1
        if source != "synthetic":
            runner.keystore.set_source(dev.id, source, offset=n)  # live replay continues after the history
        print(f"  {username}: {n} encrypted readings via device {dev.id} (source: {source})")

    db.close()
    audit.checkpoint_now()

    out = Path(os.environ.get("RPM_SEED_CREDENTIALS", PROJECT_DIR / "seed_credentials.txt"))
    lines = ["# Demo credentials (gitignored). TOTP uses SHA-512, 6 digits, 30 s.",
             "# Add the secret to Aegis / 2FAS / FreeOTP with algorithm SHA512, or run:",
             "#   .venv\\Scripts\\python scripts\\totp_code.py <username>", ""]
    for username, role, pw, totp_secret in creds:
        lines.append(f"{username:10} {role:9} password={pw}" + (f"  totp_secret={totp_secret}" if totp_secret else ""))
        if username in recovery:
            lines.append(f"{'':10} recovery codes: {' '.join(recovery[username])}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Seeded {len(PEOPLE)} users. Database: {db_path}. Credentials written to {out}")


if __name__ == "__main__":
    main()
