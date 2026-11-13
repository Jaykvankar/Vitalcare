"""Rotate the master key: re-wrap every patient DEK, TOTP secret and server key under a new key.

Readings are NOT re-encrypted (envelope encryption: only the small wrapped keys change).

    python scripts/rotate_master_key.py          (server stopped)

Updates .env: new RPM_MASTER_KEY, version + 1, old key moved to RPM_PREVIOUS_MASTER_KEYS.
After every row is on the new version you may remove the old key from RPM_PREVIOUS_MASTER_KEYS.
"""
import base64
import os
import re
import secrets

import _path

from app import config
from app.config import get_settings
from app.db import SessionLocal, init_engine
from app.models import Patient, User
from app.security import audit, auth, crypto, server_keys

env_path = _path.ROOT / ".env"
s = get_settings()
old_version, old_key = s.master_key_version, s.master_key
new_version = old_version + 1
new_key = secrets.token_bytes(32)

# Make the new key current in-process, keeping the old one available for unwrapping.
os.environ["RPM_PREVIOUS_MASTER_KEYS"] = ",".join(
    filter(None, [os.environ.get("RPM_PREVIOUS_MASTER_KEYS", ""), f"{old_version}:{base64.b64encode(old_key).decode()}"])
)
os.environ["RPM_MASTER_KEY"] = base64.b64encode(new_key).decode()
os.environ["RPM_MASTER_KEY_VERSION"] = str(new_version)
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
# Persist the new key to .env BEFORE committing, so a crash can never lose the only copy.
text = env_path.read_text()
text = re.sub(r"^RPM_MASTER_KEY=.*$", f"RPM_MASTER_KEY={os.environ['RPM_MASTER_KEY']}", text, flags=re.M)
text = re.sub(r"^RPM_MASTER_KEY_VERSION=.*$", f"RPM_MASTER_KEY_VERSION={new_version}", text, flags=re.M)
text = re.sub(r"^RPM_PREVIOUS_MASTER_KEYS=.*$", f"RPM_PREVIOUS_MASTER_KEYS={os.environ['RPM_PREVIOUS_MASTER_KEYS']}",
              text, flags=re.M)
env_path.write_text(text, encoding="utf-8")
db.commit()
server_keys.save(keys)
db.close()

audit.append("master_key_rotated", actor="script", detail=f"v{old_version}->v{new_version} patients={n_pat}")
print(f"Rotated master key v{old_version} -> v{new_version}: {n_pat} patient keys, {n_totp} TOTP secrets, server keys.")
