# SecureRPM: AI-based Secure Remote Patient Monitoring

Simulated wearables send vital signs to a server. Each reading is **sealed with Diffie–Hellman + AES-256-GCM** and **signed with RSA-3072 (sign-the-digest)**.

The server then:
- verifies and decrypts each reading,
- scores it with **clinical rules, NEWS2 and a gradient-boosting model**,
- stores it **encrypted under a per-patient AES-256 key** (envelope encryption),
- records every access in a **SHA-512 hash-chained audit ledger with ECDSA-signed checkpoints**.

Clinicians see a risk-sorted worklist, charts and alerts. Patients see their own data and control consent.

> Educational project, not a certified medical device. All data is synthetic.

## Quick start (Windows, from the project folder)

```bash
python -m venv .venv
```
```bash
.venv\Scripts\python -m pip install -r backend\requirements.txt
```
```bash
.venv\Scripts\python scripts\init_env.py
```
```bash
.venv\Scripts\python scripts\gen_dev_cert.py
```
```bash
cd backend && ..\.venv\Scripts\python -m app.seed && cd ..
```
```bash
cd frontend && npm install && npm run build && cd ..
```
```bash
.venv\Scripts\python run_server.py
```

Open **https://localhost:8443**. The certificate is self-signed. Either trust `certs/dev-cert.pem` in Windows (Current User → Trusted Root Certification Authorities), or use the localhost-only HTTP mode at http://localhost:8000:

```bash
.venv\Scripts\python run_server.py --http
```

Seeded accounts and passwords are in `seed_credentials.txt`.
- Clinicians and the admin need a **TOTP code (SHA-512)**. Add the secret to Aegis, 2FAS or FreeOTP with algorithm SHA512, or print the current code:

```bash
.venv\Scripts\python scripts\totp_code.py dr.mehta
```

Demo flow:
1. Admin → **Simulator** → *Start all*, then inject `hypoxia` for a patient.
2. Sign in as `dr.mehta` and watch the worklist reorder. Open the patient and acknowledge alerts.
3. Sign in as a patient, view the data and toggle consent.
4. Admin → **Audit log** → *Verify integrity*.

## Tests and tools

```bash
cd backend && ..\.venv\Scripts\python -m pytest -q
```
Covers:
- **Crypto:** AES-GCM round trips, tamper and AAD swap, DH safe-prime check, sealing, RSA and ECDSA, PBKDF2, master-key rotation, model hash pin.
- **Ingest:** bad signature, modified ciphertext, replay, stale timestamp, hypoxia → critical alert.
- **Access control:** RBAC, consent, MFA, lockout, CSRF.
- **Audit:** tampering detected, and a recomputed chain is caught by the signed checkpoint.

| Script | What it does |
|---|---|
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
