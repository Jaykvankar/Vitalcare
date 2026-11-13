"""Loaders for the open-access real datasets in data/real/ (downloaded from PhysioNet, git-ignored).

MIMIC-III Clinical Database Demo v1.4 (ODbL): 100 de-identified ICU patients.
    Charted vitals are aggregated to hourly medians per ICU stay, forward-filled up to 4 h.
    Gives all six vitals plus the in-hospital outcome.
BIDMC PPG and Respiration Dataset v1.0.0 (ODC-BY): 53 ICU recordings, 8 min each, 1 Hz.
    Has HR, SpO2 and RR only. Blood pressure and temperature were not recorded: replay leaves them
    out (shown as not measured); the evaluation holds them at fixed normal values.

eICU Collaborative Research Database Demo v2.0.1 (ODbL): 2,520 ICU stays from 186 US hospitals.
    5-minute vital signs (vitalPeriodic) plus cuff blood pressure (vitalAperiodic); hospital outcome
    and hospital characteristics. Temperature is rarely charted in these tables (167 stays); when it
    is missing, live replay leaves it out and the evaluation holds it at a fixed normal value.

Dates in MIMIC are shifted for de-identification; only relative times are used.
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .rules import PLAUSIBLE, VITALS

PROJECT_DIR = Path(__file__).resolve().parents[3]
REAL_DIR = PROJECT_DIR / "data" / "real"
MIMIC_DIR = REAL_DIR / "mimic"
BIDMC_DIR = REAL_DIR / "bidmc"
MIMIC_CACHE = REAL_DIR / "mimic_hourly.json"

# MIMIC-III item ids (CareVue + MetaVision)
ITEMS = {
    "hr": {211, 220045},
    "spo2": {646, 220277},
    "rr": {618, 615, 220210, 224690},
    "sbp": {51, 455, 6701, 220179, 220050},
    "dbp": {8368, 8441, 8555, 220180, 220051},
    "temp_c": {676, 223762},
    "temp_f": {678, 223761},
}
ITEM_TO_VITAL = {i: k for k, ids in ITEMS.items() for i in ids}
FFILL_HOURS = 4
BIDMC_FIXED = {"sbp": 120.0, "dbp": 78.0, "temp": 36.9}


def available() -> dict:
    return {"mimic": (MIMIC_DIR / "CHARTEVENTS.csv").exists(),
            "bidmc": BIDMC_DIR.exists() and any(BIDMC_DIR.glob("*.csv")),
            "eicu": eicu_available()}


def _ts(s: str) -> datetime:
    return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def _plausible(k: str, v: float) -> bool:
    lo, hi = PLAUSIBLE[k]
    return lo <= v <= hi


def build_mimic_cache() -> dict:
    """Parse CHARTEVENTS once (about 78 MB) into hourly vital series per ICU stay."""
    stays: dict[str, dict] = {}
    with open(MIMIC_DIR / "ICUSTAYS.csv", newline="") as f:
        for r in csv.DictReader(f):
            stays[r["icustay_id"]] = {"subject_id": r["subject_id"], "hadm_id": r["hadm_id"],
                                      "intime": r["intime"], "outtime": r["outtime"]}
    died: dict[str, tuple[bool, str]] = {}
    with open(MIMIC_DIR / "ADMISSIONS.csv", newline="") as f:
        for r in csv.DictReader(f):
            died[r["hadm_id"]] = (r["hospital_expire_flag"] == "1", r["deathtime"])

    buckets: dict[str, dict[int, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    with open(MIMIC_DIR / "CHARTEVENTS.csv", newline="") as f:
        for r in csv.DictReader(f):
            vital = ITEM_TO_VITAL.get(int(r["itemid"]))
            stay = r["icustay_id"]
            if vital is None or not stay or stay not in stays or not r["valuenum"] or r.get("error") == "1":
                continue
            v = float(r["valuenum"])
            if vital == "temp_f":
                vital, v = "temp", (v - 32) * 5 / 9
            elif vital == "temp_c":
                vital = "temp"
            if not _plausible(vital, v):
                continue
            hour = int((_ts(r["charttime"]) - _ts(stays[stay]["intime"])).total_seconds() // 3600)
            if hour < 0:
                continue
            buckets[stay][hour][vital].append(v)

    out = {}
    for stay, hours in buckets.items():
        info = stays[stay]
        dead, deathtime = died.get(info["hadm_id"], (False, ""))
        last: dict[str, tuple[int, float]] = {}
        rows = []
        for h in range(0, max(hours) + 1):
            for k, vals in hours.get(h, {}).items():
                last[k] = (h, statistics.median(vals))
            current = {k: v for k, (t, v) in last.items() if h - t <= FFILL_HOURS}
            if all(k in current for k in VITALS) and current["dbp"] < current["sbp"]:
                rows.append({"t_h": h, **{k: round(current[k], 2) for k in VITALS}})
        if len(rows) < 6:
            continue
        stay_hours = (_ts(info["outtime"]) - _ts(info["intime"])).total_seconds() / 3600 if info["outtime"] else rows[-1]["t_h"]
        death_h = (_ts(deathtime) - _ts(info["intime"])).total_seconds() / 3600 if dead and deathtime else None
        out[stay] = {"subject_id": info["subject_id"], "died_in_hospital": dead, "death_hour": death_h,
                     "stay_hours": round(stay_hours, 1), "rows": rows}
    MIMIC_CACHE.write_text(json.dumps(out))
    return out


def load_mimic() -> dict:
    if MIMIC_CACHE.exists() and MIMIC_CACHE.stat().st_mtime >= (MIMIC_DIR / "CHARTEVENTS.csv").stat().st_mtime:
        return json.loads(MIMIC_CACHE.read_text())
    return build_mimic_cache()


def load_bidmc(n: int, step_s: int = 5, fill_missing: bool = True) -> list[dict]:
    """One BIDMC record as `step_s`-second medians.

    BP and temperature were not recorded. fill_missing=True (evaluation) holds them at fixed normal
    values; fill_missing=False (live replay) leaves them out, so the app shows them as not measured.
    """
    path = BIDMC_DIR / f"bidmc_{n:02d}_Numerics.csv"
    rows: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        idx = {name: header.index(name) for name in ("Time [s]", "HR", "RESP", "SpO2")}
        for r in reader:
            try:
                t = int(float(r[idx["Time [s]"]]))
                for src, dst in (("HR", "hr"), ("RESP", "rr"), ("SpO2", "spo2")):
                    v = float(r[idx[src]])
                    if v == v and _plausible(dst, v):  # skip NaN
                        rows[t // step_s][dst].append(v)
            except (ValueError, IndexError):
                continue
    out = []
    for b in sorted(rows):
        vals = rows[b]
        if all(k in vals for k in ("hr", "rr", "spo2")):
            out.append({"t_s": b * step_s, **{k: round(statistics.median(v), 1) for k, v in vals.items()},
                        **(BIDMC_FIXED if fill_missing else {})})
    return out


def bidmc_records() -> list[int]:
    return sorted(int(p.name.split("_")[1]) for p in BIDMC_DIR.glob("bidmc_*_Numerics.csv"))


# ---------------------------------------------------------------- eICU Collaborative Research Database demo

EICU_DIR = REAL_DIR / "eicu"
EICU_META = REAL_DIR / "eicu_meta.json"
EICU_ROWS = REAL_DIR / "eicu_5min.json.gz"
EICU_BP_FFILL_MIN = 240     # cuff blood pressure is measured every 1-4 h: carry it forward up to 4 h
EICU_TEMP_FFILL_MIN = 720   # temperature carried forward up to 12 h when it was measured at all
EICU_TEMP_FIXED = 36.9      # used only when no temperature was recorded (flagged per row)
EICU_MIN_ROWS = 12          # at least one hour of 5-minute data


def eicu_available() -> bool:
    return all((EICU_DIR / f"{n}.csv.gz").exists() for n in ("patient", "hospital", "vitalPeriodic", "vitalAperiodic"))


def _f(value: str) -> float | None:
    try:
        v = float(value)
    except ValueError:
        return None
    return v if v == v else None  # drop NaN


def _ok(k: str, v: float | None) -> bool:
    return v is not None and _plausible(k, v)


def build_eicu_cache() -> tuple[dict, dict]:
    """Turn the eICU demo tables into 5-minute vital-sign rows per ICU stay.

    Heart rate, SpO2 and respiration come from vitalPeriodic (5-minute medians). Blood pressure is the
    arterial line when present, otherwise the most recent cuff reading (vitalAperiodic) within 4 h.
    Temperature is rare in vitalPeriodic; when a stay has none, it is held at 36.9 C and flagged.
    Offsets are minutes from ICU admission (eICU stores no real dates).
    """
    import gzip

    hospitals: dict[str, dict] = {}
    with gzip.open(EICU_DIR / "hospital.csv.gz", "rt", newline="") as f:
        for r in csv.DictReader(f):
            hospitals[r["hospitalid"]] = {"beds": r["numbedscategory"] or "unknown",
                                          "teaching": r["teachingstatus"] == "t",
                                          "region": r["region"] or "unknown"}
    stays: dict[str, dict] = {}
    with gzip.open(EICU_DIR / "patient.csv.gz", "rt", newline="") as f:
        for r in csv.DictReader(f):
            stays[r["patientunitstayid"]] = {
                "hospital_id": r["hospitalid"], "unit_type": r["unittype"], "age": r["age"],
                "died_in_hospital": r["hospitaldischargestatus"] == "Expired",
                "died_in_unit": r["unitdischargestatus"] == "Expired",
                "unit_minutes": int(r["unitdischargeoffset"] or 0),
            }

    cuff: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    with gzip.open(EICU_DIR / "vitalAperiodic.csv.gz", "rt", newline="") as f:
        for r in csv.DictReader(f):
            s, d = _f(r["noninvasivesystolic"]), _f(r["noninvasivediastolic"])
            if _ok("sbp", s) and _ok("dbp", d) and d < s:  # type: ignore[operator]
                cuff[r["patientunitstayid"]].append((int(r["observationoffset"]), s, d))  # type: ignore[arg-type]

    periodic: dict[str, dict[int, dict[str, float]]] = defaultdict(dict)
    with gzip.open(EICU_DIR / "vitalPeriodic.csv.gz", "rt", newline="") as f:
        for r in csv.DictReader(f):
            vals = {"hr": _f(r["heartrate"]), "spo2": _f(r["sao2"]), "rr": _f(r["respiration"]),
                    "sbp": _f(r["systemicsystolic"]), "dbp": _f(r["systemicdiastolic"]), "temp": _f(r["temperature"])}
            periodic[r["patientunitstayid"]][int(r["observationoffset"])] = {
                k: v for k, v in vals.items() if _ok(k, v)}  # type: ignore[misc]

    meta: dict[str, dict] = {}
    rows_out: dict[str, list[list[float]]] = {}
    for stay, by_offset in periodic.items():
        info = stays.get(stay)
        if info is None:
            continue
        bp = sorted(cuff.get(stay, []))
        bi, last_bp = 0, None
        last_temp: tuple[int, float] | None = None
        rows: list[list[float]] = []
        temp_seen = False
        for off in sorted(by_offset):
            v = by_offset[off]
            while bi < len(bp) and bp[bi][0] <= off:
                last_bp = bp[bi]
                bi += 1
            if "temp" in v:
                last_temp = (off, v["temp"])
            if not all(k in v for k in ("hr", "spo2", "rr")):
                continue
            if "sbp" in v and "dbp" in v and v["dbp"] < v["sbp"]:
                sbp, dbp = v["sbp"], v["dbp"]
            elif last_bp is not None and off - last_bp[0] <= EICU_BP_FFILL_MIN:
                sbp, dbp = last_bp[1], last_bp[2]
            else:
                continue
            if last_temp is not None and off - last_temp[0] <= EICU_TEMP_FFILL_MIN:
                temp, measured = last_temp[1], 1
                temp_seen = True
            else:
                temp, measured = EICU_TEMP_FIXED, 0
            rows.append([off, v["hr"], v["spo2"], sbp, dbp, round(temp, 2), v["rr"], measured])
        if len(rows) < EICU_MIN_ROWS:
            continue
        h = hospitals.get(info["hospital_id"], {"beds": "unknown", "teaching": False, "region": "unknown"})
        meta[stay] = {**info, **{f"hospital_{k}": v for k, v in h.items()},
                      "rows": len(rows), "temp_measured": temp_seen}
        rows_out[stay] = rows

    EICU_META.write_text(json.dumps(meta))
    with gzip.open(EICU_ROWS, "wt") as f:
        json.dump(rows_out, f, separators=(",", ":"))
    _eicu_rows_cached.cache_clear()
    return meta, rows_out


def _cache_fresh() -> bool:
    if not (EICU_META.exists() and EICU_ROWS.exists()):
        return False
    newest_source = max((EICU_DIR / f"{n}.csv.gz").stat().st_mtime
                        for n in ("patient", "hospital", "vitalPeriodic", "vitalAperiodic"))
    return EICU_ROWS.stat().st_mtime >= newest_source


def load_eicu_meta() -> dict:
    if not _cache_fresh():
        return build_eicu_cache()[0]
    return json.loads(EICU_META.read_text())


@lru_cache(maxsize=1)
def _eicu_rows_cached() -> dict:
    import gzip

    with gzip.open(EICU_ROWS, "rt") as f:
        return json.load(f)


def load_eicu_rows() -> dict[str, list[list[float]]]:
    if not _cache_fresh():
        build_eicu_cache()
    return _eicu_rows_cached()


EICU_FIELDS = ("t_min", "hr", "spo2", "sbp", "dbp", "temp", "rr", "temp_measured")


def eicu_rows_as_dicts(rows: list[list[float]], drop_unmeasured: bool = False) -> list[dict]:
    """drop_unmeasured=True (live replay) leaves out temperature where it was never charted
    instead of the fixed 36.9 C that the evaluation uses."""
    out = [dict(zip(EICU_FIELDS, r, strict=True)) for r in rows]
    if drop_unmeasured:
        for d in out:
            if not d["temp_measured"]:
                del d["temp"]
    return out


class ReplayStream:
    """Plays recorded rows one per step, looping at the end. Same interface as synth.PatientStream."""

    def __init__(self, rows: list[dict], source: str, start: int = 0):
        self.rows, self.source, self.i = rows, source, start

    def start(self, kind: str, scale: float = 1.0) -> None:  # episodes cannot be injected into real data
        return None

    def step(self) -> tuple[dict, int, str]:
        r = self.rows[self.i % len(self.rows)]
        self.i += 1
        return {k: r[k] for k in VITALS if r.get(k) is not None}, 0, self.source


def replay_sources() -> list[dict]:
    """Choices for the simulator UI."""
    out = [{"id": "synthetic", "label": "Synthetic generator", "detail": "Generated vital signs with optional injected episodes"}]
    if available()["mimic"]:
        data = load_mimic()
        for stay, s in sorted(data.items(), key=lambda kv: (not kv[1]["died_in_hospital"], -len(kv[1]["rows"])))[:40]:
            out.append({"id": f"mimic:{stay}", "label": f"MIMIC-III ICU stay {stay}",
                        "detail": f"{len(s['rows'])} hourly rows, all six vitals real"
                                  + (", patient died in hospital" if s["died_in_hospital"] else "")})
    if eicu_available():
        meta = load_eicu_meta()
        ranked = sorted(meta.items(), key=lambda kv: (not kv[1]["died_in_hospital"], -kv[1]["rows"]))[:40]
        for stay, s in ranked:
            temp = "temperature measured" if s["temp_measured"] else "temperature not recorded (shown as not measured)"
            out.append({"id": f"eicu:{stay}", "label": f"eICU stay {stay} · hospital {s['hospital_id']}",
                        "detail": f"{s['rows']} five-minute rows, {s['hospital_region']} {s['hospital_beds']} beds; "
                                  f"{temp}" + ("; patient died in hospital" if s["died_in_hospital"] else "")})
    if available()["bidmc"]:
        for n in bidmc_records():
            out.append({"id": f"bidmc:{n}", "label": f"BIDMC record {n:02d}",
                        "detail": "8 min at 1 Hz; HR, SpO2, RR real; BP and temperature not recorded (shown as not measured)"})
    return out


def stream_for_source(source: str, start: int = 0) -> ReplayStream | None:
    if source.startswith("mimic:"):
        stay = load_mimic().get(source.split(":", 1)[1])
        return ReplayStream(stay["rows"], source, start) if stay else None
    if source.startswith("bidmc:"):
        return ReplayStream(load_bidmc(int(source.split(":", 1)[1]), fill_missing=False), source, start)
    if source.startswith("eicu:") and eicu_available():
        rows = load_eicu_rows().get(source.split(":", 1)[1])
        return ReplayStream(eicu_rows_as_dicts(rows, drop_unmeasured=True), source, start) if rows else None
    return None
