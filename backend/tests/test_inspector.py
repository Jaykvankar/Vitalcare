"""Security inspector: evidence is shown without vitals, and demonstrated attacks are blocked."""
import json
import time

from fastapi.testclient import TestClient


def send(world, vitals):
    from app.security import server_keys
    from app.simulator import build_packet
    from tests.conftest import next_seq

    pkt = build_packet(world["dev_id"], world["dev_key"], server_keys.load_or_create().dh_public_raw, vitals,
                       ts=int(time.time()), seq=next_seq(world["dev_id"]))
    return TestClient(world["app"], base_url="https://testserver").post("/api/ingest", json=pkt)


def test_inspector_shows_crypto_steps_but_never_vitals(world, client_for):
    vitals = {"hr": 77.7, "spo2": 96.6, "sbp": 131.3, "dbp": 81.1, "temp": 36.66, "rr": 15.5}
    assert send(world, vitals).status_code == 200
    data = client_for("admin").get("/api/security/inspector").json()
    dev = next(d for d in data["devices"] if d["id"] == world["dev_id"])
    steps = {s["id"]: s for s in dev["packets"][0]["steps"]}
    assert list(steps) == ["dh", "kdf", "aead", "digest", "sig", "replay", "store", "ai"]
    assert "3072 bits" in steps["dh"]["values"]["Device public value E = gᵉ mod p"]
    assert steps["sig"]["family"].startswith("RSA") and steps["sig"]["ok"] is True
    assert data["ledger"]["rows"] > 0
    text = json.dumps(data)
    for value in ("77.7", "96.6", "131.3", "81.1", "36.66", "15.5"):
        assert value not in text                     # no vital sign ever appears in the inspector
    assert "BEGIN" not in text and "PRIVATE" not in text   # no key material (PEM) either
    for label in ('"normal"', '"warning"', '"critical"', "SPO2_LOW", "HR_HIGH"):
        assert label not in text                     # nor the clinical result (band, reasons)


def test_clinician_sees_only_assigned_devices_and_cannot_attack(world, client_for):
    c2 = client_for("clin2").get("/api/security/inspector").json()
    assert world["dev_id"] not in {d["id"] for d in c2["devices"]} and c2["can_attack"] is False
    c1 = client_for("clin1").get("/api/security/inspector").json()
    assert world["dev_id"] in {d["id"] for d in c1["devices"]}
    r = client_for("clin1").post("/api/security/attack", json={"device_id": world["dev_id"], "kind": "replay"})
    assert r.status_code == 403
    assert client_for("pat1").get("/api/security/inspector").status_code == 403


def test_attacks_are_blocked_by_the_real_checks(world, client_for):
    assert send(world, {"hr": 80, "spo2": 97}).status_code == 200
    admin = client_for("admin")
    expected = {"replay": (409, "replayed"), "tamper": (401, "bad signature"), "forge": (401, "bad signature")}
    for kind, (status, words) in expected.items():
        r = admin.post("/api/security/attack", json={"device_id": world["dev_id"], "kind": kind})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["blocked"] is True and body["status"] == status and words in body["message"], (kind, body)
    # the genuine device keeps working afterwards
    assert send(world, {"hr": 81, "spo2": 97}).status_code == 200
    assert admin.post("/api/security/attack", json={"device_id": "dev-none", "kind": "replay"}).status_code == 404
