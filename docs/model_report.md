# Risk model report

Generated 2026-11-14 05:33 UTC by `backend/app/ml/train_real.py`.

## What the shipped model is
- **Trained on real ICU patients**: eICU Collaborative Research Database demo, 2048 ICU stays from
  184 US hospitals, 405293 readings at 15-minute spacing (taken from 5-minute data).
- **Target**: for each reading, "the patient dies in the ICU within the next 24 hours" (6704 positive readings,
  1.65%).
- **Model**: scikit-learn `HistGradientBoostingClassifier` (class-balanced) on the same 18 per-reading features the live
  app computes: hr, spo2, sbp, dbp, temp, rr, d_hr, d_spo2, d_sbp, d_dbp, d_temp, d_rr, z_hr, z_spo2, z_sbp, z_dbp, z_temp, z_rr.
- **Alert threshold**: 0.6626, chosen on out-of-fold predictions for 95% specificity and pinned
  in `model_hash.py` with the model's SHA-512. The model can raise a band to *warning* (ML_RISK); it never lowers a rule.

## Held-out hospitals (eICU, 5-fold GroupKFold by hospital)
Every score below is for hospitals the model never saw while training. AUROC per reading (0.5 = chance, 1 = perfect).

| Fold | Hospitals | Readings | Positive | Real-data model | NEWS2 | Previous synthetic model |
|---|---|---|---|---|---|---|
| 1 | 37 | 81076 | 1435 | 0.711 | 0.690 | 0.665 |
| 2 | 37 | 81048 | 811 | 0.693 | 0.557 | 0.583 |
| 3 | 37 | 81052 | 1362 | 0.779 | 0.742 | 0.663 |
| 4 | 36 | 81009 | 1485 | 0.711 | 0.707 | 0.706 |
| 5 | 37 | 81108 | 1611 | 0.697 | 0.730 | 0.677 |
| **All** | 184 | 405293 | 6704 | **0.718 ± 0.031** | 0.698 | 0.665 |

At the pinned threshold (out-of-fold): sensitivity 26.5%, specificity
95.0%, about 4.8 model warnings per patient-day for patients
who did not die (one reading every 15 minutes; the app keeps one open alert per reason, so these merge into far fewer alerts).

## External test: MIMIC-III demo (different hospital system, never used for training)
128 ICU stays, 12839 hourly readings, 462 positive.

| Signal | AUROC |
|---|---|
| Real-data model (trained on eICU only) | **0.705** |
| NEWS2 | 0.742 |
| Previous synthetic model | 0.659 |

At the pinned threshold: sensitivity 23.8%, specificity 96.4%.

## Limits
- Small demo datasets: 6704 positive eICU readings from about 100 deaths, so results carry real uncertainty
  (see the ± across folds). The full credentialed eICU / MIMIC-IV databases would give a much stronger model.
- Temperature was charted for few eICU stays; where missing it was held at 36.9 °C for training, so the model learns
  little from temperature (the clinical fever rules still apply).
- ICU patients are sicker than patients monitored at home; a home-monitoring deployment should be re-validated locally.
- Decision support only: rules and NEWS2 always run, and every alert lists its reasons.

## Previous model
The earlier synthetic-trained model is kept as `model_synthetic.joblib` for comparison only (`train.py` can rebuild it).
It is never loaded by the app.

## Integrity
`model.joblib` SHA-512 (pinned in `model_hash.py`, checked before loading):
`732ab349c1486faf888ac98483540e0713d33d8cf38bd90c2e3e2584fe9edd9f675ca9dbce020122c613cf601e2c5e010fa85790f62dd1f04cecf3b7cd0cc2a3`
