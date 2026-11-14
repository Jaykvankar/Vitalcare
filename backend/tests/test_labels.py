"""Band, AI score and reason codes are encrypted at rest (security/labels.py, migration 0005)."""
import json
import time

from fastapi.testclient import TestClient


def send(world, vitals, key="dev_key", device="dev_id"):
    from app.security import server_keys
    from app.simulator import build_packet
    from tests.conftest import next_seq

    pkt = build_packet(world[device], world[key], server_keys.load_or_create().dh_public_raw, vitals,
                       ts=int(time.time()), seq=next_seq(world[device]))
    return TestClient(world["app"], base_url="https://testserver").post("/api/ingest", json=pkt)


CRITICAL = {"hr": 131, "spo2": 85, "sbp": 118, "dbp": 74, "temp": 37.1, "rr": 26}


def test_database_holds_no_clear_labels_but_the_app_shows_them(world, client_for):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Alert, Patient, Reading, ReadingRollup

    assert send(world, CRITICAL).status_code == 200
    db = SessionLocal()
    pid = world["ids"]["p1"]
    last = db.execute(select(Reading).where(Reading.patient_id == pid).order_by(Reading.id.desc()).limit(1)).scalar_one()
    assert (last.band, last.risk_score, last.reason_codes) == (None, None, None)
    p = db.get(Patient, pid)
    assert p.last_band is None and p.last_score is None and p.last_status_enc is not None
    assert all(r.worst_band is None for r in db.execute(select(ReadingRollup).where(ReadingRollup.patient_id == pid))
               .scalars())
    for a in db.execute(select(Alert).where(Alert.patient_id == pid)).scalars():
        assert a.reason_code is None and a.severity is None and len(a.reason_tag) == 128
    raw = b"".join(str(v).encode() for v in (last.nonce, last.ciphertext))
    assert b"critical" not in raw and b"SPO2_LOW" not in raw
    db.close()

    c = client_for("clin1")
    six = c.get(f"/api/patients/{pid}/readings?range=6h").json()
    from app.ml import infer
    assert six["model_threshold"] == infer.ML_THRESHOLD                      # the UI shows the pinned threshold
    latest = six["latest"]
    assert latest["band"] == "critical" and "SPO2_LOW" in latest["reasons"] and latest["risk"] is not None
    worklist = {x["id"]: x for x in c.get("/api/patients").json()}
    assert worklist[pid]["band"] == "critical"
    alerts = c.get(f"/api/patients/{pid}/alerts?status=open").json()
    assert any(a["reason_code"] == "SPO2_LOW" and a["severity"] == "critical" for a in alerts)
    assert c.get(f"/api/patients/{pid}/readings?range=24h").json()["points"][-1]["band"] == "critical"
    export = client_for("pat1").get("/api/me/export").json()
    assert export["readings"][-1]["band"] == "critical" and "SPO2_LOW" in export["readings"][-1]["reasons"]


def test_paused_sharing_hides_the_band_from_the_worklist(world, client_for):
    pid = world["ids"]["p1"]
    pat = client_for("pat1")
    assert pat.put("/api/me/consent", json={"active": False}).status_code == 200
    try:
        row = next(x for x in client_for("clin1").get("/api/patients").json() if x["id"] == pid)
        assert row["band"] is None and row["risk"] is None and row["consent_active"] is False
        assert pat.get(f"/api/patients/{pid}").json()["band"] is not None      # the patient still sees their own
    finally:
        assert pat.put("/api/me/consent", json={"active": True}).status_code == 200


def test_blind_index_keeps_one_open_alert_per_reason(world):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Alert, Patient
    from app.security import crypto, labels

    assert send(world, CRITICAL).status_code == 200
    assert send(world, CRITICAL).status_code == 200
    db = SessionLocal()
    p1, p2 = db.get(Patient, world["ids"]["p1"]), db.get(Patient, world["ids"]["p2"])
    tag = labels.alert_tag(crypto.patient_dek(p1), p1.id, "SPO2_LOW")
    rows = db.execute(select(Alert).where(Alert.patient_id == p1.id, Alert.status == "open",
                                          Alert.reason_tag == tag)).scalars().all()
    assert len(rows) == 1 and rows[0].occurrences >= 2
    assert labels.alert_tag(crypto.patient_dek(p2), p2.id, "SPO2_LOW") != tag    # same reason, unlinkable tags
    db.close()


def test_migration_0005_encrypts_existing_clear_labels(env, tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from app import models  # noqa: F401
    from app.config import BACKEND_DIR
    from app.db import Base
    from app.security import aead, crypto, labels
    from app.security.hashing import canonical

    eng = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    Base.metadata.create_all(eng)
    dek = aead.new_key()
    wrapped, version = crypto.wrap_dek(dek, 1)
    n, ct = crypto.encrypt_reading(dek, {"hr": 130, "spo2": 85}, patient_id=1, device_id="d1", seq=5, ts=1000)
    rollup = aead.seal_blob(dek, json.dumps({"n": 1, "sum": {"hr": 130}, "min": {}, "max": {}, "count": {"hr": 1}})
                            .encode(), canonical("rollup", 1, 900))
    with eng.begin() as conn:   # an old database: labels in clear columns
        conn.execute(text("DROP INDEX uq_alert_open_tag"))
        conn.execute(text("CREATE UNIQUE INDEX uq_alert_open ON alerts (patient_id, reason_code) WHERE status = 'open'"))
        conn.execute(text("INSERT INTO patients (id, user_id, wrapped_dek, key_version, consent_active, "
                          "consent_changed_at, last_band, last_score) "
                          "VALUES (1, 1, :w, :v, 1, '2026-01-01', 'critical', 0.9)"), {"w": wrapped, "v": version})
        conn.execute(text("INSERT INTO readings (patient_id, device_id, seq, ts, nonce, ciphertext, band, risk_score, "
                          "reason_codes) VALUES (1,'d1',5,1000,:n,:c,'critical',0.9,'SPO2_LOW,HR_HIGH')"),
                     {"n": n, "c": ct})
        conn.execute(text("INSERT INTO reading_rollups (patient_id, bucket_ts, blob, worst_band) "
                          "VALUES (1, 900, :b, 'critical')"), {"b": rollup})
        conn.execute(text("INSERT INTO alerts (patient_id, reason_code, severity, status, occurrences, first_seen, "
                          "last_seen) VALUES (1, 'SPO2_LOW', 'critical', 'open', 1, '2026-01-01', '2026-01-01')"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0004_partial_readings')"))

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")

    with eng.connect() as conn:
        r = conn.execute(text("SELECT nonce, ciphertext, band, risk_score, reason_codes FROM readings")).one()
        assert r[2:] == (None, None, None)
        payload = json.loads(aead.decrypt(dek, r[0], r[1], crypto.reading_aad(1, "d1", 5, 1000)))
        assert payload == {"hr": 130, "spo2": 85, "band": "critical", "risk": 0.9, "reasons": ["SPO2_LOW", "HR_HIGH"]}
        blob, worst = conn.execute(text("SELECT blob, worst_band FROM reading_rollups")).one()
        assert worst is None and json.loads(aead.open_blob(dek, blob, canonical("rollup", 1, 900)))["band"] == "critical"
        status, band, score = conn.execute(text("SELECT last_status_enc, last_band, last_score FROM patients")).one()
        assert (band, score) == (None, None)
        assert crypto.decrypt_json(dek, status, patient_id=1, field="last_status") == {"band": "critical", "risk": 0.9}
        tag, details, code, sev = conn.execute(text("SELECT reason_tag, details_enc, reason_code, severity FROM alerts")).one()
        assert (code, sev) == (None, None) and tag == labels.alert_tag(dek, 1, "SPO2_LOW")
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(alerts)"))}
        assert "uq_alert_open_tag" in indexes and "uq_alert_open" not in indexes


def test_demo_helpers_answer_only_local_callers():
    from types import SimpleNamespace

    from app.api.auth_routes import is_local

    for host, ok in (("127.0.0.1", True), ("::1", True), ("192.168.1.20", False), ("10.0.0.5", False)):
        assert is_local(SimpleNamespace(client=SimpleNamespace(host=host))) is ok
    assert is_local(SimpleNamespace(client=None)) is False


def test_app_page_is_revalidated_after_updates(world):
    from app.main import FRONTEND_DIST

    if not (FRONTEND_DIST / "index.html").exists():
        import pytest
        pytest.skip("web app not built")
    r = TestClient(world["app"], base_url="https://testserver").get("/login")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
