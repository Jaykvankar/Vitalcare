# Vitalcare: AI-based Secure Remote Patient Monitoring

Simulated wearables send vital signs to a server. Each reading is **sealed with Diffie–Hellman + AES-256-GCM** and **signed with RSA-3072 (sign-the-digest)**.

The server then:
- verifies and decrypts each reading,
- scores it with **clinical rules, NEWS2 and a gradient-boosting model**,
- stores it **encrypted under a per-patient AES-256 key** (envelope encryption),
- records every access in a **SHA-512 hash-chained audit ledger with ECDSA-signed checkpoints**.

Clinicians see a risk-sorted worklist, charts and alerts. Patients see their own data and control consent.

> Educational project, not a certified medical device. Patients and names are fictional. Vital signs are either
> synthetic or **replayed from real, de-identified ICU recordings** (PhysioNet eICU demo, MIMIC-III demo and BIDMC; see below).

## Start here

| You want to | Open |
|---|---|
| See how the whole system works (interactive diagram, step-throughs) | [docs/architecture.html](docs/architecture.html) in any browser |
| Run the working demo | the command below |
| Set it up at a hospital and connect real devices | [docs/HANDOFF.md](docs/HANDOFF.md) |
| Use it day to day | [docs/user_guide.md](docs/user_guide.md) |
| Answer viva questions | [docs/viva_defense.md](docs/viva_defense.md) |

## Run the demo (Windows, from the project folder)

First time only, create the Python environment:

```bash
python -m venv .venv
```
```bash
.venv\Scripts\python -m pip install -r backend\requirements.txt
```

Then one command does the rest:
1. creates the keys and the certificate,
2. builds the web app (needs Node.js 20+),
3. seeds four patients with 24 h of encrypted history,
4. starts the server at **http://localhost:8000**, with every patient's monitor streaming.

```bash
.venv\Scripts\python demo.py
```

* With the real datasets downloaded (below), two demo patients replay **real eICU ICU stays from two different hospitals**, one replays a MIMIC-III stay, and one is synthetic, so you can inject a deterioration from Admin → **Data sources**.
* Accounts and passwords are in `seed_credentials.txt`. Staff also need a 6-digit code:

```bash
.venv\Scripts\python scripts\totp_code.py dr.mehta
```

* `demo.py --https` serves https://localhost:8443 with the self-signed certificate (trust `certs/dev-cert.pem` in Windows first).
* `demo.py --reset` backs up the demo data and seeds it again.

Five-minute walkthrough:
1. **dr.mehta:** the worklist is ranked by urgency. Open the top patient to see the AI explanation, trends and alerts, then acknowledge an alert.
2. **admin:** switch a monitor to another real ICU stay under **Data sources**, onboard staff under **Bulk import**, and check the **Privacy ledger**.
3. **p.iyer:** sees only her own data, can pause sharing and can download her data.

Running pieces by hand instead: `scripts/init_env.py`, `scripts/gen_dev_cert.py`, `python -m app.seed` (in `backend/`), `npm run build` (in `frontend/`), then `run_server.py` (HTTPS) or `run_server.py --http`.

## Real data (optional, about 100 MB, all open access)

The live model is trained on synthetic episodes, because no open dataset marks *when* deterioration started.
Real recordings are used two ways: to **evaluate** the system and to **replay** real patients through a simulated device.

Download into `data/real/` (git-ignored, no login needed):
- **eICU Collaborative Research Database Demo** (ODbL): `patient.csv.gz`, `hospital.csv.gz`, `vitalPeriodic.csv.gz`, `vitalAperiodic.csv.gz` from `https://physionet.org/files/eicu-crd-demo/2.0.1/`, saved to `data/real/eicu/` (about 22 MB).
- **MIMIC-III Clinical Database Demo** (ODbL): `CHARTEVENTS.csv`, `D_ITEMS.csv`, `ADMISSIONS.csv`, `ICUSTAYS.csv`, `PATIENTS.csv` from `https://physionet.org/files/mimiciii-demo/1.4/`, saved to `data/real/mimic/`.
- **BIDMC** (ODC-BY): `bidmc_01_Numerics.csv` … `bidmc_53_Numerics.csv` from `https://physionet.org/files/bidmc/1.0.0/bidmc_csv/`, saved to `data/real/bidmc/`.

Then run, from `backend/` (about 3 minutes):

```bash
..\.venv\Scripts\python -m app.ml.eval_real
```

This writes [docs/real_data_report.md](docs/real_data_report.md). Highlights:
- **eICU, 2,032 stays from 184 hospitals, first 24 h → later in-hospital death (AUROC):**
  - NEWS2: 0.734
  - our synthetic-trained model: 0.687
  - a model trained on real data from *other* hospitals: **0.760 ± 0.05** on hospitals it never saw
- **Main next step:** retraining on real data and validating it at each new hospital.
- **MIMIC-III, 100 stays:** the model 0.62 vs NEWS2 0.53. That is too small a set to rely on.
- **Not clinically useful yet:** none of these is strong enough for clinical use, and eICU shows about 3.8 critical alerts per patient-day at 5-minute resolution.

When the data is present, seeding makes Meera Iyer's and Ananya Das's monitors replay real eICU stays (two different hospitals) and Imran Khan's a MIMIC-III stay. Admin → **Data sources** can switch any monitor to another eICU or MIMIC stay or a BIDMC record.

## Pairing a device

Admins, and clinicians on the patient's care team, connect devices with a guided wizard (patient record → Devices → **Connect device**, or Admin → **Devices & pairing**) that shows a QR code and a one-time code. The in-app **Device guide** lists which devices work and how to fix common problems.

How pairing works underneath:
1. A one-time code is issued (10 min, `XXXX-XXXX-XXXX`).
2. The device generates its own RSA-3072 key and proves it knows the code with HMAC-SHA-512. The code never crosses the network.
3. Five wrong proofs burn the code; a used code cannot be reused.
4. Devices can be revoked, and ingest rejects them immediately.

Pairing from the command line:

```bash
.venv\Scripts\python scripts\device_client.py pair --pairing-id ID --code ABCD-EFGH-JKLM
```
```bash
.venv\Scripts\python scripts\device_client.py stream --source synthetic
```

A real sensor connects through a small adapter program that prints one JSON line per reading:

```bash
python scripts/sensor_example.py | python scripts/device_client.py stream --source stdin
```

Hospital setup, device choices (Bluetooth services, gateways) and operations: [docs/HANDOFF.md](docs/HANDOFF.md).

## Onboarding a real hospital

1. Run `python scripts/init_env.py`, set up TLS certs, then run `python scripts/create_admin.py --username it.admin --name "IT Admin"`. This creates no demo data.
2. Admin → **Bulk import**: upload one CSV of staff and patients with care teams. Check the preview, then create. Everyone gets a temporary password and must change it at first sign-in.
3. Clinicians import past vital signs per patient (patient record → **Import past readings**) and pair devices with one-time codes.

See [docs/user_guide.md](docs/user_guide.md), [docs/architecture.md](docs/architecture.md) and [docs/threat_model.md](docs/threat_model.md).

## Tests and tools

```bash
cd backend && ..\.venv\Scripts\python -m pytest -q --cov
```
```bash
cd backend && ..\.venv\Scripts
uff check . ../scripts && ..\.venv\Scripts\mypy app
```
```bash
cd frontend && npm run lint && npm run typecheck && npm test
```
```bash
cd frontend && npm run e2e
```

`npm run e2e` starts a throw-away seeded server on port 8010 and drives it with your installed Chrome (`RPM_E2E_CHANNEL=msedge` to use Edge). CI (`.github/workflows/ci.yml`) runs all of these on every push. Install dev tools with `pip install -r backend/requirements-dev.txt`, plus the optional git hooks in `.pre-commit-config.yaml`.
Covers:
- **Crypto:** AES-GCM round trips, tamper and AAD swap, DH safe-prime check, sealing, RSA and ECDSA, PBKDF2, master-key rotation, model hash pin.
- **Ingest:** bad signature, modified ciphertext, replay, stale timestamp, hypoxia → critical alert.
- **Access control:** RBAC, consent, MFA, lockout, CSRF.
- **Audit:** tampering detected, and a recomputed chain is caught by the signed checkpoint.

| Script | What it does |
|---|---|
| `scripts/device_client.py` | Stand-alone device: pair with a code, then stream sealed + signed readings |
| `scripts/crypto_demo.py` | Prints every crypto step (DH values, AES ciphertext, digest, RSA/ECDSA signatures) for the viva |
| `scripts/verify_audit.py` | Recomputes the audit chain and checks checkpoint signatures |
| `scripts/rotate_master_key.py` | Re-wraps patient keys, TOTP secrets and server keys under a new master key (server stopped) |
| `python -m app.ml.train` (in `backend/`) | Retrains the model, pins its SHA-512, writes `docs/model_report.md` |

## Algorithm map

Every technique comes from a course family. Primitives come from the `cryptography` library; the protocols are ours.

| Where | Algorithm | Course family | Code |
|---|---|---|---|
| Reading payload (device → server) | Ephemeral **Diffie–Hellman** ffdhe3072 (RFC 7919, g^ab mod p) → HKDF-SHA-512 → **AES-256-GCM** | Diffie–Hellman, AES | `security/sealing.py` |
| Packet authenticity | **RSA-3072-PSS** over **SHA-512** digest: *sign-the-digest*, *direct digital signature* | RSA digital signature | `security/signatures.py`, `readings/ingest.py` |
| Readings, PII, notes at rest | **AES-256-GCM** under a per-patient key; AAD binds patient, device, seq, timestamp | AES | `security/crypto.py` |
| Key wrapping (envelope) | Patient key wrapped with **AES-256-GCM** under a versioned master key | AES | `security/crypto.py` |
| Audit ledger | **SHA-512** hash chain plus **ECDSA P-384** signed checkpoints | Hash, DSA (elliptic-curve form) | `security/audit.py` |
| Passwords | **PBKDF2-HMAC-SHA-512**, 210,000 iterations, 16-byte salt | Hash | `security/hashing.py` |
| MFA | TOTP with **HMAC-SHA-512** | Hash | `security/auth.py` |
| Sessions | Random token in cookie; DB stores only its **SHA-512** | Hash | `security/auth.py` |
| Model integrity | **SHA-512** of `model.joblib` pinned and checked before loading | Hash | `ml/infer.py` |
| Transport | **TLS 1.3** with an **RSA-3072** cert signed over SHA-512 (negotiates `TLS_AES_256_GCM_SHA384`) | RSA, AES, SHA-2 | `scripts/gen_dev_cert.py` |

All of these are NIST/IETF standards:
- AES-GCM: FIPS 197 / SP 800-38D
- SHA-512: FIPS 180-4
- HMAC: FIPS 198-1
- HKDF: RFC 5869
- PBKDF2: SP 800-132
- RSA-PSS: FIPS 186-5
- FFDH: RFC 7919 / SP 800-56A
- ECDSA: FIPS 186-5
- TOTP: RFC 6238
- TLS 1.3: RFC 8446

## Security model

The API decrypts a patient's data only after all of these pass:
1. Authentication: session, plus TOTP for staff.
2. Role check.
3. Assignment check, for clinicians.
4. Active consent.

Unauthorized and non-existent patients both return **404**, so IDs cannot be probed. Admins manage accounts but **cannot decrypt** vitals or personal details.

| Threat | Defence |
|---|---|
| Eavesdropping on the network | TLS 1.3, plus the inner DH + AES-GCM seal (data stays protected even if TLS ends at a proxy) |
| Forged or modified readings | RSA signature over the whole packet; the GCM tag |
| Replayed readings | Strictly increasing sequence (atomic compare-and-set), ±60 s timestamp window |
| Stolen database or backup | Readings, PII, notes and TOTP secrets are AES-GCM ciphertext; keys are wrapped by a master key held only in the environment |
| Ciphertext moved between rows | AES-GCM associated data binds patient, device, seq and timestamp |
| Compromised device key on server | Server stores device **public** keys only; simulator keys are in a separate encrypted keystore |
| Password guessing | PBKDF2 (210k iterations), rate limit, 5-try lockout, TOTP for staff, constant-time unknown-user path |
| CSRF / clickjacking / XSS | SameSite=Strict httpOnly cookie, required `X-RPM-Request` header and Origin check, CSP, `X-Frame-Options: DENY` |
| Insider editing the audit log | DB triggers block UPDATE/DELETE; a hash chain detects edits; ECDSA checkpoints detect full-chain rewrites |
| Malicious model file | Pinned SHA-512 checked before unpickling |
| Data leakage via logs | Only reason codes (`SPO2_LOW` …) are stored or logged in clear, never vital values |

Known limits:
- The model is trained on synthetic data. Real data is only used to evaluate it (indicative, 100 stays), so it is not clinically validated.
- No real wearable hardware: devices are simulated. The pairing protocol and `device_client.py` are what a real device would implement.
- MIMIC vitals are hourly while the model expects minute-level readings, and NEWS2 lacks the oxygen-therapy and consciousness inputs.
- The master key lives in an environment variable. Production would use an HSM or KMS.
- Rate limits and the TOTP replay guard are in-memory (single process).
- Polling read events are logged once per minute per viewer.
- DTLS/CoAP devices are out of scope.

## AI risk engine

- **Rules:** clinical thresholds (SpO₂ < 92, HR > 120 or < 45, SBP < 90 or > 180, T ≥ 38.5 °C, RR > 24 …) and **NEWS2** always win.
- **Model:** `HistGradientBoostingClassifier` on 18 features: vitals, deltas, and z-scores against the patient's own encrypted rolling baseline. The model can raise the band, never lower it.
- **Results** (see [docs/model_report.md](docs/model_report.md); synthetic data, test patients separate from training patients):
  - 100% of deterioration episodes detected, vs 97.8% for rules only.
  - Median first alarm 7 min into an episode, vs 12 min for rules only.
  - About 0.07 false critical alarms per patient-day.

## Layout

```
backend/app/security/   aead, sealing (DH), signatures (RSA/ECDSA), crypto (envelope), hashing, audit, auth, rbac, server_keys
backend/app/readings/   ingest pipeline
backend/app/ml/         rules + NEWS2, features, synthetic data, train, infer, pinned model
backend/app/api/        auth, patients, admin, ingest routes
backend/app/simulator.py  device keystore + live simulator
frontend/src/           React app (login + TOTP, patient, clinician, admin pages)
scripts/                env, certs, TOTP helper, audit verify, key rotation, crypto demo
```

## Docker (optional, PostgreSQL)

```bash
docker compose up --build
```
This runs the API plus PostgreSQL over HTTPS on 8443. It reads secrets from `.env`, and the certs and seed must already exist.
