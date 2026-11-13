"""Partial readings: real sensors measure only some vitals."""
import time

import pytest
from fastapi.testclient import TestClient


def send(world, vitals):
    from app.security import server_keys
    from app.simulator import build_packet
    from tests.conftest import next_seq

    pkt = build_packet(world["dev_id"], world["dev_key"], server_keys.load_or_create().dh_public_raw, vitals,
                       ts=int(time.time()), seq=next_seq(world["dev_id"]))
    return TestClient(world["app"], base_url="https://testserver").post("/api/ingest", json=pkt)


def test_validate_accepts_subsets_and_rejects_bad_input():
    from app.ml.rules import validate

    assert validate({"hr": 80}) == {"hr": 80.0}
    assert validate({"spo2": 97, "hr": 70, "temp": ""}) == {"spo2": 97.0, "hr": 70.0}   # empty CSV cell = missing
    for bad in ({}, {"sbp": 120}, {"hr": 80, "mood": 3}, {"hr": 999}, {"sbp": 80, "dbp": 90}, {"hr": float("nan")}):
        with pytest.raises(ValueError):
            validate(bad)


def test_rules_and_news2_use_what_was_measured():
    from app.ml.rules import evaluate_rules, news2, news2_inputs_present

    v = {"spo2": 86, "hr": 125}
    assert dict(evaluate_rules(v)) == {"SPO2_LOW": "critical", "HR_HIGH": "critical"}
    assert news2(v) == 3 + 2 and news2_inputs_present(v) == 2
    full = {"hr": 125, "spo2": 86, "sbp": 118, "dbp": 74, "temp": 37.0, "rr": 26}
    assert news2(full) == 2 + 3 + 0 + 3 + 0 and news2_inputs_present(full) == 5


def test_features_skip_partial_and_resume_on_full():
    from app.ml.features import features_and_update, new_state

    f, s = features_and_update({"hr": 80, "spo2": 97}, new_state())
    assert f is None and s["mean"] == {"hr": 80, "spo2": 97}
    f, s = features_and_update({"hr": 90, "spo2": 95, "sbp": 120, "dbp": 80, "temp": 36.8, "rr": 15}, s)
    assert f is not None and len(f) == 18
    assert f[6] == 10 and f[7] == -2          # deltas use the earlier partial values for hr and spo2


def test_partial_reading_is_stored_scored_by_rules_and_shown(world, client_for):
    r = send(world, {"spo2": 85, "hr": 124})
    assert r.status_code == 200, r.text
    assert r.json()["band"] == "critical" and "SPO2_LOW" in r.json()["reasons"]
    assert "ML_RISK" not in r.json()["reasons"]          # the model does not score partial readings

    c = client_for("clin1")
    latest = c.get(f"/api/patients/{world['ids']['p1']}/readings?range=6h").json()["latest"]
    assert latest["spo2"] == 85 and latest["hr"] == 124
    assert "sbp" not in latest and "temp" not in latest and latest["risk"] is None
    assert latest["news2_inputs"] == 2
    long = c.get(f"/api/patients/{world['ids']['p1']}/readings?range=24h")      # encrypted rollups still work
    assert long.status_code == 200 and long.json()["count"] >= 1

    full = send(world, {"hr": 78, "spo2": 97, "sbp": 121, "dbp": 77, "temp": 36.8, "rr": 15})
    assert full.status_code == 200
    latest = c.get(f"/api/patients/{world['ids']['p1']}/readings?range=6h").json()["latest"]
    assert latest["risk"] is not None and latest["news2_inputs"] == 5


def test_invalid_partial_readings_are_rejected(world):
    assert send(world, {"sbp": 120}).status_code == 422
    assert send(world, {"hr": 80, "colour": 1}).status_code == 422
