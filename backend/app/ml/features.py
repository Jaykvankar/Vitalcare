"""Feature extraction with a per-patient rolling baseline (EWMA mean/variance).

Features (18): six vitals, change since previous reading, z-score vs the patient's baseline.
The baseline state is stored AES-GCM encrypted per patient, so features never need the
plaintext history.

Readings may be partial (a real oximeter has no blood pressure). A partial reading updates the
baseline of the vitals it contains, but the model needs all six, so no features are produced for it.
A full reading behaves exactly as before, so training, evaluation and the pinned model are unaffected.
"""
from __future__ import annotations

import math

from .rules import VITALS

ALPHA = 0.03  # EWMA weight: baseline adapts over roughly 30-60 readings
STD_FLOOR = {"hr": 3.0, "spo2": 0.8, "sbp": 5.0, "dbp": 4.0, "temp": 0.15, "rr": 1.5}
FEATURE_NAMES = [*VITALS, *(f"d_{k}" for k in VITALS), *(f"z_{k}" for k in VITALS)]


def new_state() -> dict:
    return {"n": 0, "mean": {}, "var": {}, "prev": None}


def _ewma(k: str, x: float, mean: float, var: float) -> tuple[float, float, float]:
    """Return (z, new_mean, new_var) for one vital. Large excursions update the baseline slowly."""
    z = (x - mean) / max(math.sqrt(var), STD_FLOOR[k])
    a = ALPHA if abs(z) < 3 else ALPHA / 4
    d = x - mean
    return z, mean + a * d, (1 - a) * (var + a * d * d)


def is_complete(v: dict) -> bool:
    return all(k in v and v[k] is not None for k in VITALS)


def features_and_update(v: dict, state: dict) -> tuple[list[float] | None, dict]:
    """Return (features or None for a partial reading, updated baseline state)."""
    n = state.get("n", 0)
    mean = dict(state.get("mean") or {})
    var = dict(state.get("var") or {})
    prev = dict(state.get("prev") or {})

    if not is_complete(v):
        for k in VITALS:
            if k in v and v[k] is not None:
                if k not in mean:
                    mean[k], var[k] = v[k], STD_FLOOR[k] ** 2
                else:
                    _, mean[k], var[k] = _ewma(k, v[k], mean[k], var[k])
                prev[k] = v[k]
        return None, {"n": n + 1, "mean": mean, "var": var, "prev": prev}

    if n == 0:
        mean = {k: v[k] for k in VITALS}
        var = {k: STD_FLOOR[k] ** 2 for k in VITALS}
        prev = dict(v)
    for k in VITALS:  # vitals never seen before (earlier readings were partial) start from this value
        if k not in mean:
            mean[k], var[k] = v[k], STD_FLOOR[k] ** 2
        if k not in prev:
            prev[k] = v[k]

    deltas = [v[k] - prev[k] for k in VITALS]
    z, new_mean, new_var = [], {}, {}
    for k in VITALS:
        zk, new_mean[k], new_var[k] = _ewma(k, v[k], mean[k], var[k])
        z.append(zk)
    feats = [float(v[k]) for k in VITALS] + deltas + z
    return feats, {"n": n + 1, "mean": new_mean, "var": new_var, "prev": {k: v[k] for k in VITALS}}
