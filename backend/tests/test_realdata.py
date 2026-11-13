"""eICU loader and device-client input tests. Uses a tiny hand-made fixture, never the real PhysioNet files."""
import csv
import gzip
import importlib.util
import sys
from pathlib import Path


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with gzip.open(path, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _fixture(tmp: Path) -> Path:
    d = tmp / "eicu"
    d.mkdir()
    _write(d / "hospital.csv.gz", ["hospitalid", "numbedscategory", "teachingstatus", "region"],
           [[7, "100 - 249", "t", "South"]])
    pat_header = ["patientunitstayid", "hospitalid", "unittype", "age", "hospitaldischargestatus",
                  "unitdischargestatus", "unitdischargeoffset"]
    _write(d / "patient.csv.gz", pat_header, [[1001, 7, "MICU", "70", "Expired", "Expired", 400],
                                              [1002, 7, "SICU", "55", "Alive", "Alive", 60]])
    vp_header = ["vitalperiodicid", "patientunitstayid", "observationoffset", "temperature", "sao2", "heartrate",
                 "respiration", "cvp", "etco2", "systemicsystolic", "systemicdiastolic", "systemicmean"]
    rows = []
    for i in range(16):  # stay 1001: 5-minute rows from 0 to 75 minutes
        temp = "37.8" if i == 2 else ""
        rows.append([i, 1001, i * 5, temp, 95, 90 + i, 18, "", "", "", "", ""])
    rows.append([99, 1001, 300, "", 94, 100, 20, "", "", "", "", ""])          # cuff BP too old (>4 h) -> dropped
    rows.append([100, 1001, 305, "", 94, 101, 20, "", "", 130, 70, 90])       # arterial line present -> kept
    rows.append([101, 1001, 310, "", "", 101, 20, "", "", "", "", ""])        # no SpO2 -> dropped
    for i in range(5):  # stay 1002: too short (5 rows < 12)
        rows.append([200 + i, 1002, i * 5, "", 98, 70, 14, "", "", 120, 80, 93])
    _write(d / "vitalPeriodic.csv.gz", vp_header, rows)
    _write(d / "vitalAperiodic.csv.gz",
           ["vitalaperiodicid", "patientunitstayid", "observationoffset", "noninvasivesystolic", "noninvasivediastolic",
            "noninvasivemean"],
           [[1, 1001, 0, 140, 85, 103]])
    return d


def test_eicu_loader_builds_5_minute_rows(tmp_path, monkeypatch):
    from app.ml import realdata

    d = _fixture(tmp_path)
    monkeypatch.setattr(realdata, "EICU_DIR", d)
    monkeypatch.setattr(realdata, "EICU_META", tmp_path / "meta.json")
    monkeypatch.setattr(realdata, "EICU_ROWS", tmp_path / "rows.json.gz")
    realdata._eicu_rows_cached.cache_clear()

    assert realdata.eicu_available()
    meta, rows = realdata.build_eicu_cache()
    assert set(meta) == {"1001"}                       # 1002 is too short
    m = meta["1001"]
    assert m["died_in_hospital"] is True and m["hospital_region"] == "South" and m["hospital_teaching"] is True
    r = realdata.eicu_rows_as_dicts(rows["1001"])
    assert len(r) == 17                                  # 16 + the arterial-line row; stale-cuff and no-SpO2 rows dropped
    assert r[0]["sbp"] == 140 and r[0]["dbp"] == 85       # cuff BP carried forward
    assert r[-1]["sbp"] == 130 and r[-1]["t_min"] == 305  # arterial line preferred
    assert r[0]["temp"] == 36.9 and r[0]["temp_measured"] == 0   # before any temperature: fixed and flagged
    assert r[2]["temp"] == 37.8 and r[5]["temp"] == 37.8 and r[5]["temp_measured"] == 1  # carried forward
    assert m["temp_measured"] is True

    stream = realdata.stream_for_source("eicu:1001")
    vitals, label, kind = stream.step()
    assert vitals == {"hr": 90.0, "spo2": 95.0, "sbp": 140.0, "dbp": 85.0, "temp": 36.9, "rr": 18.0}
    assert kind == "eicu:1001"
    assert realdata.stream_for_source("eicu:9999") is None
    realdata._eicu_rows_cached.cache_clear()


def _device_client():
    path = Path(__file__).resolve().parents[2] / "scripts" / "device_client.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("device_client_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # the CLI only runs under __main__
    return mod


def test_device_client_reads_sensor_json_lines(env):
    dc = _device_client()
    ok = dc.parse_vitals_line('{"hr": 78, "spo2": 97, "sbp": 122, "dbp": 79, "temp": 36.8, "rr": 15}')
    assert ok == {"hr": 78.0, "spo2": 97.0, "sbp": 122.0, "dbp": 79.0, "temp": 36.8, "rr": 15.0}
    assert dc.parse_vitals_line('{"hr": 78}') is None          # missing values
    assert dc.parse_vitals_line("not json") is None
    assert dc.parse_vitals_line("# comment") is None
    assert dc.verify_arg("https://vitalcare.example.org", None) is True       # real hospital: system CAs
    assert dc.verify_arg("https://x.example.org", "/etc/ca.pem") == "/etc/ca.pem"


def test_device_client_reads_pairing_link(env):
    import pytest

    dc = _device_client()
    server, pid, code = dc.parse_pairing_link(
        "vitalcare-pair:v1?server=https%3A%2F%2Fvitalcare.example.org&id=7f3c0a1b2c3d4e5f&code=K7QM-2WXR-9HPD")
    assert (server, pid, code) == ("https://vitalcare.example.org", "7f3c0a1b2c3d4e5f", "K7QM-2WXR-9HPD")
    local = dc.parse_pairing_link("vitalcare-pair:v1?server=http%3A%2F%2Flocalhost%3A8000&id=ab12&code=AAAA-BBBB-CCCC")
    assert local[0] == "http://localhost:8000"
    for bad in (
        "https://evil.example.org/pair?id=1&code=2",                                          # not our scheme
        "vitalcare-pair:v1?server=http%3A%2F%2Fvitalcare.example.org&id=ab12&code=AAAA-BBBB-CCCC",  # plain http remote
        "vitalcare-pair:v1?server=https%3A%2F%2Fx.org%2Fphish&id=ab12&code=AAAA-BBBB-CCCC",   # path in server
        "vitalcare-pair:v1?server=https%3A%2F%2Fx.org&code=AAAA-BBBB-CCCC",                   # missing id
        "vitalcare-pair:v1?server=https%3A%2F%2Fx.org&id=..%2F..&code=AAAA",                  # bad id
    ):
        with pytest.raises(ValueError):
            dc.parse_pairing_link(bad)
