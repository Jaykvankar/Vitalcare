"""Train the deterioration model on real ICU data (eICU Collaborative Research Database demo).

    python -m app.ml.train_real            (from backend/)  evaluate only, nothing is replaced
    python -m app.ml.train_real --save     evaluate, then ship: model.joblib, model_hash.py, docs/model_report.md

Target: for every 5-minute reading, "this patient dies in the ICU within the next 24 hours" (a standard early-warning
target). Features are the same 18 per-reading features the live app computes (values, change since the last reading,
distance from the patient's own running baseline), so the trained model drops straight into ingest.

Validation is honest about new hospitals:
  * eICU: 5-fold GroupKFold by hospital, so every score is for hospitals the model never trained on.
  * MIMIC-III demo: a completely separate hospital system, used only as an external test, never for training.
The alert threshold is chosen on the out-of-fold eICU predictions (95% specificity) and pinned with the model.

Data licences: eICU-CRD demo and MIMIC-III demo are open-access PhysioNet databases (ODbL). Raw data is never committed.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from ..security.hashing import sha512_hex
from . import realdata
from .features import FEATURE_NAMES, features_and_update, new_state
from .rules import news2

ML_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ML_DIR.parents[2]
HORIZON_MIN = 24 * 60          # label: death in the ICU within the next 24 h
TRAIN_EVERY = 3                # keep every 3rd 5-minute reading for training (15-minute spacing)
TARGET_SPECIFICITY = 0.95      # threshold: at most 5% of readings from patients who do not die raise ML_RISK
SYNTHETIC_COPY = ML_DIR / "model_synthetic.joblib"
VITALS = ("hr", "spo2", "sbp", "dbp", "temp", "rr")


def make_model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=200, l2_regularization=1.0,
        class_weight="balanced", random_state=0,
    )


def stay_features(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Features for every reading of one stay, in time order, plus each reading's NEWS2."""
    state = new_state()
    feats, scores = [], []
    for r in rows:
        v = {k: float(r[k]) for k in VITALS}
        f, state = features_and_update(v, state)
        assert f is not None  # replay rows used for training always carry all six values
        feats.append(f)
        scores.append(news2(v))
    return np.array(feats, dtype=np.float32), np.array(scores, dtype=np.float32)


def load_eicu() -> dict:
    meta = realdata.load_eicu_meta()
    rows = realdata.load_eicu_rows()
    X, y, news, groups, stays, t = [], [], [], [], [], []
    for stay_id, m in meta.items():
        r = realdata.eicu_rows_as_dicts(rows[stay_id])   # temperature held at 36.9 C where never charted
        f, s = stay_features(r)
        tmin = np.array([row["t_min"] for row in r])
        lab = m["unit_minutes"] - tmin <= HORIZON_MIN if m["died_in_unit"] else np.zeros(len(r), dtype=bool)
        keep = np.arange(len(r)) % TRAIN_EVERY == 0
        X.append(f[keep])
        y.append(lab[keep].astype(np.int8))
        news.append(s[keep])
        groups += [m["hospital_id"]] * int(keep.sum())
        stays += [stay_id] * int(keep.sum())
        t.append(tmin[keep])
    return {"X": np.vstack(X), "y": np.concatenate(y), "news2": np.concatenate(news),
            "groups": np.array(groups), "stays": np.array(stays), "meta": meta}


def load_mimic() -> dict:
    data = realdata.load_mimic()
    X, y, news, stays = [], [], [], []
    for stay_id, m in data.items():
        rows = [r for r in m["rows"] if all(r.get(k) is not None for k in VITALS)]
        if len(rows) < 2:
            continue
        f, s = stay_features(rows)
        th = np.array([r["t_h"] for r in rows], dtype=float)
        if m["died_in_hospital"] and m["death_hour"] is not None:
            lab = (m["death_hour"] - th) <= HORIZON_MIN / 60
        else:
            lab = np.zeros(len(rows), dtype=bool)
        X.append(f)
        y.append(lab.astype(np.int8))
        news.append(s)
        stays += [stay_id] * len(rows)
    return {"X": np.vstack(X), "y": np.concatenate(y), "news2": np.concatenate(news), "stays": np.array(stays)}


def threshold_at_specificity(y: np.ndarray, p: np.ndarray, spec: float) -> float:
    return float(np.quantile(p[y == 0], spec))


def rates(y: np.ndarray, p: np.ndarray, thr: float, n_readings_per_day: float) -> dict:
    alarm = p >= thr
    return {"sensitivity": float(alarm[y == 1].mean()) if (y == 1).any() else float("nan"),
            "specificity": float((~alarm[y == 0]).mean()),
            "alerts_per_patient_day": float(alarm[y == 0].mean() * n_readings_per_day)}


# SHA-512 of the earlier synthetic-trained model. joblib files are pickles (loading runs code), so this file is
# only loaded after its hash matches, exactly as the app does for the shipped model.
SYNTHETIC_SHA512 = ("cbe4f406e67400fb5066dccf28fb35822bd787035efe7750b8ac2cf3abda8ed9"
                    "755c16a6df2b5dba5a71353e4e29e6ae0368ff999e07d8c9ea7e012f4d3c2851")


def synthetic_model():
    """The previous, synthetic-trained model, kept for comparison only (never loaded by the app)."""
    path = SYNTHETIC_COPY if SYNTHETIC_COPY.exists() else ML_DIR / "model.joblib"
    if sha512_hex(path.read_bytes()) != SYNTHETIC_SHA512:
        raise SystemExit(f"{path.name} is not the pinned synthetic model; refusing to load it")
    return joblib.load(path), path.name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="ship the model trained on all eICU stays")
    a = ap.parse_args()
    if not realdata.eicu_available():
        raise SystemExit("eICU demo not found in data/real/eicu (see README: Real data)")

    print("Building features for eICU stays ...", flush=True)
    e = load_eicu()
    X, y, g = e["X"], e["y"], e["groups"]
    print(f"eICU: {len(X)} readings, {y.sum()} positive, {len(set(g))} hospitals, {len(e['meta'])} stays", flush=True)

    synth, synth_name = synthetic_model()
    p_synth = synth.predict_proba(X)[:, 1]

    oof = np.zeros(len(X))
    folds = []
    for k, (tr, te) in enumerate(GroupKFold(n_splits=5).split(X, y, g)):
        m = make_model().fit(X[tr], y[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]
        folds.append({"fold": k + 1, "hospitals": len(set(g[te])), "readings": len(te), "positives": int(y[te].sum()),
                      "real": roc_auc_score(y[te], oof[te]), "news2": roc_auc_score(y[te], e["news2"][te]),
                      "synthetic": roc_auc_score(y[te], p_synth[te])})
        print(f"  fold {k + 1}: real {folds[-1]['real']:.3f}  NEWS2 {folds[-1]['news2']:.3f}  "
              f"synthetic {folds[-1]['synthetic']:.3f}", flush=True)
    real_auc = [f["real"] for f in folds]
    thr = threshold_at_specificity(y, oof, TARGET_SPECIFICITY)
    per_day = 24 * 60 / (5 * TRAIN_EVERY)
    eicu_rates = rates(y, oof, thr, per_day)

    print("Training on all eICU stays ...", flush=True)
    final = make_model().fit(X, y)

    print("External test on MIMIC-III demo ...", flush=True)
    mm = load_mimic()
    p_mimic = final.predict_proba(mm["X"])[:, 1]
    mimic = {"readings": len(mm["X"]), "positives": int(mm["y"].sum()), "stays": len(set(mm["stays"])),
             "real": roc_auc_score(mm["y"], p_mimic), "news2": roc_auc_score(mm["y"], mm["news2"]),
             "synthetic": roc_auc_score(mm["y"], synth.predict_proba(mm["X"])[:, 1])}
    mimic_rates = rates(mm["y"], p_mimic, thr, 24.0)

    summary = {
        "eicu_real": (float(np.mean(real_auc)), float(np.std(real_auc))),
        "eicu_news2": roc_auc_score(y, e["news2"]), "eicu_synthetic": roc_auc_score(y, p_synth),
        "eicu_real_pooled": roc_auc_score(y, oof),
    }
    print(f"eICU held-out hospitals: real {summary['eicu_real'][0]:.3f} ± {summary['eicu_real'][1]:.3f}, "
          f"NEWS2 {summary['eicu_news2']:.3f}, synthetic {summary['eicu_synthetic']:.3f}")
    print(f"MIMIC external: real {mimic['real']:.3f}, NEWS2 {mimic['news2']:.3f}, synthetic {mimic['synthetic']:.3f}")
    print(f"threshold {thr:.4f}: eICU {eicu_rates}, MIMIC {mimic_rates}")

    if not a.save:
        print("\nEvaluation only. Run with --save to ship this model.")
        return

    current = ML_DIR / "model.joblib"
    if not SYNTHETIC_COPY.exists():
        shutil.copyfile(current, SYNTHETIC_COPY)
    joblib.dump(final, current, compress=3)
    digest = sha512_hex(current.read_bytes())
    (ML_DIR / "model_hash.py").write_text(
        '"""Pinned SHA-512 of model.joblib, written by train_real.py. Loading refuses any other file."""\n'
        f'MODEL_SHA512 = "{digest}"\n'
        f"MODEL_THRESHOLD = {thr!r}  # ML_RISK when probability >= this (95% specificity on held-out hospitals)\n"
        'MODEL_TRAINED_ON = "eICU-CRD demo (real ICU patients, 184 hospitals)"\n'
    )
    fold_rows = "\n".join(
        f"| {f['fold']} | {f['hospitals']} | {f['readings']} | {f['positives']} | {f['real']:.3f} | {f['news2']:.3f} | "
        f"{f['synthetic']:.3f} |" for f in folds)
    report = f"""# Risk model report

Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by `backend/app/ml/train_real.py`.

## What the shipped model is
- **Trained on real ICU patients**: eICU Collaborative Research Database demo, {len(e['meta'])} ICU stays from
  {len(set(g))} US hospitals, {len(X)} readings at 15-minute spacing (taken from 5-minute data).
- **Target**: for each reading, "the patient dies in the ICU within the next 24 hours" ({y.sum()} positive readings,
  {y.mean():.2%}).
- **Model**: scikit-learn `HistGradientBoostingClassifier` (class-balanced) on the same 18 per-reading features the live
  app computes: {", ".join(FEATURE_NAMES)}.
- **Alert threshold**: {thr:.4f}, chosen on out-of-fold predictions for {TARGET_SPECIFICITY:.0%} specificity and pinned
  in `model_hash.py` with the model's SHA-512. The model can raise a band to *warning* (ML_RISK); it never lowers a rule.

## Held-out hospitals (eICU, 5-fold GroupKFold by hospital)
Every score below is for hospitals the model never saw while training. AUROC per reading (0.5 = chance, 1 = perfect).

| Fold | Hospitals | Readings | Positive | Real-data model | NEWS2 | Previous synthetic model |
|---|---|---|---|---|---|---|
{fold_rows}
| **All** | {len(set(g))} | {len(X)} | {int(y.sum())} | **{summary['eicu_real'][0]:.3f} ± {summary['eicu_real'][1]:.3f}** | {summary['eicu_news2']:.3f} | {summary['eicu_synthetic']:.3f} |

At the pinned threshold (out-of-fold): sensitivity {eicu_rates['sensitivity']:.1%}, specificity
{eicu_rates['specificity']:.1%}, about {eicu_rates['alerts_per_patient_day']:.1f} model warnings per patient-day for patients
who did not die (one reading every 15 minutes; the app keeps one open alert per reason, so these merge into far fewer alerts).

## External test: MIMIC-III demo (different hospital system, never used for training)
{mimic['stays']} ICU stays, {mimic['readings']} hourly readings, {mimic['positives']} positive.

| Signal | AUROC |
|---|---|
| Real-data model (trained on eICU only) | **{mimic['real']:.3f}** |
| NEWS2 | {mimic['news2']:.3f} |
| Previous synthetic model | {mimic['synthetic']:.3f} |

At the pinned threshold: sensitivity {mimic_rates['sensitivity']:.1%}, specificity {mimic_rates['specificity']:.1%}.

## Limits
- Small demo datasets: {int(y.sum())} positive eICU readings from about 100 deaths, so results carry real uncertainty
  (see the ± across folds). The full credentialed eICU / MIMIC-IV databases would give a much stronger model.
- Temperature was charted for few eICU stays; where missing it was held at 36.9 °C for training, so the model learns
  little from temperature (the clinical fever rules still apply).
- ICU patients are sicker than patients monitored at home; a home-monitoring deployment should be re-validated locally.
- Decision support only: rules and NEWS2 always run, and every alert lists its reasons.

## Previous model
The earlier synthetic-trained model is kept as `{SYNTHETIC_COPY.name}` for comparison only (`train.py` can rebuild it).
It is never loaded by the app.

## Integrity
`model.joblib` SHA-512 (pinned in `model_hash.py`, checked before loading):
`{digest}`
"""
    (PROJECT_DIR / "docs" / "model_report.md").write_text(report, encoding="utf-8")
    print(f"\nShipped. SHA-512 {digest[:32]}… threshold {thr:.4f}. Report: docs/model_report.md")


if __name__ == "__main__":
    main()
