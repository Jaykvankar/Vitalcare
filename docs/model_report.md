# Risk model report

Generated 2026-11-13 07:54 UTC by `backend/app/ml/train.py`.

## Setup
- Model: scikit-learn `HistGradientBoostingClassifier` (class-balanced), threshold 0.6.
- Features (18): hr, spo2, sbp, dbp, temp, rr, d_hr, d_spo2, d_sbp, d_dbp, d_temp, d_rr, z_hr, z_spo2, z_sbp, z_dbp, z_temp, z_rr.
- Data: synthetic, one reading per minute. 160 training patients and 40 **different** test patients, one day each
  (split by patient, so no leakage). Episodes: hypoxia, tachycardia, hypotension, fever (label 1 once severity >= 30%),
  plus harmless "activity" heart-rate rises (label 0).
- Test rows: 57600, positive rate 0.122.

## Per-reading metrics (model alone)
| AUC | Precision | Recall | F1 |
|---|---|---|---|
| 0.995 | 0.931 | 0.926 | 0.929 |

Confusion matrix (rows = truth 0/1, columns = predicted 0/1):

| | pred 0 | pred 1 |
|---|---|---|
| true 0 | 50089 | 484 |
| true 1 | 517 | 6510 |

## Whole system on test patients (what clinicians experience)
An alarm is any non-normal band. "Rules only" = clinical thresholds + NEWS2; "Rules + model" adds the classifier.
False alarms are alarm events outside deterioration episodes, counted with a 10-minute refractory
window (the app keeps one open alert per reason code, so flicker does not create new alerts).

| System | Episodes | Episode recall | Median minutes to first alarm | False alarms / patient-day (any) | False critical / patient-day |
|---|---|---|---|---|---|
| Rules only | 93 | 0.978 | 12.0 | 7.58 | 0.07 |
| Rules + model | 93 | 1.000 | 7.0 | 8.18 | 0.07 |

## Limitations
Synthetic data only; the numbers show the pipeline works, not clinical validity. A real deployment needs validation on
real monitored patients (for example PhysioNet datasets) and clinical review of thresholds.

## Integrity
`model.joblib` SHA-512 (pinned in `model_hash.py`, checked before loading):
`cbe4f406e67400fb5066dccf28fb35822bd787035efe7750b8ac2cf3abda8ed9755c16a6df2b5dba5a71353e4e29e6ae0368ff999e07d8c9ea7e012f4d3c2851`
