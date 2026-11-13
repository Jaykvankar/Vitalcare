"""Device catalog, device types through pairing, and migration 0002."""
from fastapi.testclient import TestClient


def test_catalog_lists_device_types_by_role(world, client_for):
    clin = client_for("clin1").get("/api/devices/catalog")
    assert clin.status_code == 200
    ids = {d["id"] for d in clin.json()}
    assert {"gateway_kit", "pulse_oximeter", "bp_cuff", "thermometer", "hr_strap", "ward_monitor"} <= ids
    assert "simulator" not in ids                    # admin-only test device
    admin_ids = {d["id"] for d in client_for("admin").get("/api/devices/catalog").json()}
    assert "simulator" in admin_ids
    entry = next(d for d in clin.json() if d["id"] == "pulse_oximeter")
    assert entry["status"] == "needs_adapter" and entry["how_to_connect"] and entry["patient_tips"]
    assert client_for("pat1").get("/api/devices/catalog").status_code == 200   # patients can read it too


def test_device_type_flows_from_code_to_device(world, client_for):
    from app.security import signatures
    from app.security.hashing import b64e
    from app.security.pairing import proof

    c = client_for("clin1")
    pid = world["ids"]["p1"]
    bad = c.post("/api/devices/pairing-codes", json={"patient_id": pid, "device_type": "toaster"})
    assert bad.status_code == 422
    sim = c.post("/api/devices/pairing-codes", json={"patient_id": pid, "device_type": "simulator"})
    assert sim.status_code == 422                     # clinicians cannot pick the admin-only test device

    r = c.post("/api/devices/pairing-codes", json={"patient_id": pid, "label": "Ward oximeter",
                                                   "device_type": "pulse_oximeter"})
    assert r.status_code == 200
    pairing_id, code = r.json()["pairing_id"], r.json()["code"]
    pub = signatures.public_pem(signatures.rsa_generate())
    dev = TestClient(world["app"], base_url="https://testserver")
    ok = dev.post("/api/devices/pair", json={"pairing_id": pairing_id, "public_key_pem": pub,
                                             "proof": b64e(proof(code, pairing_id, pub))})
    assert ok.status_code == 200
    device_id = ok.json()["device_id"]

    rows = c.get(f"/api/devices?patient_id={pid}").json()
    d = next(x for x in rows if x["id"] == device_id)
    assert d["device_type"] == "pulse_oximeter" and d["kind"] == "device" and d["label"] == "Ward oximeter"
    profile = client_for("pat1").get(f"/api/patients/{pid}").json()
    assert any(x["id"] == device_id and x["device_type"] == "pulse_oximeter" for x in profile["devices"])


def test_migration_0002_adds_columns_to_an_older_database(tmp_path):
    """A database at revision 0001 without the columns is upgraded in place."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    from app import models  # noqa: F401
    from app.config import BACKEND_DIR
    from app.db import Base

    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    with eng.begin() as conn:  # make it look like a database created before this change
        conn.execute(text("ALTER TABLE devices DROP COLUMN device_type"))
        conn.execute(text("ALTER TABLE pairing_codes DROP COLUMN device_type"))
        # readings.risk_score was NOT NULL before 0004
        conn.execute(text("DROP TABLE readings"))
        conn.execute(text("CREATE TABLE readings (id INTEGER PRIMARY KEY, patient_id INTEGER, device_id VARCHAR(64), "
                          "seq BIGINT, ts BIGINT, nonce BLOB, ciphertext BLOB, band VARCHAR(16), "
                          "risk_score FLOAT NOT NULL, reason_codes VARCHAR(256))"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0001_baseline')"))
    assert "device_type" not in {c["name"] for c in inspect(eng).get_columns("devices")}

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    insp = inspect(eng)
    for table in ("devices", "pairing_codes"):
        assert "device_type" in {c["name"] for c in insp.get_columns(table)}
    with eng.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004_partial_readings"
    assert "demo_account" in {c["name"] for c in insp.get_columns("users")}
    risk = next(c for c in insp.get_columns("readings") if c["name"] == "risk_score")
    assert risk["nullable"] is True
