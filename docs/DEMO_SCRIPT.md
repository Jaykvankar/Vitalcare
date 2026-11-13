# Vitalcare demo script (about 8 minutes)

## Before you present

**The evening before**
1. `git pull`, then run the checks once so you know everything is green:
   ```bash
   cd backend && ..\.venv\Scripts\python -m pytest -q
   ```
2. Rehearse this script twice. Record one full run (Windows: `Win + Alt + R` with Xbox Game Bar) as a backup video.

**About 30 minutes before**
1. Start fresh data and the server:
   ```bash
   .venv\Scripts\python demo.py --reset
   ```
   It backs up the old demo data, seeds new data with 24 h of encrypted history, and starts streaming on **http://localhost:8000**.
2. Open in the browser (one tab each):
   - **Tab 1:** http://localhost:8000 (the app)
   - **Tab 2:** `docs/architecture.html` (works offline)
   - **Tab 3:** `docs/presentation.html` (slides)
3. Staff accounts show their password and 6-digit code on the sign-in screen in demo mode, so no phone and no printed password list are needed. `seed_credentials.txt` still has them if the screen does not.
4. Set the browser zoom to 110–125 % so the room can read it, and switch off notifications.

| Account | Role | Notes |
|---|---|---|
| `dr.mehta` | Clinician | Cares for Rohan Sharma, Meera Iyer, Imran Khan |
| `admin` | Administrator | Cannot see any vital signs |
| `p.iyer` | Patient (Meera Iyer) | Real eICU ICU stay replayed |

Patients' data sources: **Meera Iyer** and **Ananya Das** replay real eICU ICU stays from two different hospitals,
**Imran Khan** replays a real MIMIC-III stay, and **Rohan Sharma** is synthetic (you can inject a deterioration).

---

## The run (say the words in *italics*)

### 1. The problem and the idea (slides 1–3, 1 min)
*"Remote patient monitoring sends a patient's vital signs to their care team. That data is extremely sensitive, so our
goal was to collect it securely, analyse it with AI, and store it so that only the patient's own care team can ever read it."*

### 2. Architecture (Tab 2, 1 min)
Click **Follow one reading** and step through 2–3 steps.
*"A reading is sealed on the device with a fresh Diffie–Hellman key and AES-256-GCM, signed with RSA over a SHA-512 digest,
checked on arrival, scored, and stored under a key that belongs only to that patient."*

### 3. Clinician view (Tab 1, 2 min)
1. Under **Try a role** select **Caretaker**. That fills in `dr.mehta` and the password shown on screen, then select **Continue**, **Use this code**, and **Verify and sign in**.
   *"Staff need a second factor. In real use this comes from an authenticator app; the demo shows it on screen."*
2. **Patient worklist**: *"Patients are ranked by urgency. Two of them are real ICU patients from the eICU dataset."*
3. Open **Meera Iyer**:
   - Point at the **vital cards**: temperature says **Not measured**. *"Real devices rarely measure everything, so the
     system works with partial readings instead of inventing values."*
   - Point at the **AI early-warning panel** next to the chart: the reasons in plain language. *"The AI only scores complete
     readings; the clinical rules and NEWS2 always run."*
   - Scroll to **Alerts** → **Acknowledge** one with a short note. *"The note is stored encrypted with this patient's key."*

### 4. Connecting a device (1 min)
In the patient's **Devices** card select **Connect device** → **Vitalcare gateway** → **Create connection code**.
*"A one-time code and QR code, valid 10 minutes. The device makes its own RSA key and proves it knows the code with an HMAC,
so the code itself never crosses the network."* Close the window (the code just expires).
Optional: open **Device guide** in the sidebar for 10 seconds.

### 5. Security inspector and live attacks (2 min) — the ISC highlight
1. Sign out, sign in as **admin** (code on screen again).
2. Open **Security inspector**. Walk down the numbered steps:
   *"This is the real packet that just arrived: the device's Diffie–Hellman public value, 3072 bits; the AES-GCM nonce and
   authentication tag; the SHA-512 digest; the RSA-PSS signature, verified; the replay check; then it is stored under the
   patient's own AES key, and the access goes into a hash-chained ledger signed with ECDSA."*
3. Under **Try to attack this device's traffic**, click **Run attack** on all three:
   - Replay → **Blocked (409)**: *"Same packet sent twice: the sequence number is not newer."*
   - Change one bit → **Blocked (401)**: *"One flipped bit and the SHA-512 digest no longer matches the signature."*
   - Wrong key → **Blocked (401)**: *"A packet signed with any other key is rejected."*

### 6. Admin cannot read health data, ledger is tamper-evident (30 s)
- **People** page: *"Admins manage accounts but have no way to decrypt vital signs."*
- **Privacy ledger** → **Verify integrity** → *"Ledger intact."* *"Every access, including the attacks we just tried, is recorded."*

### 7. Patient rights (30 s)
Sign in as **p.iyer** (password only):
- Own data only; **Pause sharing** (care team immediately loses access), then **Resume sharing**.
- **Download my data**: *"The right of access. Erasure works by destroying this patient's key (crypto-shredding)."*

### 8. Results and honest limits (slides, 1 min)
- eICU, 2,032 real ICU stays from 184 hospitals: NEWS2 AUROC 0.734; our synthetic-trained model 0.687; a model trained on
  real data from *other* hospitals 0.760. *"So the next step is retraining on real data."*
- Not done: real Bluetooth adapters (the path is built and tested with a gateway program), phone app, SMS alerts,
  clinical certification.

---

## If something goes wrong
| Problem | Fix |
|---|---|
| "Invalid username or password" | Select the eye button to see what was typed (or autofilled by the browser) and compare it with the password printed when `demo.py` starts. Passwords are case-sensitive; `--reset` keeps the same ones |
| Code rejected | Wait for the next code (changes every 30 s) and select **Use this code** again |
| Page empty or "Not signed in" | Refresh; sign in again |
| No readings arriving | Admin → **Data sources** → **Start all** |
| Server stopped | Run `.venv\Scripts\python demo.py` again (keeps the data) |
| Anything else | Play the backup recording and continue with the slides |

## Likely viva questions
See `docs/viva_defense.md` for full answers. Short versions:
- **Why AES-GCM and not plain AES?** GCM is a mode of AES that also detects any change (authentication tag).
- **Why both Diffie–Hellman and RSA?** DH gives a fresh secret key per reading (forward secrecy); RSA proves which device sent it.
- **What does sign-the-digest mean here?** We hash the whole packet with SHA-512 and RSA-sign that digest.
- **Why ECDSA for the ledger?** It is the DSA algorithm on an elliptic curve, approved by NIST (FIPS 186-5); classic DSA is withdrawn for new signatures.
- **What if the database is stolen?** Every reading and personal detail is AES-256-GCM ciphertext; keys are wrapped by a master key kept outside the database.
- **What if an insider edits the audit log?** The hash chain breaks, and the ECDSA-signed checkpoint no longer matches (tested).
- **Is the AI reliable?** It is decision support only. On real data NEWS2 still beats our synthetic-trained model; we report that openly.
