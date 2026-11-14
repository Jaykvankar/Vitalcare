# Vitalcare handoff: running it at a hospital with real devices

This guide is for a hospital (or the team helping one) that wants to run Vitalcare for real patients:
how to set it up, how to connect actual monitoring devices, and how each kind of user works with it.

> **Status:** Vitalcare is a semester project, not a certified medical device. Use it for pilots,
> teaching and evaluation alongside normal clinical care, never as the only safety net.
> It gives decision support, never a diagnosis.

---

## 1. How it fits a hospital

```
 bedside / home                        hospital network or cloud VM                 staff & patients
┌─────────────────┐  HTTPS (443)   ┌──────────────────────────────────┐   HTTPS   ┌──────────────────┐
│ sensor ─► gateway│ ─────────────► │ Vitalcare server (one per hospital)│ ◄───────► │ web browser      │
│ (oximeter, cuff, │ sealed+signed  │  API · risk engine · audit ledger │           │ clinician/admin/ │
│  thermometer)    │ readings       │  PostgreSQL (encrypted data)      │           │ patient          │
└─────────────────┘                └──────────────────────────────────┘           └──────────────────┘
```

* **One installation per hospital.** Each hospital runs its own server with its own master key and
  database. Patient data never leaves that hospital's installation, and one hospital's administrators
  can never see another's patients. Several hospitals means several independent installations.
* **Devices talk to the server through a gateway.** Most medical sensors speak Bluetooth or USB, not
  HTTPS. A small computer next to the patient (Raspberry Pi, mini PC or a laptop) reads the sensor and
  runs the Vitalcare device client, which encrypts, signs and uploads every reading.
* **People use a web browser.** Nothing to install for clinicians or patients.

---

## 2. What the hospital needs

| Item | Minimum | Notes |
|---|---|---|
| Server | 2 vCPU, 4 GB RAM, 20 GB disk, Linux or Windows | A VM in the hospital data centre or a cloud region the hospital is allowed to use |
| Software | Python 3.11+ and Node.js 20+ (build only), **or** Docker | `docker compose` runs the app and PostgreSQL together |
| Database | PostgreSQL 14+ | SQLite works for a single-laptop demo only |
| Network name | e.g. `vitalcare.cityhospital.org` | Gateways and browsers must reach it on port 443 (or 8443) |
| TLS certificate | From the hospital's IT certificate authority or a public CA | Must match the network name; browsers must trust it |
| Secret storage | Password manager, vault or offline safe | Holds the `.env` master key; **losing it loses all patient data** |
| Backups | Daily database dump + the `.env` file stored **separately** | Test a restore before go-live |
| Per patient | A gateway + the sensors (see section 5) | One gateway can serve one patient |
| Staff phones | An authenticator app that supports **SHA-512** TOTP | Aegis, 2FAS or FreeOTP. Google and Microsoft Authenticator may ignore SHA-512 and show wrong codes |

---

## 3. Setting up the server (IT, about one hour)

### Option A: Docker (recommended)

```bash
git clone <your copy of the repository> vitalcare && cd vitalcare
python scripts/init_env.py          # creates .env with a random 256-bit master key
```

Edit `.env` and set at least:

```ini
POSTGRES_PASSWORD=<long random password>
RPM_ALLOWED_ORIGINS=https://vitalcare.cityhospital.org
RPM_SELF_URL=https://vitalcare.cityhospital.org
RPM_RETENTION_DAYS=365
```

Copy the hospital certificate (full chain) and its private key into `certs/` (mounted at `/app/certs`)
and add to `.env`:

```ini
RPM_TLS_CERT=/app/certs/fullchain.pem
RPM_TLS_KEY=/app/certs/privkey.pem
```

Then:

```bash
docker compose up -d --build
docker compose run --rm api python scripts/create_admin.py --username it.admin --name "IT Administrator"
```

### Option B: directly on the server

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd frontend && npm ci && npm run build && cd ..
python scripts/init_env.py
```

Add to `.env`:

```ini
DATABASE_URL=postgresql+psycopg://vitalcare:<password>@localhost:5432/vitalcare
RPM_ALLOWED_ORIGINS=https://vitalcare.cityhospital.org
RPM_SELF_URL=https://vitalcare.cityhospital.org
RPM_TLS_CERT=/etc/vitalcare/tls/fullchain.pem
RPM_TLS_KEY=/etc/vitalcare/tls/privkey.pem
RPM_HOST=0.0.0.0
RPM_PORT=8443
```

```bash
.venv/bin/python scripts/create_admin.py --username it.admin --name "IT Administrator"
.venv/bin/python run_server.py
```

Run it as a service so it restarts automatically (Linux example, `/etc/systemd/system/vitalcare.service`):

```ini
[Unit]
Description=Vitalcare
After=network-online.target postgresql.service

[Service]
WorkingDirectory=/opt/vitalcare
ExecStart=/opt/vitalcare/.venv/bin/python run_server.py
Restart=always
User=vitalcare

[Install]
WantedBy=multi-user.target
```

The database schema is created and upgraded automatically at start-up (Alembic). Nothing else is needed.

> The Docker image's built-in health check trusts the self-signed development certificate. With a
> CA-issued certificate, monitor `https://<name>/api/health/ready` from the hospital's monitoring system
> instead (section 7), or adjust `HEALTHCHECK` in the `Dockerfile`.

### Before go-live checklist

- [ ] `https://<name>/api/health/ready` returns `"ready": true`
- [ ] The browser shows the site as secure (no certificate warning)
- [ ] The master key is not left readable in `.env`: run `python scripts/seal_master_key.py` (passphrase typed at
      start-up) or set `RPM_MASTER_KEY_SOURCE=command` so the hospital's HSM / KMS supplies it (section 7)
- [ ] The master key (or the sealed file **and** its passphrase) is backed up in the hospital's secret store,
      **separately** from database backups
- [ ] A restore from backup has been tested on a spare machine
- [ ] The first admin has signed in, set up two-step sign-in and saved the 10 recovery codes
- [ ] `python scripts/verify_audit.py` reports `"ok": true`
- [ ] A data protection impact assessment and patient consent text are approved (see section 8)

---

## 4. Onboarding staff and patients (admin, minutes)

1. Sign in as the admin → **Bulk import** → **Download template**.
2. Fill one row per person. Patients list their clinicians in `care_team` (usernames separated by `;`):

   ```csv
   username,full_name,role,dob,phone,address,care_team
   dr.sen,Dr. Arjun Sen,clinician,,,,
   nurse.roy,Nisha Roy,clinician,,,,
   p.verma,Kavita Verma,patient,1962-08-19,+91 98000 11111,22 Ring Road Delhi,dr.sen;nurse.roy
   ```

3. Upload. Every row is checked; fix any errors shown and upload again. Nothing is created until the
   whole file is valid.
4. Select **Create accounts**, then **Download temporary passwords** immediately (shown once). Hand them
   out the way the hospital hands out other credentials.
5. Each person must choose their own password at first sign-in. Clinicians and admins also set up
   two-step sign-in and receive recovery codes.

Single people can be added under **People**; care teams can be changed under **Care teams**.

---

## 5. Connecting actual devices

### 5.1 How a device connects

```
 sensor ──(Bluetooth / USB / hospital feed)──► adapter program ──(JSON lines)──► device_client.py ──HTTPS──► Vitalcare
                                                 written per device type          built: encrypts + signs
```

* **`scripts/device_client.py` (built and tested)** handles everything security-related: pairing with the
  one-time code, keeping the device's RSA key encrypted on disk, sealing each reading (Diffie–Hellman +
  AES-256-GCM), signing it (RSA-3072 over SHA-512), and uploading it.
* **The adapter (written once per device model)** only reads the sensor and prints one line per reading:

  ```json
  {"hr": 78, "spo2": 97.0, "sbp": 122, "dbp": 79, "temp": 36.8, "rr": 15}
  ```

  Units: heart rate and breathing rate per minute, SpO₂ in %, blood pressure in mmHg, temperature in °C.
  `scripts/sensor_example.py` is a working template that prints simulated values in exactly this format.

**A line may contain any subset of the six values**, for example `{"spo2": 96, "hr": 81}` from an oximeter
alone. Rules: at least one value, blood pressure as a pair (`sbp` and `dbp` together), no unknown fields, and
values in a plausible range; anything else is rejected with 422. Never repeat or invent old values to fill
gaps: missing vitals show as *Not measured*, the clinical rules and NEWS2 use what was sent, and the AI model
scores only lines that contain all six (its score is shown as "Needs all six vitals" otherwise).

The in-app **Device guide** (sidebar) explains all of this for non-technical staff and patients: which
device types work, a "will my device work?" checklist, what each device status means, and troubleshooting.
Its content comes from `backend/app/device_catalog.py`, so the guide, the wizard and the device list agree.

Device status in the app: **Receiving readings** (last reading within 2 min), **Recently active**
(2–10 min), **No recent readings** (over 10 min: check power, range and network), **Not connected yet**,
**Revoked**.

### 5.2 Choosing devices

| Device type | How the adapter reads it | Notes |
|---|---|---|
| Bluetooth pulse oximeter | Bluetooth LE **Pulse Oximeter Service (0x1822)** | Gives SpO₂ and pulse rate |
| Bluetooth heart-rate strap | Bluetooth LE **Heart Rate Service (0x180D)** | Heart rate only |
| Bluetooth blood-pressure cuff | Bluetooth LE **Blood Pressure Service (0x1810)** | Systolic/diastolic per measurement |
| Bluetooth thermometer | Bluetooth LE **Health Thermometer Service (0x1809)** | |
| USB / serial bedside monitor | Vendor's serial protocol or SDK | Ask the vendor for the data interface document |
| Existing ward monitors | The hospital's integration engine (HL7 v2 or FHIR Observation feed) | The adapter subscribes to the feed and prints JSON lines per patient |
| Breathing rate | Most wearables do not measure it; bedside monitors and some patches do | Without a source, enter the clinician-observed value or choose a device that measures it |

Prefer devices that publish the standard Bluetooth services above or document their data interface.
Devices that only work with their own phone app usually cannot be connected.

**Bluetooth gateway (included).** `scripts/ble_gateway.py` reads any device that implements the standard
services above, using the `bleak` library (Windows, Linux, macOS), and prints one JSON line per reading:

```bash
pip install -r scripts/requirements-ble.txt
python scripts/ble_gateway.py --scan
python scripts/ble_gateway.py | python scripts/device_client.py stream --source stdin
```

It decodes the official measurement formats (IEEE 11073 SFLOAT/FLOAT, mmHg or kPa, °C or °F, the heart-rate
strap's skin-contact flag), collects what arrives in a 30-second window, and sends only what was measured. The
parsers are tested byte-for-byte against the specification (`backend/tests/test_ble.py`); test each device model
on site before relying on it, since this was not run against physical devices during the project.

### 5.3 Setting up one gateway (per patient)

On a Raspberry Pi 4/5 (64-bit OS), mini PC or laptop:

```bash
git clone <repository> vitalcare && cd vitalcare
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
sudo timedatectl set-ntp true      # clock must be within 60 seconds of the server
```

1. In Vitalcare, the patient's clinician opens the patient → **Devices → Connect device**. A short wizard
   asks what is being connected (gateway, oximeter, cuff, thermometer, strap, bedside monitor) and a name
   (e.g. "Home oximeter + cuff"), then shows a **QR code** and a one-time code, valid for 10 minutes.
   Its **For IT staff** section shows the command below with the link already filled in.
2. On the gateway, pair with the link from the QR code (or the three separate options):

   ```bash
   export RPM_DEVICE_PASSPHRASE='<long passphrase for this gateway>'
   .venv/bin/python scripts/device_client.py pair \
       --link "vitalcare-pair:v1?server=https%3A%2F%2Fvitalcare.cityhospital.org&id=<id>&code=<XXXX-XXXX-XXXX>" \
       --state /var/lib/vitalcare/patient-0421.json
   # same thing: --server https://vitalcare.cityhospital.org --pairing-id <id> --code <XXXX-XXXX-XXXX>
   ```

   The wizard changes to **Connected**, then to **Readings are arriving** when the first reading lands.
   Links are only accepted for https servers (plain http only for a `localhost` demo).
3. Start streaming from the adapter:

   ```bash
   python my_adapter.py | .venv/bin/python scripts/device_client.py stream --source stdin \
       --state /var/lib/vitalcare/patient-0421.json
   ```

   Every line prints `200 {"accepted": true, ...}`. Readings appear on the clinician's screen within seconds.

4. Run step 3 as a service on the gateway so it restarts after power cuts (same systemd pattern as above,
   with `RPM_DEVICE_PASSPHRASE` set in the service's environment file, readable only by its user).

**Gateway rules**

* Network: outbound HTTPS to the Vitalcare server only. No incoming ports needed.
* The `--state` file holds the device key, encrypted with the passphrase. Never copy it between gateways.
* Lost or stolen gateway: open the patient → **Devices → Revoke**. Its uploads are rejected immediately.
  Pair a replacement with a new code.
* A server with a certificate from a public or hospital CA needs no `--cert` option; the gateway uses the
  operating system's trusted certificates. Use `--cert ca.pem` only for a private CA the OS does not know.

### 5.4 Testing a gateway without real sensors

```bash
python scripts/sensor_example.py | python scripts/device_client.py stream --source stdin --state test-gw.json
```

The same pipeline then works with a real adapter in place of `sensor_example.py`.

---

## 6. Using Vitalcare day to day

| Role | What they do |
|---|---|
| **Clinician** | **Worklist:** patients ranked by urgency with AI risk and open alerts; a red banner means a critical alert has waited 15 minutes. **Patient record:** live vitals, 6 h / 24 h / 7 d trends, the AI explanation (which vital, how far from this patient's normal), alerts. Acknowledge with a note. Pair or revoke devices; import past readings (CSV `timestamp,hr,spo2,sbp,dbp,temp,rr`). |
| **Patient** | Sees only their own readings and alerts. **Pause sharing** stops uploads and blocks the care team until resumed. **Download my data** exports everything held about them. |
| **Admin** | People, bulk import, care teams, devices, privacy ledger (verify integrity), keys page. Admins never see clinical data. Erases a patient on a valid request (irreversible crypto-shredding). |
| **IT** | Backups, certificate renewal, updates, monitoring (`/api/health/ready`, JSON logs with request ids), key rotation. |

More detail per screen: `docs/user_guide.md`.

### Common situations

| Situation | What to do |
|---|---|
| Staff member lost their phone | Sign in with a recovery code, or an admin uses **Reset two-step** under People |
| Gateway lost or stolen | Clinician or admin: patient → Devices → **Revoke** |
| Patient withdraws consent | Patient pauses sharing, or the hospital records the request and erases the record |
| Suspected server compromise | Rotate the master key (`scripts/rotate_master_key.py`; this re-wraps keys but does not sign anyone out), ask staff to change passwords (which ends their other sessions) or disable affected accounts, re-pair devices if their keys may be exposed, and verify the ledger |
| Too many alerts | Expected in ICU data (about 3.8 critical alerts per patient-day in eICU). Tune thresholds with clinicians before a ward pilot |

---

## 7. Operating it

| Task | How | How often |
|---|---|---|
| Health check | `GET /api/health/ready` (database, keys, model integrity) | Every minute, from the hospital's monitoring |
| Backups | `pg_dump` of the database; `.env` and the sealed key file kept separately | Daily; test restore quarterly |
| Ledger check | `python scripts/verify_audit.py` or Admin → Privacy ledger → Verify integrity | Weekly |
| Master key rotation | Stop server → `python scripts/rotate_master_key.py` → start | Yearly, or after staff with key access leave |
| Certificate renewal | Replace the files at `RPM_TLS_CERT` / `RPM_TLS_KEY`, restart | Before expiry |
| Updates | Pull the new version, rebuild, restart (schema upgrades run automatically) | As released |
| Retention | Automatic, readings older than `RPM_RETENTION_DAYS` are deleted | Continuous |

### Where the master key lives (`RPM_MASTER_KEY_SOURCE`)

| Source | How it works | Use for |
|---|---|---|
| `env` (default) | Key in `.env` | Laptop demo only |
| `file` | `python scripts/seal_master_key.py` writes `secrets/master_keys.sealed` = AES-256-GCM under PBKDF2-HMAC-SHA-512 (600,000 rounds) of a passphrase, and removes the key from `.env`. The server asks for the passphrase when it starts (or reads `RPM_MASTER_PASSPHRASE` from the operating system's secret store, then forgets it) | A single server without an HSM |
| `command` | At start-up the server runs `RPM_MASTER_KEY_COMMAND`, which prints `{"version": n, "key": "<base64>", "previous": {...}}`. The command asks the hospital's HSM, cloud KMS or Vault for the key, so no key is stored on the server | Hospitals with an HSM / KMS |

Rotation works with `env` and `file` (the sealed file is re-sealed with the same passphrase); with `command`, rotate in the HSM / KMS.

---

## 8. Privacy and compliance (for the hospital's data protection officer)

* **Built in:** per-patient encryption at rest, encrypted transport, consent switch, right of access
  (export), right to erasure (crypto-shredding), retention limits, a tamper-evident access log, admins
  without clinical access, two-step sign-in for staff.
* **The hospital still has to:** complete a data protection impact assessment; write the patient consent
  text; decide retention periods; make sure backups expire in line with erasure promises (old backups
  stay readable until they expire); follow its national rules (for example India's DPDP Act 2023,
  HIPAA in the US, GDPR in Europe); and, before clinical use, obtain any medical-device approval required
  locally. Vitalcare has none.

---

## 9. Several hospitals

* Give each hospital its **own installation, master key, database and admin**. Nothing is shared.
* Hospitals that want a better shared AI model should not pool patient data through Vitalcare. Options:
  train on de-identified research data under a data use agreement (as done here with eICU), or keep data
  local and share only model updates (federated learning, not built).
* The shipped model is trained on the eICU demo (184 hospitals). Per reading it reached AUROC 0.72 on hospitals it
  had never seen (NEWS2 0.70) but 0.71 on MIMIC, where NEWS2 reached 0.74: results move between hospital systems.
  **Validate on each new hospital's own patients before relying on the AI score.**

---

## 10. Known limitations and next steps

| Limitation | Next step |
|---|---|
| Not a certified medical device | Clinical validation and regulatory process before any clinical decision relies on it |
| AI model trained on the small eICU demo (beats NEWS2 on unseen eICU hospitals, not on MIMIC) | Retrain on the full credentialed eICU / MIMIC-IV and validate on each hospital's own patients |
| Bluetooth gateway not tested with physical devices | Test and certify the chosen device models on site |
| Device client installs the whole backend | Package a slim client with only `cryptography` and `httpx` |
| Alert thresholds tuned for demonstration | Tune with clinicians for the ward or home setting; measure alarm burden |
| Demo keeps the master key in `.env` | Use the sealed key file, or the `command` source with an HSM / cloud KMS |
| No push notifications (SMS / pager) | Connect escalations to the hospital's paging system |

---

## Quick reference

| Setting (`.env`) | Purpose | Default |
|---|---|---|
| `RPM_MASTER_KEY_SOURCE` | Where the master key comes from: `env`, `file` (sealed, passphrase at start-up) or `command` (HSM / KMS) | `env` |
| `RPM_MASTER_KEY`, `RPM_MASTER_KEY_VERSION` | 256-bit master key and its version (`env` source only) | created by `init_env.py` |
| `RPM_MASTER_KEY_FILE` | Sealed key file (`file` source) | `secrets/master_keys.sealed` |
| `RPM_MASTER_KEY_COMMAND` | Command that prints the key bundle JSON (`command` source) | none |
| `DATABASE_URL` | PostgreSQL connection | SQLite in `backend/data/` |
| `RPM_ALLOWED_ORIGINS` | The site's own https address (CSRF protection) | `https://localhost:8443` |
| `RPM_SELF_URL` | Address the server uses for its built-in demo monitors | `https://localhost:8443` |
| `RPM_TLS_CERT`, `RPM_TLS_KEY` | Certificate and key files | `certs/dev-cert.pem`, `certs/dev-key.pem` |
| `RPM_HOST`, `RPM_PORT` | Listen address and port | `127.0.0.1`, `8443` |
| `RPM_RETENTION_DAYS` | Delete readings older than this (0 = keep) | `365` |
| `RPM_SIM_PASSPHRASE` | Protects the demo simulator's device keys | created by `init_env.py` |

| Command | What it does |
|---|---|
| `python demo.py` | Full local demo with seeded patients (not for real use) |
| `python scripts/create_admin.py` | First administrator on a real installation |
| `python scripts/device_client.py pair / stream` | Gateway pairing and streaming |
| `python scripts/verify_audit.py` | Check the privacy ledger |
| `python scripts/rotate_master_key.py` | Rotate the master key (server stopped) |
| `python scripts/seal_master_key.py` | Move the master key out of `.env` into a passphrase-sealed file |
| `python scripts/ble_gateway.py` | Read standard Bluetooth health devices for the gateway |
| `python -m app.ml.train_real --save` (in `backend/`) | Retrain the AI model on eICU and re-test it on unseen hospitals and MIMIC |
| `python -m app.ml.eval_real` (in `backend/`) | Re-run the real-data evaluation report |
