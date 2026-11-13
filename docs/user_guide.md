# User guide

## Hospital IT (first install)
1. `python scripts/init_env.py`, which creates `.env` with a random master key. Back this file up securely: without it, no data can be decrypted.
2. Install a real TLS certificate in `certs/` (or `python scripts/gen_dev_cert.py` for testing).
3. `python scripts/create_admin.py --username it.admin --name "IT Administrator"`
4. Start the server (`python run_server.py` or `docker compose up -d`) and sign in. You will set up an authenticator app (SHA-512 TOTP) and receive 10 recovery codes.

## Administrator
- **Bulk import:** download the template, fill in staff and patients (with `care_team` usernames), upload, check the preview, then create. Download the temporary passwords file immediately; it is shown once.
- **People:** add individuals, disable accounts, reset someone's two-step sign-in, or **Erase** a patient (crypto-shredding, irreversible).
- **Care teams:** link clinicians to patients. Only linked clinicians can see a patient.
- **Devices & pairing:** issue a pairing code for any patient; revoke lost devices.
- **Data sources:** demo only. Start simulated monitors, choose synthetic or real recorded data, and inject episodes.
- **Privacy ledger:** see every access; *Verify integrity* checks the hash chain and signatures.
- **Keys & algorithms:** key versions and fingerprints. Rotate with `python scripts/rotate_master_key.py`.

## Clinician
- **Worklist:** patients sorted by urgency. A red banner means a critical alert has waited more than 15 minutes (escalated).
- **Patient record:** live vitals, trends (6 h raw, 24 h / 7 d summarised), the AI early-warning panel with reasons, and alerts. *Acknowledge* with an optional note (stored encrypted).
- **Pair device:** create a code and enter it on the patient's device. **Import past readings:** upload a CSV from another system (`timestamp,hr,spo2,sbp,dbp,temp,rr`).
- **Account:** change your password, or create new recovery codes.
- Lost your phone? On the sign-in code screen choose *Use a recovery code*.

## Patient
- **My health:** your latest readings, trends and alerts.
- **Sharing:** *Pause sharing* stops uploads and blocks your care team; *Resume* turns it back on.
- **Download my data:** everything held about you, as a JSON file.
- New accounts must choose their own password at first sign-in.
