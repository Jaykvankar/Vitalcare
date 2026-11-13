"""Train and evaluate the deterioration model.

    python -m app.ml.train          (from backend/)

Writes app/ml/model.joblib, app/ml/model_hash.py (pinned SHA-512) and docs/model_report.md.
Patients are split into train/test groups so no patient appears in both (no leakage).
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

from ..security.hashing import sha512_hex
from .features import FEATURE_NAMES, features_and_update, new_state
from .infer import ML_THRESHOLD, band_for
from .rules import evaluate_rules, news2
from .synth import DETERIORATION, PatientStream

ML_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ML_DIR.parents[2]
STEPS_PER_DAY = 1440  # one reading per minute


def simulate(n_patients: int, days: float, seed: int, episode_rate: float = 0.002):
    rng = random.Random(seed)
    data = []
    for pid in range(n_patients):
        stream = PatientStream(random.Random(rng.random()), episode_rate=episode_rate)
        state = new_state()
        rows, labels, kinds, vitals = [], [], [], []
        for _ in range(int(days * STEPS_PER_DAY)):
            v, label, kind = stream.step()
            feats, state = features_and_update(v, state)
            rows.append(feats)
            labels.append(label)
            kinds.append(kind)
            vitals.append(v)
        data.append((pid, np.array(rows), np.array(labels), kinds, vitals))
    return data


def episodes(kinds: list[str]) -> list[tuple[int, int, str]]:
    """Contiguous deterioration segments as (start, end, kind)."""
    out, start = [], None
    for i, k in enumerate([*kinds, "stable"]):
        if k in DETERIORATION and start is None:
            start = i
        elif (k not in DETERIORATION or (start is not None and k != kinds[start])) and start is not None:
            out.append((start, i, kinds[start]))
            start = i if k in DETERIORATION else None
    return out


REFRACTORY = 10  # minutes: a new alarm event needs 10 quiet readings first (mirrors alert de-duplication)


def _alarm_events(alarm: np.ndarray) -> list[int]:
    events, quiet_run = [], REFRACTORY
    for i, a in enumerate(alarm):
        if a:
            if quiet_run >= REFRACTORY:
                events.append(i)
            quiet_run = 0
        else:
            quiet_run += 1
    return events


def system_eval(model, data, use_model: bool) -> dict:  # noqa: ANN001
    detected = total = 0
    delays: list[int] = []
    false_any = false_crit = 0
    patient_days = 0.0
    for _, X, y, kinds, vitals in data:
        probs = model.predict_proba(X)[:, 1] if use_model else np.zeros(len(X))
        bands = [band_for(evaluate_rules(v), float(p) if use_model else 0.0, news2(v))[0]
                 for v, p in zip(vitals, probs)]
        alarm = np.array([b != "normal" for b in bands])
        crit = np.array([b == "critical" for b in bands])
        for s, e, _ in episodes(kinds):
            total += 1
            hits = np.flatnonzero(alarm[s:e])
            if len(hits):
                detected += 1
                delays.append(int(hits[0]))
        quiet = [k not in DETERIORATION for k in kinds]
        false_any += sum(quiet[i] for i in _alarm_events(alarm))
        false_crit += sum(quiet[i] for i in _alarm_events(crit))
        patient_days += len(X) / STEPS_PER_DAY
    return {
        "episodes": total,
        "episode_recall": detected / total if total else 0.0,
        "median_minutes_to_alert": float(np.median(delays)) if delays else float("nan"),
        "false_alarms_per_patient_day": false_any / patient_days,
        "false_critical_per_patient_day": false_crit / patient_days,
    }


def main() -> None:
    print("Simulating training data ...")
    train = simulate(n_patients=160, days=1.0, seed=7)
    test = simulate(n_patients=40, days=1.0, seed=99)
    X_tr = np.vstack([d[1] for d in train])
    y_tr = np.concatenate([d[2] for d in train])
    X_te = np.vstack([d[1] for d in test])
    y_te = np.concatenate([d[2] for d in test])
    print(f"train rows={len(X_tr)} positives={y_tr.mean():.3f}; test rows={len(X_te)}")

    model = HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0,
        class_weight="balanced", random_state=0,
    )
    model.fit(X_tr, y_tr)

    p = model.predict_proba(X_te)[:, 1]
    pred = (p >= ML_THRESHOLD).astype(int)
    cm = confusion_matrix(y_te, pred)
    reading_metrics = {
        "auc": roc_auc_score(y_te, p),
        "precision": precision_score(y_te, pred),
        "recall": recall_score(y_te, pred),
        "f1": f1_score(y_te, pred),
    }
    rules_only = system_eval(model, test, use_model=False)
    combined = system_eval(model, test, use_model=True)

    model_path = ML_DIR / "model.joblib"
    joblib.dump(model, model_path, compress=3)
    digest = sha512_hex(model_path.read_bytes())
    (ML_DIR / "model_hash.py").write_text(
        '"""Pinned SHA-512 of model.joblib, written by train.py. Loading refuses any other file."""\n'
        f'MODEL_SHA512 = "{digest}"\n'
    )

    report = f"""# Risk model report

Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} by `backend/app/ml/train.py`.

## Setup
- Model: scikit-learn `HistGradientBoostingClassifier` (class-balanced), threshold {ML_THRESHOLD}.
- Features (18): {", ".join(FEATURE_NAMES)}.
- Data: synthetic, one reading per minute. 160 training patients and 40 **different** test patients, one day each
  (split by patient, so no leakage). Episodes: hypoxia, tachycardia, hypotension, fever (label 1 once severity >= 30%),
  plus harmless "activity" heart-rate rises (label 0).
- Test rows: {len(X_te)}, positive rate {y_te.mean():.3f}.

## Per-reading metrics (model alone)
| AUC | Precision | Recall | F1 |
|---|---|---|---|
| {reading_metrics['auc']:.3f} | {reading_metrics['precision']:.3f} | {reading_metrics['recall']:.3f} | {reading_metrics['f1']:.3f} |

Confusion matrix (rows = truth 0/1, columns = predicted 0/1):

| | pred 0 | pred 1 |
|---|---|---|
| true 0 | {cm[0, 0]} | {cm[0, 1]} |
| true 1 | {cm[1, 0]} | {cm[1, 1]} |

## Whole system on test patients (what clinicians experience)
An alarm is any non-normal band. "Rules only" = clinical thresholds + NEWS2; "Rules + model" adds the classifier.
False alarms are alarm events outside deterioration episodes, counted with a {REFRACTORY}-minute refractory
window (the app keeps one open alert per reason code, so flicker does not create new alerts).

| System | Episodes | Episode recall | Median minutes to first alarm | False alarms / patient-day (any) | False critical / patient-day |
|---|---|---|---|---|---|
| Rules only | {rules_only['episodes']} | {rules_only['episode_recall']:.3f} | {rules_only['median_minutes_to_alert']:.1f} | {rules_only['false_alarms_per_patient_day']:.2f} | {rules_only['false_critical_per_patient_day']:.2f} |
| Rules + model | {combined['episodes']} | {combined['episode_recall']:.3f} | {combined['median_minutes_to_alert']:.1f} | {combined['false_alarms_per_patient_day']:.2f} | {combined['false_critical_per_patient_day']:.2f} |

## Limitations
Synthetic data only; the numbers show the pipeline works, not clinical validity. A real deployment needs validation on
real monitored patients (for example PhysioNet datasets) and clinical review of thresholds.

## Integrity
`model.joblib` SHA-512 (pinned in `model_hash.py`, checked before loading):
`{digest}`
"""
    (PROJECT_DIR / "docs").mkdir(exist_ok=True)
    (PROJECT_DIR / "docs" / "model_report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
