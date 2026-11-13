"""Evaluate the risk engine on REAL patient data (open PhysioNet datasets).

    python -m app.ml.eval_real          (from backend/, after downloading data/real/)

Writes docs/real_data_report.md. The model itself is still trained on synthetic data; this script
measures how the rules, NEWS2 and the model behave on real ICU vital signs.
"""
from __future__ import annotations

import statistics
from datetime import UTC, datetime

import numpy as np
from sklearn.metrics import roc_auc_score

from .features import features_and_update, new_state
from .infer import band_for, load_model
from .realdata import (
    PROJECT_DIR,
    available,
    bidmc_records,
    eicu_rows_as_dicts,
    load_bidmc,
    load_eicu_meta,
    load_eicu_rows,
    load_mimic,
)
from .rules import evaluate_rules, news2

REFRACTORY_H = 4
REFRACTORY_5MIN = 12  # one hour of 5-minute rows


def run_sequence(rows: list[dict], model) -> dict:
    state = new_state()
    feats, n2, rules = [], [], []
    for r in rows:
        v = {k: r[k] for k in ("hr", "spo2", "sbp", "dbp", "temp", "rr")}
        f, state = features_and_update(v, state)
        assert f is not None  # evaluation rows always contain all six vitals
        feats.append(f)
        n2.append(news2(v))
        rules.append(evaluate_rules(v))
    probs = model.predict_proba(np.array(feats))[:, 1]
    bands = [band_for(rl, float(p), n)[0] for rl, p, n in zip(rules, probs, n2, strict=False)]
    bands_rules = [band_for(rl, 0.0, n)[0] for rl, n in zip(rules, n2, strict=False)]
    return {"prob": probs, "news2": np.array(n2), "bands": bands, "bands_rules": bands_rules}


def events(flags: list[bool], refractory: int) -> int:
    count, quiet = 0, refractory
    for f in flags:
        if f:
            if quiet >= refractory:
                count += 1
            quiet = 0
        else:
            quiet += 1
    return count


def auc(y, s) -> float:
    return float(roc_auc_score(y, s)) if len(set(y)) == 2 else float("nan")


def mimic_section(model) -> str:
    stays = load_mimic()
    y: list[int] = []
    first24: dict[str, list[float]] = {"news2_max": [], "prob_mean": [], "crit_frac": [], "crit_frac_rules": []}
    last24: dict[str, list[float]] = {"news2_max": [], "prob_mean": [], "crit_frac": []}
    hours = crit_events = crit_events_rules = 0
    crit_hours = 0
    for s in stays.values():
        if len(s["rows"]) < 24:
            continue
        r = run_sequence(s["rows"], model)
        crit = [b == "critical" for b in r["bands"]]
        crit_r = [b == "critical" for b in r["bands_rules"]]
        hours += len(crit)
        crit_hours += sum(crit)
        crit_events += events(crit, REFRACTORY_H)
        crit_events_rules += events(crit_r, REFRACTORY_H)
        y.append(int(s["died_in_hospital"]))
        for d, sl in ((first24, slice(0, 24)), (last24, slice(-24, None))):
            d["news2_max"].append(int(r["news2"][sl].max()))
            d["prob_mean"].append(float(r["prob"][sl].mean()))
            d["crit_frac"].append(float(np.mean(crit[sl])))
        first24["crit_frac_rules"].append(float(np.mean(crit_r[:24])))
    days = hours / 24
    died = sum(y)
    return f"""## MIMIC-III Clinical Database Demo (real ICU patients)

- Source: PhysioNet `mimiciii-demo` v1.4 (Open Data Commons ODbL). 100 de-identified patients.
- Used: {len(y)} ICU stays with at least 24 hourly rows where all six vitals were charted ({died} patients died in hospital),
  {hours:,} patient-hours ({days:.0f} patient-days). Charted values were aggregated to hourly medians, forward-filled up to 4 h.
- Every hour was scored exactly as live readings are: rules + NEWS2 + model, with the per-patient rolling baseline.

### Alert burden on real ICU data
| Metric | Rules + NEWS2 only | Rules + NEWS2 + model |
|---|---|---|
| Critical alert events per patient-day ({REFRACTORY_H} h refractory) | {crit_events_rules / days:.2f} | {crit_events / days:.2f} |
| Hours spent in critical band | - | {crit_hours / hours:.1%} |

ICU patients are sick, so a high critical share is expected. Ward patients wearing a home monitor would trigger far fewer alerts.

### Does the score separate patients who later died? (stay-level AUROC, in-hospital mortality)
| Signal | First 24 h of the stay (early warning) | Last 24 h of data |
|---|---|---|
| Max NEWS2 | {auc(y, first24['news2_max']):.3f} | {auc(y, last24['news2_max']):.3f} |
| Mean model probability | {auc(y, first24['prob_mean']):.3f} | {auc(y, last24['prob_mean']):.3f} |
| Share of hours in critical band (combined) | {auc(y, first24['crit_frac']):.3f} | {auc(y, last24['crit_frac']):.3f} |
| Share of hours in critical band (rules only) | {auc(y, first24['crit_frac_rules']):.3f} | - |

0.5 means no better than chance. With only {len(y)} stays, these AUROCs carry wide uncertainty (roughly ±0.1).
"""


def bidmc_section(model) -> str:
    recs = bidmc_records()
    rows_total, flagged_rules, flagged_model = 0, 0, 0
    per_rec = []
    for n in recs:
        rows = load_bidmc(n, step_s=60)  # 1-minute medians, matching the model's training cadence
        if len(rows) < 3:
            continue
        r = run_sequence(rows, model)
        rows_total += len(rows)
        fr = sum(b != "normal" for b in r["bands_rules"])
        fm = sum(b != "normal" for b in r["bands"])
        flagged_rules += fr
        flagged_model += fm
        per_rec.append(statistics.mean(x["hr"] for x in rows))
    return f"""## BIDMC PPG and Respiration Dataset (real ICU recordings)

- Source: PhysioNet `bidmc` v1.0.0 (Open Data Commons Attribution). {len(per_rec)} recordings of 8 minutes at 1 Hz,
  aggregated to 1-minute medians ({rows_total} minutes).
- Only heart rate, SpO2 and respiratory rate were recorded. Blood pressure and temperature are held at fixed normal values,
  so this tests the HR/SpO2/RR rules and the model's response to real short-term variability.

| Minutes flagged (warning or critical) | Rules + NEWS2 only | Rules + NEWS2 + model |
|---|---|---|
| Share of minutes | {flagged_rules / rows_total:.1%} | {flagged_model / rows_total:.1%} |
"""


def eicu_section(model) -> str:
    """eICU demo: 5-minute vitals from many hospitals, evaluated with hospital-level splits."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    meta = load_eicu_meta()
    all_rows = load_eicu_rows()
    per_row = 5 / 60  # hours per 5-minute row
    hours = crit_hours = 0.0
    crit_events = crit_events_rules = 0
    stays, y, groups, feats_24 = [], [], [], []
    first24: dict[str, list[float]] = {"news2_max": [], "prob_mean": [], "crit_frac": []}
    for stay, m in meta.items():
        rows = eicu_rows_as_dicts(all_rows[stay])
        r = run_sequence(rows, model)
        crit = [b == "critical" for b in r["bands"]]
        crit_r = [b == "critical" for b in r["bands_rules"]]
        hours += len(rows) * per_row
        crit_hours += sum(crit) * per_row
        crit_events += events(crit, REFRACTORY_5MIN)
        crit_events_rules += events(crit_r, REFRACTORY_5MIN)
        idx = [i for i, row in enumerate(rows) if row["t_min"] <= 1440]
        if len(idx) < 12:
            continue
        sl = slice(idx[0], idx[-1] + 1)
        part = rows[sl]
        stays.append(stay)
        y.append(int(m["died_in_hospital"]))
        groups.append(m["hospital_id"])
        first24["news2_max"].append(int(r["news2"][sl].max()))
        first24["prob_mean"].append(float(r["prob"][sl].mean()))
        first24["crit_frac"].append(float(np.mean(crit[sl])))
        arr = {k: np.array([p[k] for p in part]) for k in ("hr", "spo2", "rr", "sbp")}
        feats_24.append([*(f(arr[k]) for k in ("hr", "spo2", "rr", "sbp") for f in (np.mean, np.min, np.max)),
                         float(r["news2"][sl].max()), float(r["prob"][sl].mean())])
    days = hours / 24
    y_arr, g_arr, X = np.array(y), np.array(groups), np.array(feats_24)

    # Hospital-held-out: a simple model trained on real data from some hospitals, tested on unseen hospitals.
    folds = []
    for train, test in GroupKFold(n_splits=5).split(X, y_arr, g_arr):
        clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced"))
        clf.fit(X[train], y_arr[train])
        p = clf.predict_proba(X[test])[:, 1]
        folds.append({"hospitals": len(set(g_arr[test])), "stays": len(test), "deaths": int(y_arr[test].sum()),
                      "real_model": auc(y_arr[test], p),
                      "news2": auc(y_arr[test], X[test][:, -2]),
                      "synthetic_model": auc(y_arr[test], X[test][:, -1])})

    def fold_row(name: str, key: str) -> str:
        vals = [f[key] for f in folds]
        return f"| {name} | " + " | ".join(f"{v:.3f}" for v in vals) + f" | **{np.mean(vals):.3f} ± {np.std(vals):.3f}** |"

    # Breakdown by hospital characteristics (pooled first-24 h scores).
    def breakdown(field: str) -> str:
        out = []
        values = sorted({meta[s][field] for s in stays}, key=str)
        for val in values:
            sel = [i for i, s in enumerate(stays) if meta[s][field] == val]
            ys = [y[i] for i in sel]
            deaths = sum(ys)
            label = {True: "teaching", False: "non-teaching"}.get(val, val) if field == "hospital_teaching" else val
            if deaths >= 10 and deaths < len(ys):
                out.append(f"| {label} | {len(sel)} | {deaths} | {auc(ys, [first24['news2_max'][i] for i in sel]):.3f} | "
                           f"{auc(ys, [first24['prob_mean'][i] for i in sel]):.3f} |")
            else:
                out.append(f"| {label} | {len(sel)} | {deaths} | too few deaths | too few deaths |")
        return "\n".join(out)

    n_hosp = len({m["hospital_id"] for m in meta.values()})
    temp_stays = sum(m["temp_measured"] for m in meta.values())
    return f"""## eICU Collaborative Research Database Demo (real ICU patients, many hospitals)

- Source: PhysioNet `eicu-crd-demo` v2.0.1 (Open Data Commons ODbL): tables `patient`, `hospital`,
  `vitalPeriodic` (5-minute medians) and `vitalAperiodic` (cuff blood pressure).
- Used: {len(meta)} ICU stays from {n_hosp} hospitals that had heart rate, SpO2, breathing rate and blood pressure for at
  least an hour ({sum(m['died_in_hospital'] for m in meta.values())} patients died in hospital), {hours:,.0f} patient-hours
  ({days:.0f} patient-days) at 5-minute resolution.
- Blood pressure: arterial line when present, otherwise the latest cuff reading within 4 h.
- Temperature was charted in these tables for only {temp_stays} stays; elsewhere it is held at 36.9 C, so fever rules
  cannot fire for those patients and NEWS2 misses its temperature points.

### Alert burden at 5-minute resolution
| Metric | Rules + NEWS2 only | Rules + NEWS2 + model |
|---|---|---|
| Critical alert events per patient-day (1 h refractory) | {crit_events_rules / days:.2f} | {crit_events / days:.2f} |
| Time spent in critical band | - | {crit_hours / hours:.1%} |

### First 24 h of the stay: does the score separate patients who later died? (all {len(stays)} stays pooled)
| Signal | AUROC |
|---|---|
| Max NEWS2 | {auc(y, first24['news2_max']):.3f} |
| Mean model probability (synthetic-trained model) | {auc(y, first24['prob_mean']):.3f} |
| Share of time in critical band | {auc(y, first24['crit_frac']):.3f} |

### Hospital-held-out test (train on some hospitals, test on hospitals never seen)
Stays were split into 5 folds **by hospital** (GroupKFold), so no hospital appears in both training and test data.
A logistic regression was trained on first-24 h summaries (mean/min/max of HR, SpO2, RR, systolic BP, plus max NEWS2
and the mean synthetic-model probability) from the training hospitals, and scored on the held-out hospitals.

| Signal | Fold 1 | Fold 2 | Fold 3 | Fold 4 | Fold 5 | Mean ± SD |
|---|---|---|---|---|---|---|
| Held-out hospitals / stays / deaths | {' | '.join(f"{f['hospitals']} / {f['stays']} / {f['deaths']}" for f in folds)} | |
{fold_row('Real-data model (trained on other hospitals)', 'real_model')}
{fold_row('Max NEWS2 (no training)', 'news2')}
{fold_row('Synthetic-trained model (no retraining)', 'synthetic_model')}

The real-data model is an evaluation experiment only; the live app still uses the rules, NEWS2 and the
synthetic-trained model.

### By hospital characteristics (pooled first-24 h scores)
| Region | Stays | Deaths | NEWS2 AUROC | Model AUROC |
|---|---|---|---|---|
{breakdown('hospital_region')}

| Teaching status | Stays | Deaths | NEWS2 AUROC | Model AUROC |
|---|---|---|---|---|
{breakdown('hospital_teaching')}
"""


def main() -> None:
    model = load_model()
    have = available()
    parts = [f"""# Real-data evaluation

Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by `backend/app/ml/eval_real.py`.

**What this does and does not show.** The deterioration model is trained on *synthetic* episodes
(see `model_report.md`), because no open dataset has bedside-labelled "deterioration started here" markers.
This report runs the unchanged system on *real* recorded vital signs. It shows alert burden and whether the
scores separate patients with worse outcomes. It is not a clinical validation.
"""]
    if have["mimic"]:
        parts.append(mimic_section(model))
    if have["eicu"]:
        parts.append(eicu_section(model))
    if have["bidmc"]:
        parts.append(bidmc_section(model))
    parts.append("""## Known gaps
- MIMIC vitals are charted about hourly and eICU vitals every 5 minutes, while the model was trained on one reading
  per minute. Deltas and z-scores therefore have a different scale, which mainly affects the model, not the rules.
- NEWS2 here omits supplemental oxygen and consciousness level, which are not measured by a wearable.
- The datasets are small, so results are indicative only. A real deployment would need validation on a large,
  representative cohort and clinical review of thresholds.
""")
    out = PROJECT_DIR / "docs" / "real_data_report.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    print("\n".join(parts))


if __name__ == "__main__":
    main()
