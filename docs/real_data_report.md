# Real-data evaluation

Generated 2026-11-13 08:19 UTC by `backend/app/ml/eval_real.py`.

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

## BIDMC PPG and Respiration Dataset (real ICU recordings)

- Source: PhysioNet `bidmc` v1.0.0 (Open Data Commons Attribution). 53 recordings of 8 minutes at 1 Hz,
  aggregated to 1-minute medians (473 minutes).
- Only heart rate, SpO2 and respiratory rate were recorded. Blood pressure and temperature are held at fixed normal values,
  so this tests the HR/SpO2/RR rules and the model's response to real short-term variability.

| Minutes flagged (warning or critical) | Rules + NEWS2 only | Rules + NEWS2 + model |
|---|---|---|
| Share of minutes | 40.4% | 51.2% |

## Known gaps
- MIMIC vitals are charted about hourly, while the model was trained on one reading per minute. Deltas and
  z-scores therefore have a different scale, which mainly affects the model, not the rules.
- NEWS2 here omits supplemental oxygen and consciousness level, which are not measured by a wearable.
- The datasets are small, so results are indicative only. A real deployment would need validation on a large,
  representative cohort and clinical review of thresholds.
