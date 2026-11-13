# Real-data evaluation

Generated 2026-11-13 09:31 UTC by `backend/app/ml/eval_real.py`.

**What this does and does not show.** The deterioration model is trained on *synthetic* episodes
(see `model_report.md`), because no open dataset has bedside-labelled "deterioration started here" markers.
This report runs the unchanged system on *real* recorded vital signs. It shows alert burden and whether the
scores separate patients with worse outcomes. It is not a clinical validation.

## MIMIC-III Clinical Database Demo (real ICU patients)

- Source: PhysioNet `mimiciii-demo` v1.4 (Open Data Commons ODbL). 100 de-identified patients.
- Used: 100 ICU stays with at least 24 hourly rows where all six vitals were charted (32 patients died in hospital),
  12,366 patient-hours (515 patient-days). Charted values were aggregated to hourly medians, forward-filled up to 4 h.
- Every hour was scored exactly as live readings are: rules + NEWS2 + model, with the per-patient rolling baseline.

### Alert burden on real ICU data
| Metric | Rules + NEWS2 only | Rules + NEWS2 + model |
|---|---|---|
| Critical alert events per patient-day (4 h refractory) | 1.00 | 1.00 |
| Hours spent in critical band | - | 37.1% |

ICU patients are sick, so a high critical share is expected. Ward patients wearing a home monitor would trigger far fewer alerts.

### Does the score separate patients who later died? (stay-level AUROC, in-hospital mortality)
| Signal | First 24 h of the stay (early warning) | Last 24 h of data |
|---|---|---|
| Max NEWS2 | 0.531 | 0.797 |
| Mean model probability | 0.615 | 0.729 |
| Share of hours in critical band (combined) | 0.592 | 0.750 |
| Share of hours in critical band (rules only) | 0.592 | - |

0.5 means no better than chance. With only 100 stays, these AUROCs carry wide uncertainty (roughly ±0.1).

## eICU Collaborative Research Database Demo (real ICU patients, many hospitals)

- Source: PhysioNet `eicu-crd-demo` v2.0.1 (Open Data Commons ODbL): tables `patient`, `hospital`,
  `vitalPeriodic` (5-minute medians) and `vitalAperiodic` (cuff blood pressure).
- Used: 2048 ICU stays from 184 hospitals that had heart rate, SpO2, breathing rate and blood pressure for at
  least an hour (178 patients died in hospital), 101,154 patient-hours
  (4215 patient-days) at 5-minute resolution.
- Blood pressure: arterial line when present, otherwise the latest cuff reading within 4 h.
- Temperature was charted in these tables for only 157 stays; elsewhere it is held at 36.9 C, so fever rules
  cannot fire for those patients and NEWS2 misses its temperature points.

### Alert burden at 5-minute resolution
| Metric | Rules + NEWS2 only | Rules + NEWS2 + model |
|---|---|---|
| Critical alert events per patient-day (1 h refractory) | 3.82 | 3.82 |
| Time spent in critical band | - | 32.3% |

### First 24 h of the stay: does the score separate patients who later died? (all 2032 stays pooled)
| Signal | AUROC |
|---|---|
| Max NEWS2 | 0.734 |
| Mean model probability (synthetic-trained model) | 0.687 |
| Share of time in critical band | 0.735 |

### Hospital-held-out test (train on some hospitals, test on hospitals never seen)
Stays were split into 5 folds **by hospital** (GroupKFold), so no hospital appears in both training and test data.
A logistic regression was trained on first-24 h summaries (mean/min/max of HR, SpO2, RR, systolic BP, plus max NEWS2
and the mean synthetic-model probability) from the training hospitals, and scored on the held-out hospitals.

| Signal | Fold 1 | Fold 2 | Fold 3 | Fold 4 | Fold 5 | Mean ± SD |
|---|---|---|---|---|---|---|
| Held-out hospitals / stays / deaths | 37 / 407 / 32 | 37 / 407 / 39 | 36 / 406 / 44 | 37 / 406 / 31 | 37 / 406 / 31 | |
| Real-data model (trained on other hospitals) | 0.685 | 0.736 | 0.829 | 0.807 | 0.742 | **0.760 ± 0.052** |
| Max NEWS2 (no training) | 0.644 | 0.718 | 0.791 | 0.790 | 0.719 | **0.732 ± 0.055** |
| Synthetic-trained model (no retraining) | 0.567 | 0.697 | 0.739 | 0.698 | 0.716 | **0.684 ± 0.060** |

The real-data model is an evaluation experiment only; the live app still uses the rules, NEWS2 and the
synthetic-trained model.

### By hospital characteristics (pooled first-24 h scores)
| Region | Stays | Deaths | NEWS2 AUROC | Model AUROC |
|---|---|---|---|---|
| Midwest | 677 | 47 | 0.766 | 0.641 |
| Northeast | 118 | 15 | 0.594 | 0.538 |
| South | 533 | 48 | 0.757 | 0.730 |
| West | 510 | 46 | 0.744 | 0.728 |
| unknown | 194 | 21 | 0.688 | 0.690 |

| Teaching status | Stays | Deaths | NEWS2 AUROC | Model AUROC |
|---|---|---|---|---|
| non-teaching | 1824 | 161 | 0.730 | 0.689 |
| teaching | 208 | 16 | 0.771 | 0.664 |

## BIDMC PPG and Respiration Dataset (real ICU recordings)

- Source: PhysioNet `bidmc` v1.0.0 (Open Data Commons Attribution). 53 recordings of 8 minutes at 1 Hz,
  aggregated to 1-minute medians (473 minutes).
- Only heart rate, SpO2 and respiratory rate were recorded. Blood pressure and temperature are held at fixed normal values,
  so this tests the HR/SpO2/RR rules and the model's response to real short-term variability.

| Minutes flagged (warning or critical) | Rules + NEWS2 only | Rules + NEWS2 + model |
|---|---|---|
| Share of minutes | 40.4% | 51.2% |

## Known gaps
- MIMIC vitals are charted about hourly and eICU vitals every 5 minutes, while the model was trained on one reading
  per minute. Deltas and z-scores therefore have a different scale, which mainly affects the model, not the rules.
- NEWS2 here omits supplemental oxygen and consciousness level, which are not measured by a wearable.
- The datasets are small, so results are indicative only. A real deployment would need validation on a large,
  representative cohort and clinical review of thresholds.
