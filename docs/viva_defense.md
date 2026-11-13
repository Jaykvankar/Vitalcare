# Viva notes: why each algorithm, and answers to likely questions

Every course topic is used:
- AES
- Hash function / SHA-512
- Public-key encryption
- RSA
- Diffie–Hellman
- DSA
- Sign-the-digest
- Direct digital signature
- RSA digital signature

Each item below is a taught algorithm used in a standard way, not a new algorithm. Run `python scripts/crypto_demo.py` to show every step live.

| Possible question | Answer |
|---|---|
| "GCM wasn't taught" | GCM is a *mode of operation*, not a new cipher. Every block is still AES-256 (SubBytes, ShiftRows, MixColumns, AddRoundKey, 14 rounds, key expansion). GCM runs AES in counter mode and adds an authentication tag, so tampering is detected. |
| "HMAC / HKDF / PBKDF2 weren't taught" | They are standard constructions built only from SHA-512. HMAC is a keyed SHA-512. HKDF is HMAC used to derive keys from the DH secret. PBKDF2 is HMAC repeated 210,000 times to slow down password guessing. |
| "What is PSS?" | RSA should never be used "textbook" (raw m^d mod n is deterministic and forgeable). PSS is the standard padding for RSA signatures. We still hash first and sign the digest. |
| "Why both DH and RSA?" | DH creates a fresh AES key for every reading (forward secrecy). RSA proves *who* sent it. Together they form authenticated key exchange. |
| "Where is public-key encryption?" | The device encrypts to the server's public DH value (hybrid DH + AES, the DHIES/ElGamal pattern). Only the holder of the server's private exponent can decrypt. |
| "Why ECDSA, not the DSA we learned?" | It uses the same DSA signing equations (random k; r, s = k⁻¹(H(m) + x·r)), computed in an elliptic-curve group instead of mod p. NIST withdrew classic DSA for new signatures in FIPS 186-5 (2023) and named ECDSA as its approved successor. |
| "Why DSA-family for the audit log but RSA for devices?" | To demonstrate both signature schemes, each where it fits. ECDSA gives small, fast signatures for frequent checkpoints. RSA is widely supported on devices and is the scheme we show as sign-the-digest. |
| "Why not Caesar / Playfair / substitution / transposition?" | Classical ciphers are broken by frequency analysis or brute force. AES itself is the modern **product cipher**: it repeats substitution (SubBytes) and permutation/transposition (ShiftRows) rounds, which is the classical idea done securely. |
| "Why a hash chain *and* signatures?" | Anyone with database write access can edit a row and recompute every later hash. They cannot forge the server's ECDSA signature on the checkpoint, so the rewrite is detected (this is tested). |
| "What about TLS internals?" | TLS 1.3 is the standard transport, configured by us, not designed by us. Our certificate is RSA-3072 signed over SHA-512, and the negotiated suite is `TLS_AES_256_GCM_SHA384` (AES + SHA-2). Our own protocol is fully course-based, and the data stays encrypted and authenticated even with TLS turned off. |
| "Is everything a real standard?" | Yes: AES-GCM (FIPS 197, SP 800-38D), SHA-512 (FIPS 180-4), HMAC (FIPS 198-1), HKDF (RFC 5869), PBKDF2 (SP 800-132), RSA-PSS and ECDSA (FIPS 186-5), FFDH ffdhe3072 (RFC 7919, SP 800-56A), TOTP (RFC 6238), TLS 1.3 (RFC 8446). |

## New features, same algorithms

| Feature | How it uses the existing techniques |
|---|---|
| Recovery codes | Random codes stored only as **PBKDF2-HMAC-SHA-512** hashes, single use |
| Right to erasure | **Crypto-shredding**: overwrite the patient's wrapped **AES-256** key. Everything encrypted under it becomes unreadable at once, with no need to find and delete every row |
| 24 h / 7 d charts | 5-minute rollups encrypted with **AES-256-GCM** under the patient key (AAD = patient + bucket) |
| Bulk import | Uploaded file fingerprinted with **SHA-512** and recorded in the ledger |
| Audit chain safety | `UNIQUE(prev_hash)` in the database: the **SHA-512** chain cannot fork even with several server processes |
| TOTP replay guard | Last used time-step stored in the DB, so a code cannot be reused after a restart or on another process |
