"""Clinical rules and NEWS2. Rules always win over the model."""
from __future__ import annotations

VITALS = ("hr", "spo2", "sbp", "dbp", "temp", "rr")

# (code, severity, predicate)
RULES = [
    ("SPO2_LOW", "critical", lambda v: v["spo2"] < 92),
    ("HR_HIGH", "critical", lambda v: v["hr"] > 120),
    ("HR_LOW", "critical", lambda v: v["hr"] < 45),
    ("BP_LOW", "critical", lambda v: v["sbp"] < 90),
    ("BP_HIGH", "critical", lambda v: v["sbp"] > 180),
    ("TEMP_HIGH", "critical", lambda v: v["temp"] >= 38.5),
    ("TEMP_LOW", "critical", lambda v: v["temp"] < 35.0),
    ("RR_HIGH", "critical", lambda v: v["rr"] > 24),
    ("RR_LOW", "critical", lambda v: v["rr"] < 8),
    # warning band
    ("SPO2_LOW", "warning", lambda v: 92 <= v["spo2"] < 95),
    ("HR_HIGH", "warning", lambda v: 100 < v["hr"] <= 120),
    ("HR_LOW", "warning", lambda v: 45 <= v["hr"] < 50),
    ("BP_LOW", "warning", lambda v: 90 <= v["sbp"] < 100),
    ("BP_HIGH", "warning", lambda v: 160 < v["sbp"] <= 180),
    ("TEMP_HIGH", "warning", lambda v: 38.0 <= v["temp"] < 38.5),
    ("RR_HIGH", "warning", lambda v: 20 < v["rr"] <= 24),
]


def evaluate_rules(v: dict) -> list[tuple[str, str]]:
    """Return [(reason_code, severity)], highest severity per code. Rules for vitals that were
    not measured in this reading are skipped."""
    found: dict[str, str] = {}
    for code, sev, pred in RULES:
        if code in found:
            continue
        try:
            hit = pred(v)
        except (KeyError, TypeError):
            continue
        if hit:
            found[code] = sev
    return sorted(found.items())


NEWS2_INPUTS = ("rr", "spo2", "sbp", "hr", "temp")


def news2(v: dict) -> int:
    """NEWS2 subscores for the vitals we measure (no O2 supplement / consciousness inputs).
    Vitals missing from a partial reading add nothing, so a partial score is a lower bound."""
    def has(k: str) -> bool:
        return v.get(k) is not None

    s = 0
    if has("rr"):
        rr = v["rr"]
        s += 3 if rr <= 8 else 1 if rr <= 11 else 0 if rr <= 20 else 2 if rr <= 24 else 3
    if has("spo2"):
        spo2 = v["spo2"]
        s += 3 if spo2 <= 91 else 2 if spo2 <= 93 else 1 if spo2 <= 95 else 0
    if has("sbp"):
        sbp = v["sbp"]
        s += 3 if sbp <= 90 else 2 if sbp <= 100 else 1 if sbp <= 110 else 0 if sbp < 220 else 3
    if has("hr"):
        hr = v["hr"]
        s += 3 if hr <= 40 else 1 if hr <= 50 else 0 if hr <= 90 else 1 if hr <= 110 else 2 if hr <= 130 else 3
    if has("temp"):
        t = v["temp"]
        s += 3 if t <= 35.0 else 1 if t <= 36.0 else 0 if t <= 38.0 else 1 if t <= 39.0 else 2
    return s


def news2_inputs_present(v: dict) -> int:
    return sum(v.get(k) is not None for k in NEWS2_INPUTS)


# Physiologically plausible input ranges: anything outside is rejected at ingest.
PLAUSIBLE = {
    "hr": (20, 250), "spo2": (50, 100), "sbp": (40, 260), "dbp": (20, 160),
    "temp": (30.0, 43.0), "rr": (3, 60),
}


def validate(v: dict) -> dict:
    """Check a reading. Any subset of the six vitals is allowed (real sensors measure only some),
    but at least one must be present, values must be plausible, and blood pressure comes as a pair."""
    if not isinstance(v, dict):
        raise ValueError("reading must be an object")
    unknown = [k for k in v if k not in VITALS]
    if unknown:
        raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
    out = {}
    for k in VITALS:
        if v.get(k) is None or (isinstance(v[k], str) and not v[k].strip()):
            continue  # not measured (missing key, null, or an empty CSV cell)
        x = float(v[k])
        if x != x:
            raise ValueError(f"{k} is not a number")
        lo, hi = PLAUSIBLE[k]
        if not lo <= x <= hi:
            raise ValueError(f"{k}={x} outside plausible range")
        out[k] = round(x, 2)
    if not out:
        raise ValueError("no vital signs in reading")
    if ("sbp" in out) != ("dbp" in out):
        raise ValueError("blood pressure needs both systolic and diastolic")
    if "sbp" in out and out["dbp"] >= out["sbp"]:
        raise ValueError("diastolic must be below systolic")
    return out
