"""Rotate the master key: re-wrap every patient DEK, TOTP secret and server key under a new key.

Readings are NOT re-encrypted (envelope encryption: only the small wrapped keys change).

    python scripts/rotate_master_key.py          (server stopped)

Updates .env (or re-seals secrets/master_keys.sealed with the same passphrase when RPM_MASTER_KEY_SOURCE=file):
new key, version + 1, old key kept as a previous version.
After every row is on the new version you may remove the old key from RPM_PREVIOUS_MASTER_KEYS.
"""
import base64
import os
import re
import secrets

import _path

from app import config, keysource
from app.config import get_settings
from app.db import SessionLocal, init_engine
from app.models import Patient, User
from app.security import audit, auth, crypto, server_keys

env_path = _path.ROOT / ".env"
source = os.environ.get("RPM_MASTER_KEY_SOURCE", "env").strip().lower()
if source == "command":
    raise SystemExit("The master key comes from RPM_MASTER_KEY_COMMAND (HSM / KMS): rotate it there, then re-run "
                     "this script with the new key bundle exposed by that command.")
sealed_passphrase = None
if source == "file":   # read the passphrase once; it is needed again to re-seal the new key bundle
    sealed_passphrase = keysource.passphrase()
    os.environ["RPM_MASTER_PASSPHRASE"] = sealed_passphrase
s = get_settings()
old_version, old_key = s.master_key_version, s.master_key
new_version = old_version + 1
new_key = secrets.token_bytes(32)

# Make the new key current in-process, keeping every older key available for unwrapping.
previous = {**s.previous_master_keys, old_version: old_key}
os.environ["RPM_PREVIOUS_MASTER_KEYS"] = ",".join(
    f"{v}:{base64.b64encode(k).decode()}" for v, k in sorted(previous.items()))
os.environ["RPM_MASTER_KEY"] = base64.b64encode(new_key).decode()
os.environ["RPM_MASTER_KEY_VERSION"] = str(new_version)
bundle = keysource.KeyBundle(version=new_version, key=new_key, previous=previous)
if sealed_passphrase is not None:
    os.environ["RPM_MASTER_KEY_SOURCE"] = "env"   # use the new keys from the environment for the rest of this run
config.reset_settings()
s = get_settings()

init_engine(s.database_url)
keys = server_keys.load_or_create()   # loads with old key version recorded in the file
db = SessionLocal()
n_pat = n_totp = 0
for p in db.query(Patient).all():
    dek = crypto.unwrap_dek(p.wrapped_dek, p.id, p.key_version)
    p.wrapped_dek, p.key_version = crypto.wrap_dek(dek, p.id)
    n_pat += 1
for u in db.query(User).filter(User.totp_secret_enc.isnot(None)).all():
    secret = auth.load_totp_secret(u)
    auth.store_totp_secret(u, secret)
    n_totp += 1
# Persist the new key BEFORE committing, so a crash can never lose the only copy.
if sealed_passphrase is not None:
    sealed = keysource.default_sealed_path()
    sealed.with_suffix(".tmp").write_bytes(keysource.seal(bundle, sealed_passphrase))
    sealed.with_suffix(".tmp").replace(sealed)
else:
    text = env_path.read_text()
    text = re.sub(r"^RPM_MASTER_KEY=.*$", f"RPM_MASTER_KEY={os.environ['RPM_MASTER_KEY']}", text, flags=re.M)
    text = re.sub(r"^RPM_MASTER_KEY_VERSION=.*$", f"RPM_MASTER_KEY_VERSION={new_version}", text, flags=re.M)
    text = re.sub(r"^RPM_PREVIOUS_MASTER_KEYS=.*$",
                  f"RPM_PREVIOUS_MASTER_KEYS={os.environ['RPM_PREVIOUS_MASTER_KEYS']}", text, flags=re.M)
    env_path.write_text(text, encoding="utf-8")
db.commit()
server_keys.save(keys)
db.close()

audit.append("master_key_rotated", actor="script", detail=f"v{old_version}->v{new_version} patients={n_pat}")
print(f"Rotated master key v{old_version} -> v{new_version}: {n_pat} patient keys, {n_totp} TOTP secrets, server keys.")
