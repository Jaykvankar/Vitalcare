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
    """Return [(reason_code, severity)], highest severity per code."""
    found: dict[str, str] = {}
    for code, sev, pred in RULES:
        if code not in found and pred(v):
            found[code] = sev
    return sorted(found.items())


def news2(v: dict) -> int:
    """NEWS2 subscores for the vitals we measure (no O2 supplement / consciousness inputs)."""
    rr, spo2, sbp, hr, t = v["rr"], v["spo2"], v["sbp"], v["hr"], v["temp"]
    s = 0
    s += 3 if rr <= 8 else 1 if rr <= 11 else 0 if rr <= 20 else 2 if rr <= 24 else 3
    s += 3 if spo2 <= 91 else 2 if spo2 <= 93 else 1 if spo2 <= 95 else 0
    s += 3 if sbp <= 90 else 2 if sbp <= 100 else 1 if sbp <= 110 else 0 if sbp < 220 else 3
    s += 3 if hr <= 40 else 1 if hr <= 50 else 0 if hr <= 90 else 1 if hr <= 110 else 2 if hr <= 130 else 3
    s += 3 if t <= 35.0 else 1 if t <= 36.0 else 0 if t <= 38.0 else 1 if t <= 39.0 else 2
    return s


# Physiologically plausible input ranges: anything outside is rejected at ingest.
PLAUSIBLE = {
    "hr": (20, 250), "spo2": (50, 100), "sbp": (40, 260), "dbp": (20, 160),
    "temp": (30.0, 43.0), "rr": (3, 60),
}


def validate(v: dict) -> dict:
    out = {}
    for k in VITALS:
        if k not in v:
            raise ValueError(f"missing vital {k}")
        x = float(v[k])
        lo, hi = PLAUSIBLE[k]
        if not lo <= x <= hi:
            raise ValueError(f"{k}={x} outside plausible range")
        out[k] = round(x, 2)
    if out["dbp"] >= out["sbp"]:
        raise ValueError("diastolic must be below systolic")
    return out
