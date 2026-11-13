"""Loaders for the open-access real datasets in data/real/ (downloaded from PhysioNet, git-ignored).

MIMIC-III Clinical Database Demo v1.4 (ODbL): 100 de-identified ICU patients.
    Charted vitals are aggregated to hourly medians per ICU stay, forward-filled up to 4 h.
    Gives all six vitals plus the in-hospital outcome.
BIDMC PPG and Respiration Dataset v1.0.0 (ODC-BY): 53 ICU recordings, 8 min each, 1 Hz.
    Has HR, SpO2 and RR only. Blood pressure and temperature were not recorded; replay holds them
    at fixed normal values and marks them as not measured.

Dates in MIMIC are shifted for de-identification; only relative times are used.
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime
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
    return {"mimic": (MIMIC_DIR / "CHARTEVENTS.csv").exists(), "bidmc": BIDMC_DIR.exists() and any(BIDMC_DIR.glob("*.csv"))}


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


def load_bidmc(n: int, step_s: int = 5) -> list[dict]:
    """One BIDMC record as `step_s`-second medians; BP and temperature held fixed (not recorded)."""
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
                        **BIDMC_FIXED})
    return out


def bidmc_records() -> list[int]:
    return sorted(int(p.name.split("_")[1]) for p in BIDMC_DIR.glob("bidmc_*_Numerics.csv"))


class ReplayStream:
    """Plays recorded rows one per step, looping at the end. Same interface as synth.PatientStream."""

    def __init__(self, rows: list[dict], source: str, start: int = 0):
        self.rows, self.source, self.i = rows, source, start

    def start(self, kind: str, scale: float = 1.0) -> None:  # episodes cannot be injected into real data
        return None

    def step(self) -> tuple[dict, int, str]:
        r = self.rows[self.i % len(self.rows)]
        self.i += 1
        return {k: r[k] for k in VITALS}, 0, self.source


def replay_sources() -> list[dict]:
    """Choices for the simulator UI."""
    out = [{"id": "synthetic", "label": "Synthetic generator", "detail": "Generated vital signs with optional injected episodes"}]
    if available()["mimic"]:
        data = load_mimic()
        for stay, s in sorted(data.items(), key=lambda kv: (not kv[1]["died_in_hospital"], -len(kv[1]["rows"])))[:40]:
            out.append({"id": f"mimic:{stay}", "label": f"MIMIC-III ICU stay {stay}",
                        "detail": f"{len(s['rows'])} hourly rows, all six vitals real"
                                  + (", patient died in hospital" if s["died_in_hospital"] else "")})
    if available()["bidmc"]:
        for n in bidmc_records():
            out.append({"id": f"bidmc:{n}", "label": f"BIDMC record {n:02d}",
                        "detail": "8 min at 1 Hz; HR, SpO2, RR real; BP and temperature not recorded (held fixed)"})
    return out


def stream_for_source(source: str, start: int = 0) -> ReplayStream | None:
    if source.startswith("mimic:"):
        stay = load_mimic().get(source.split(":", 1)[1])
        return ReplayStream(stay["rows"], source, start) if stay else None
    if source.startswith("bidmc:"):
        return ReplayStream(load_bidmc(int(source.split(":", 1)[1])), source, start)
    return None
