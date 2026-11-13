"""Feature extraction with a per-patient rolling baseline (EWMA mean/variance).

Features (18): six vitals, change since previous reading, z-score vs the patient's baseline.
The baseline state is stored AES-GCM encrypted per patient, so features never need the
plaintext history.
"""
from __future__ import annotations

import math

from .rules import VITALS

ALPHA = 0.03  # EWMA weight: baseline adapts over roughly 30-60 readings
STD_FLOOR = {"hr": 3.0, "spo2": 0.8, "sbp": 5.0, "dbp": 4.0, "temp": 0.15, "rr": 1.5}
FEATURE_NAMES = [*VITALS, *(f"d_{k}" for k in VITALS), *(f"z_{k}" for k in VITALS)]


def new_state() -> dict:
    return {"n": 0, "mean": {}, "var": {}, "prev": None}


def features_and_update(v: dict, state: dict) -> tuple[list[float], dict]:
    if state.get("n", 0) == 0:
        mean = {k: v[k] for k in VITALS}
        var = {k: STD_FLOOR[k] ** 2 for k in VITALS}
        prev = v
    else:
        mean, var, prev = state["mean"], state["var"], state["prev"]

    deltas = [v[k] - prev[k] for k in VITALS]
    z = [(v[k] - mean[k]) / max(math.sqrt(var[k]), STD_FLOOR[k]) for k in VITALS]
    feats = [float(v[k]) for k in VITALS] + deltas + z

    # Update baseline. Large excursions update it more slowly so an episode does not
    # become the "new normal" within minutes.
    new_mean, new_var = {}, {}
    for i, k in enumerate(VITALS):
        a = ALPHA if abs(z[i]) < 3 else ALPHA / 4
        d = v[k] - mean[k]
        new_mean[k] = mean[k] + a * d
        new_var[k] = (1 - a) * (var[k] + a * d * d)
    return feats, {"n": state.get("n", 0) + 1, "mean": new_mean, "var": new_var, "prev": dict(v)}
