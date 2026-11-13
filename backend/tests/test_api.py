import time

from fastapi.testclient import TestClient

HYPOXIA = {"hr": 118, "spo2": 85, "sbp": 116, "dbp": 72, "temp": 37.1, "rr": 28}
NORMAL = {"hr": 74, "spo2": 98, "sbp": 121, "dbp": 77, "temp": 36.8, "rr": 15}
_seq = [int(time.time() * 1000)]


def packet(world, vitals, *, key=None, device_id=None, seq=None, ts=None):
    from app.security import server_keys
    from app.simulator import build_packet

    _seq[0] += 1
    return build_packet(device_id or world["dev_id"], key or world["dev_key"],
                        server_keys.load_or_create().dh_public_raw, vitals,
                        ts=ts or int(time.time()), seq=seq or _seq[0])


def device_client(world):
    return TestClient(world["app"], base_url="https://testserver")


def test_ingest_accepts_valid_packet(world):
    r = device_client(world).post("/api/ingest", json=packet(world, NORMAL))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"]


def test_ingest_rejects_bad_signature(world):
    from app.security import signatures

    pkt = packet(world, NORMAL, key=signatures.rsa_generate())   # signed by a different key
    assert device_client(world).post("/api/ingest", json=pkt).status_code == 401


def test_ingest_rejects_modified_ciphertext(world):
    import base64

    pkt = packet(world, NORMAL)
    ct = bytearray(base64.b64decode(pkt["ct"]))
    ct[0] ^= 1
    pkt["ct"] = base64.b64encode(bytes(ct)).decode()
    assert device_client(world).post("/api/ingest", json=pkt).status_code == 401


def test_ingest_rejects_replay_and_stale(world):
    c = device_client(world)
    pkt = packet(world, NORMAL)
    assert c.post("/api/ingest", json=pkt).status_code == 200
    assert c.post("/api/ingest", json=pkt).status_code == 409                     # exact replay
    old = packet(world, NORMAL, ts=int(time.time()) - 3600)
    assert c.post("/api/ingest", json=old).status_code == 400                     # outside time window


def test_hypoxia_raises_critical_alert(world, client_for):
    r = device_client(world).post("/api/ingest", json=packet(world, HYPOXIA))
    assert r.status_code == 200 and r.json()["band"] == "critical"
    c = client_for("clin1")
    alerts = c.get(f"/api/patients/{world['ids']['p1']}/alerts?status=open").json()
    spo2 = [a for a in alerts if a["reason_code"] == "SPO2_LOW"]
    assert spo2 and spo2[0]["severity"] == "critical"
    assert c.post(f"/api/alerts/{spo2[0]['id']}/ack", json={"note": "Called patient"}).status_code == 200
    after = c.get(f"/api/patients/{world['ids']['p1']}/alerts").json()
    acked = next(a for a in after if a["id"] == spo2[0]["id"])
    assert acked["status"] == "acknowledged" and acked["note"] == "Called patient"


def test_readings_are_ciphertext_at_rest(world):
    from app.db import SessionLocal
    from app.models import Reading

    db = SessionLocal()
    r = db.query(Reading).first()
    db.close()
    assert b"spo2" not in r.ciphertext and b"hr" not in r.ciphertext


def test_clinician_can_read_assigned_patient(world, client_for):
    c = client_for("clin1")
    r = c.get(f"/api/patients/{world['ids']['p1']}/readings?range=6h")
    assert r.status_code == 200 and r.json()["count"] >= 1
    assert "spo2" in r.json()["latest"]
    worklist = c.get("/api/patients").json()
    assert [p["id"] for p in worklist] == [world["ids"]["p1"]]


def test_clinician_blocked_from_unassigned_patient(world, client_for):
    c = client_for("clin2")
    assert c.get(f"/api/patients/{world['ids']['p1']}/readings").status_code == 404
    assert c.get(f"/api/patients/{world['ids']['p1']}").status_code == 404


def test_patient_sees_only_own_record(world, client_for):
    c = client_for("pat1")
    assert c.get(f"/api/patients/{world['ids']['p1']}").json()["dob"] == "1960-01-01"
    assert c.get(f"/api/patients/{world['ids']['p2']}/readings").status_code == 404


def test_admin_cannot_decrypt_vitals(world, client_for):
    c = client_for("admin")
    assert c.get(f"/api/patients/{world['ids']['p1']}/readings").status_code == 403
    assert c.get("/api/admin/users").status_code == 200


def test_consent_revocation_blocks_ingest_and_clinician(world, client_for):
    p = client_for("pat1")
    assert p.put("/api/me/consent", json={"active": False}).json()["consent_active"] is False
    try:
        assert device_client(world).post("/api/ingest", json=packet(world, NORMAL)).status_code == 403
        assert client_for("clin1").get(f"/api/patients/{world['ids']['p1']}/readings").status_code == 403
        assert p.get(f"/api/patients/{world['ids']['p1']}/readings").status_code == 200  # own data still visible
    finally:
        p.put("/api/me/consent", json={"active": True})


def test_mfa_required_for_clinician(world):
    c = TestClient(world["app"], base_url="https://testserver")
    c.headers["X-RPM-Request"] = "1"
    r = c.post("/api/auth/login", json={"username": "clin2", "password": world["pw"]})
    assert r.json()["mfa"] == "verify"
    assert c.get("/api/auth/me").status_code == 401            # password alone is not enough
    assert c.post("/api/auth/mfa", json={"code": "000000"}).status_code == 401


def test_lockout_after_repeated_failures(world):
    from app.security import auth

    auth.login_limiter.hits.clear()
    c = TestClient(world["app"], base_url="https://testserver")
    c.headers["X-RPM-Request"] = "1"
    for _ in range(5):
        assert c.post("/api/auth/login", json={"username": "pat2", "password": "wrong-password"}).status_code == 401
    r = c.post("/api/auth/login", json={"username": "pat2", "password": world["pw"]})
    assert r.status_code == 423
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    u = db.query(User).filter_by(username="pat2").one()
    u.locked_until = None
    db.commit()
    db.close()
    auth.login_limiter.hits.clear()


def test_csrf_header_and_origin_required(world):
    c = TestClient(world["app"], base_url="https://testserver")
    r = c.post("/api/auth/login", json={"username": "pat1", "password": world["pw"]})
    assert r.status_code == 403
    r = c.post("/api/auth/login", json={"username": "pat1", "password": world["pw"]},
               headers={"X-RPM-Request": "1", "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_device_pairing_flow(world, client_for):
    from app.security.hashing import b64e
    from app.security.pairing import proof
    from app.security import signatures

    dev = TestClient(world["app"], base_url="https://testserver")
    # unassigned clinician cannot issue a code; assigned clinician can
    assert client_for("clin2").post("/api/devices/pairing-codes", json={"patient_id": world["ids"]["p1"]}).status_code == 404
    c = client_for("clin1")
    r = c.post("/api/devices/pairing-codes", json={"patient_id": world["ids"]["p1"], "label": "Ward watch"})
    assert r.status_code == 200
    pid, code = r.json()["pairing_id"], r.json()["code"]

    key = signatures.rsa_generate()
    pub = signatures.public_pem(key)
    wrong = {"pairing_id": pid, "public_key_pem": pub, "proof": b64e(proof("AAAA-AAAA-AAAA", pid, pub))}
    assert dev.post("/api/devices/pair", json=wrong).status_code == 401
    good = {"pairing_id": pid, "public_key_pem": pub, "proof": b64e(proof(code, pid, pub))}
    r = dev.post("/api/devices/pair", json=good)
    assert r.status_code == 200, r.text
    device_id = r.json()["device_id"]
    assert dev.post("/api/devices/pair", json=good).status_code == 409          # one-time code

    # the paired device can now send readings
    assert dev.post("/api/ingest", json=packet(world, NORMAL, key=key, device_id=device_id)).status_code == 200
    assert c.get(f"/api/patients/{world['ids']['p1']}/alerts").status_code == 200
    # revoke -> readings rejected
    assert c.post(f"/api/devices/{device_id}/revoke").status_code == 200
    assert dev.post("/api/ingest", json=packet(world, NORMAL, key=key, device_id=device_id)).status_code == 401


def test_pairing_code_burns_after_five_wrong_proofs(world, client_for):
    from app.security.hashing import b64e
    from app.security.pairing import proof
    from app.security import signatures

    dev = TestClient(world["app"], base_url="https://testserver")
    r = client_for("admin").post("/api/devices/pairing-codes", json={"patient_id": world["ids"]["p2"]})
    pid, code = r.json()["pairing_id"], r.json()["code"]
    pub = signatures.public_pem(signatures.rsa_generate())
    for _ in range(5):
        dev.post("/api/devices/pair", json={"pairing_id": pid, "public_key_pem": pub, "proof": b64e(b"x" * 64)})
    good = {"pairing_id": pid, "public_key_pem": pub, "proof": b64e(proof(code, pid, pub))}
    assert dev.post("/api/devices/pair", json=good).status_code == 429


def test_audit_chain_detects_tampering(world, client_for):
    from sqlalchemy import text

    from app.db import engine
    from app.security import audit
    from app.security.audit import row_hash

    client_for("pat1")
    audit.checkpoint_now()
    assert audit.verify()["ok"]

    with engine().begin() as conn:
        # The DB itself refuses edits ...
        try:
            conn.execute(text("UPDATE audit_log SET detail='x' WHERE id=1"))
            raise AssertionError("update should have been blocked")
        except Exception as exc:  # noqa: BLE001
            assert "append-only" in str(exc)
    with engine().begin() as conn:
        # ... so an attacker with full DB access drops the trigger and edits a row.
        conn.execute(text("DROP TRIGGER audit_no_update"))
        conn.execute(text("UPDATE audit_log SET detail='tampered' WHERE id=1"))
    result = audit.verify()
    assert not result["ok"] and any("row 1" in p for p in result["problems"])

    # Attacker recomputes the whole chain so every hash matches again ...
    with engine().begin() as conn:
        rows = conn.execute(text("SELECT id, ts, actor_id, actor, action, target, detail FROM audit_log ORDER BY id")).all()
        prev = audit.GENESIS
        for r in rows:
            h = row_hash(prev, r.ts, r.actor_id, r.actor, r.action, r.target, r.detail)
            conn.execute(text("UPDATE audit_log SET prev_hash=:p, hash=:h WHERE id=:i"), {"p": prev, "h": h, "i": r.id})
            prev = h
    # ... but cannot forge the ECDSA-signed checkpoint.
    result = audit.verify()
    assert not result["ok"] and any("checkpoint" in p for p in result["problems"])
