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
| Present it (click-by-click script, slides) | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md), [docs/presentation.html](docs/presentation.html) |

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
* Accounts and passwords are in `seed_credentials.txt`. In demo mode, **Try a role** fills the username and shows the password. Staff (dr.mehta, dr.rao, admin) also need a 6-digit code; get it in a second terminal and type it in:

```bash
.venv\Scripts\python scripts\totp_code.py dr.mehta
```

* `demo.py --https` serves https://localhost:8443 with the self-signed certificate (trust `certs/dev-cert.pem` in Windows first).
* `demo.py --reset` backs up the demo data and seeds it again.

Five-minute walkthrough:
1. **dr.mehta:** the worklist is ranked by urgency. Open the top patient to see the AI explanation, trends and alerts, then acknowledge an alert.
2. **admin:** open **Security inspector** to see the cryptography applied to the latest real packet and run the replay / tamper / forged-key attacks (all blocked); switch a monitor to another real ICU stay under **Data sources**, onboard staff under **Bulk import**, and check the **Privacy ledger**.
3. **p.iyer:** sees only her own data, can pause sharing and can download her data.

Running pieces by hand instead: `scripts/init_env.py`, `scripts/gen_dev_cert.py`, `python -m app.seed` (in `backend/`), `npm run build` (in `frontend/`), then `run_server.py` (HTTPS) or `run_server.py --http`.

## Real data (optional, about 100 MB, all open access)

Real recordings are used three ways: to **train** the live model (eICU), to **evaluate** it (eICU hospitals it never
saw, and MIMIC-III as a separate hospital system), and to **replay** real patients through a simulated device.

Download into `data/real/` (git-ignored, no login needed):
- **eICU Collaborative Research Database Demo** (ODbL): `patient.csv.gz`, `hospital.csv.gz`, `vitalPeriodic.csv.gz`, `vitalAperiodic.csv.gz` from `https://physionet.org/files/eicu-crd-demo/2.0.1/`, saved to `data/real/eicu/` (about 22 MB).
- **MIMIC-III Clinical Database Demo** (ODbL): `CHARTEVENTS.csv`, `D_ITEMS.csv`, `ADMISSIONS.csv`, `ICUSTAYS.csv`, `PATIENTS.csv` from `https://physionet.org/files/mimiciii-demo/1.4/`, saved to `data/real/mimic/`.
- **BIDMC** (ODC-BY): `bidmc_01_Numerics.csv` … `bidmc_53_Numerics.csv` from `https://physionet.org/files/bidmc/1.0.0/bidmc_csv/`, saved to `data/real/bidmc/`.

Then run, from `backend/` (about 3 minutes):

```bash
..\.venv\Scripts\python -m app.ml.eval_real
```

This writes [docs/real_data_report.md](docs/real_data_report.md) (rules, NEWS2 and the synthetic baseline on real data).
To train the live model on real data (about 5 minutes; without `--save` it only evaluates):

```bash
..\.venv\Scripts\python -m app.ml.train_real --save
```

This writes [docs/model_report.md](docs/model_report.md). Target: death in the ICU within the next 24 h, per reading.
AUROC per reading:

| Test | Real-data model | NEWS2 | Previous synthetic model |
|---|---|---|---|
| eICU, 184 hospitals, each fold tested on hospitals it never saw | **0.718 ± 0.031** | 0.698 | 0.665 |
| MIMIC-III (a different hospital system, never used for training) | 0.705 | **0.742** | 0.659 |

The real-data model beats the synthetic one everywhere and NEWS2 on unseen eICU hospitals, but not on MIMIC: it is
decision support on top of the rules and NEWS2, never a replacement. The demo datasets are small (about 100 ICU deaths);
the full credentialed eICU / MIMIC-IV would give a stronger model.

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

Real Bluetooth devices (any that implement the standard Heart Rate, Pulse Oximeter, Blood Pressure or Health
Thermometer service) are read by the gateway program and piped into the device client:

```bash
pip install -r scripts/requirements-ble.txt
```
```bash
python scripts/ble_gateway.py | python scripts/device_client.py stream --source stdin
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
| `scripts/rotate_master_key.py` | Re-wraps patient keys, TOTP secrets and server keys under a new master key (server stopped); works with `.env` or the sealed key file |
| `scripts/seal_master_key.py` | Moves the master keys out of `.env` into `secrets/master_keys.sealed` (AES-256-GCM under PBKDF2-HMAC-SHA-512 of a passphrase typed at start-up) |
| `scripts/ble_gateway.py` | Reads standard Bluetooth health devices and prints JSON lines for `device_client.py` |
| `python -m app.ml.train_real --save` (in `backend/`) | Trains the live model on eICU, tests it on unseen hospitals and on MIMIC, pins its SHA-512 and threshold, writes `docs/model_report.md` |
| `python -m app.ml.train` (in `backend/`) | Rebuilds the synthetic baseline model (replaces the shipped one) |

## Algorithm map

Every technique comes from a course family. Primitives come from the `cryptography` library; the protocols are ours.

| Where | Algorithm | Course family | Code |
|---|---|---|---|
| Reading payload (device → server) | Ephemeral **Diffie–Hellman** ffdhe3072 (RFC 7919, g^ab mod p) → HKDF-SHA-512 → **AES-256-GCM** | Diffie–Hellman, AES | `security/sealing.py` |
| Packet authenticity | **RSA-3072-PSS** over **SHA-512** digest: *sign-the-digest*, *direct digital signature* | RSA digital signature | `security/signatures.py`, `readings/ingest.py` |
| Readings, PII, notes at rest | **AES-256-GCM** under a per-patient key; AAD binds patient, device, seq, timestamp | AES | `security/crypto.py` |
| Key wrapping (envelope) | Patient key wrapped with **AES-256-GCM** under a versioned master key | AES | `security/crypto.py` |
| Clinical labels at rest | Band, AI score and reasons inside **AES-256-GCM**; alert reason matched by a blind index **HMAC-SHA-512**(HKDF-SHA-512(patient key)) | AES, Hash | `security/labels.py` |
| Sealed master key (option) | **AES-256-GCM** under **PBKDF2-HMAC-SHA-512**(passphrase, 600,000 rounds) | AES, Hash | `keysource.py` |
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
| Stolen database or backup | Readings, PII, notes, TOTP secrets **and the clinical labels** (band, AI score, alert reasons) are AES-GCM ciphertext; alert reasons are matched through an HMAC-SHA-512 blind index; keys are wrapped by a master key that is never in the database (sealed file or HSM/KMS option) |
| Ciphertext moved between rows | AES-GCM associated data binds patient, device, seq and timestamp |
| Compromised device key on server | Server stores device **public** keys only; simulator keys are in a separate encrypted keystore |
| Password guessing | PBKDF2 (210k iterations), rate limit, 5-try lockout, TOTP for staff, constant-time unknown-user path |
| CSRF / clickjacking / XSS | SameSite=Strict httpOnly cookie, required `X-RPM-Request` header and Origin check, CSP, `X-Frame-Options: DENY` |
| Insider editing the audit log | DB triggers block UPDATE/DELETE; a hash chain detects edits; ECDSA checkpoints detect full-chain rewrites |
| Malicious model file | Pinned SHA-512 checked before unpickling |
| Data leakage via logs | No vital values, bands or reason codes are written to logs or the audit ledger |

Known limits:
- The model is trained on the small open eICU demo (about 100 ICU deaths) and is not clinically validated; NEWS2 is still better on MIMIC.
- The Bluetooth gateway follows the official GATT specifications and its parsers are tested byte-for-byte, but it has not been run against physical devices here.
- NEWS2 lacks the oxygen-therapy and consciousness inputs, which wearables do not measure.
- The master key defaults to `.env` for the demo. `scripts/seal_master_key.py` moves it into a passphrase-sealed file, and `RPM_MASTER_KEY_SOURCE=command` lets an HSM or cloud KMS supply it; no HSM hardware was available to test with.
- Which patients exist and how many open alerts they have is still visible as row counts (not their content).
- Polling read events are logged once per minute per viewer.
- DTLS/CoAP devices are out of scope.

## AI risk engine

- **Partial readings:** a device may send any subset of the six vitals (blood pressure as a pair). Missing ones show as *Not measured*; rules and NEWS2 use what is present, and the model scores only complete readings.
- **Rules:** clinical thresholds (SpO₂ < 92, HR > 120 or < 45, SBP < 90 or > 180, T ≥ 38.5 °C, RR > 24 …) and **NEWS2** always win.
- **Model:** `HistGradientBoostingClassifier` on 18 features: vitals, deltas, and z-scores against the patient's own encrypted rolling baseline, **trained on real eICU ICU patients** (death in the ICU within 24 h). The model can raise the band, never lower it. Its alert threshold (95% specificity on held-out hospitals) is pinned with its SHA-512.
- **Results:** see the table under *Real data* and [docs/model_report.md](docs/model_report.md). The synthetic baseline (`train.py`) is kept for comparison.

## Layout

```
backend/app/security/   aead, sealing (DH), signatures (RSA/ECDSA), crypto (envelope), hashing, audit, auth, rbac, server_keys
backend/app/readings/   ingest pipeline
backend/app/ml/         rules + NEWS2, features, train_real (eICU), synthetic baseline, infer, pinned model
backend/app/api/        auth, patients, admin, ingest routes
backend/app/simulator.py  device keystore + live simulator
frontend/src/           React app (login + TOTP, patient, clinician, admin pages)
scripts/                env, certs, TOTP helper, audit verify, key sealing and rotation, Bluetooth gateway, crypto demo
```

## Docker (optional, PostgreSQL)

```bash
docker compose up --build
```
This runs the API plus PostgreSQL over HTTPS on 8443. It reads secrets from `.env`, and the certs and seed must already exist.
