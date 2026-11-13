# Threat model (STRIDE)

**Assets:** vital signs, patient identity and contact details, clinician notes, credentials, keys, and the integrity of the access record.
**Trust boundaries:** device ↔ network ↔ server; browser ↔ server; server ↔ database/backups; operators (admins, DBAs) inside the organisation.

| STRIDE | Threat | Mitigation in Vitalcare | Residual risk |
|---|---|---|---|
| **S**poofing | Fake device sends readings | Per-device RSA-3072 key; RSA-PSS sign-the-digest on every packet; keys registered only via one-time pairing code (HMAC proof, 10 min, 5 tries) | Stolen physical device keeps its key until revoked |
| | Stolen password | PBKDF2-HMAC-SHA-512 (210k); lockout + DB rate limit; TOTP (HMAC-SHA-512) for staff; single-use recovery codes | Patients have password-only sign-in |
| | Session hijack | Random token, httpOnly + Secure + SameSite=Strict cookie, DB stores SHA-512 only, idle/absolute timeout, other sessions revoked on password change | XSS in a future change could still act within the session |
| **T**ampering | Modify reading in transit | TLS 1.3 + AES-GCM tag + RSA signature over the whole packet | – |
| | Move ciphertext to another row / patient | AES-GCM AAD binds patient, device, seq, timestamp | – |
| | Edit or delete audit rows | DB triggers block UPDATE/DELETE; SHA-512 hash chain; ECDSA P-384 signed checkpoints; `UNIQUE(prev_hash)` prevents forks | Rows after the last checkpoint can be truncated undetected until the next checkpoint (every 50 rows and at shutdown) |
| | Swap the ML model file | Pinned SHA-512 checked before unpickling | Attacker who can change code can change the pin |
| **R**epudiation | "I never opened that record" | Every decrypt, ack, consent change, pairing, import, erasure is in the signed ledger with actor and time | Reads are de-duplicated to one entry per viewer per minute |
| **I**nformation disclosure | Stolen DB or backup | All clinical data and PII are AES-256-GCM ciphertext; keys wrapped by a master key kept outside the DB | Master key in an environment variable (production: HSM/KMS) |
| | Admin snooping | Admins have no decrypt path for vitals/PII; historical vitals import is clinician-only | A server operator with the master key can decrypt |
| | Logs leak data | JSON logs carry method, path, status, duration and request id only; reason codes, never values | – |
| | Network observer | TLS 1.3 (AES-256-GCM-SHA384) plus inner DH sealing with per-reading keys (forward secrecy) | Metadata (who talks to the server, when) |
| **D**enial of service | Flood ingest / login / pairing | Per-key DB-backed rate limits; request size limits; device must sign before any expensive work is kept | No upstream WAF in the demo |
| **E**levation of privilege | Clinician reads unassigned patient | RBAC + assignment check on every route; 404 for non-assigned (no ID probing) | – |
| | CSRF from another site | SameSite=Strict, required `X-RPM-Request` header, Origin allow-list | – |

## Privacy controls (GDPR / DPDP-style)
- **Consent:** patients can pause sharing; ingest and clinician decrypts stop immediately.
- **Access:** patients can download everything held about them (`/api/me/export`).
- **Erasure:** crypto-shredding destroys the patient key. Copies in older backups remain readable until those backups expire, so backup retention must be shorter than or equal to the erasure promise.
- **Minimisation:** `RPM_RETENTION_DAYS` (default 365) purges old readings and rollups automatically.
