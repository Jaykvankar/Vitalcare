"""Risk scoring at ingest time: clinical rules + NEWS2 + classifier."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from ..security.hashing import sha512_hex
from .features import features_and_update
from .rules import evaluate_rules, news2

ML_THRESHOLD = 0.6
ML_DIR = Path(__file__).resolve().parent


class ModelIntegrityError(RuntimeError):
    pass


_model = None
_lock = threading.Lock()


def load_model():
    """Load model.joblib only if its SHA-512 matches the pinned value (unpickling runs code)."""
    global _model
    with _lock:
        if _model is None:
            from .model_hash import MODEL_SHA512

            path = ML_DIR / "model.joblib"
            data = path.read_bytes()
            if sha512_hex(data) != MODEL_SHA512:
                raise ModelIntegrityError("model.joblib does not match the pinned SHA-512; refusing to load")
            _model = joblib.load(path)
        return _model


def band_for(reasons: list[tuple[str, str]], prob: float, news: int) -> tuple[str, list[tuple[str, str]]]:
    """Combine rules, NEWS2 and model. The model can raise the band but never lower a rule."""
    reasons = list(reasons)
    severities = {s for _, s in reasons}
    if prob >= ML_THRESHOLD:
        reasons.append(("ML_RISK", "warning"))
    if news >= 7:
        reasons.append(("NEWS2_HIGH", "critical"))
    elif news >= 5:
        reasons.append(("NEWS2_MEDIUM", "warning"))
    severities = {s for _, s in reasons}
    if "critical" in severities:
        return "critical", reasons
    if "warning" in severities:
        return "warning", reasons
    return "normal", reasons


@dataclass
class Score:
    band: str
    risk: float          # model probability 0..1
    news2: int
    reasons: list[tuple[str, str]]
    state: dict          # updated baseline state (caller re-encrypts it)


def score(vitals: dict, state: dict) -> Score:
    feats, new_state = features_and_update(vitals, state)
    prob = float(load_model().predict_proba(np.array([feats]))[0, 1])
    n = news2(vitals)
    band, reasons = band_for(evaluate_rules(vitals), prob, n)
    return Score(band=band, risk=round(prob, 4), news2=n, reasons=reasons, state=new_state)
