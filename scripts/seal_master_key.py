"""Move the master keys out of .env into a passphrase-sealed file (server stopped).

    python scripts/seal_master_key.py

1. Reads the current master key (and older versions) from .env.
2. Asks for a passphrase twice (at least 12 characters).
3. Writes secrets/master_keys.sealed = AES-256-GCM(PBKDF2-HMAC-SHA-512(passphrase, 600,000 rounds), keys),
   and checks that it opens again with the passphrase.
4. Only then removes the keys from .env and sets RPM_MASTER_KEY_SOURCE=file.

From then on the server asks for the passphrase when it starts. Keep the passphrase somewhere safe (for example a
password manager or the hospital's secret store): without it, and without a backup of the keys, the data cannot be read.
"""
import getpass
import os
import re
import sys

import _path

from app import keysource
from app.config import get_settings

env_path = _path.ROOT / ".env"
if os.environ.get("RPM_MASTER_KEY_SOURCE", "env").lower() != "env":
    sys.exit("The master key is already not in .env (RPM_MASTER_KEY_SOURCE is set).")
s = get_settings()
bundle = keysource.KeyBundle(version=s.master_key_version, key=s.master_key, previous=dict(s.previous_master_keys))
target = keysource.default_sealed_path()
if target.exists():
    sys.exit(f"{target} already exists; move it away first.")

pw = os.environ.pop("RPM_MASTER_PASSPHRASE", "")
if not pw:
    pw = getpass.getpass("New passphrase (12+ characters): ")
    if getpass.getpass("Repeat it: ") != pw:
        sys.exit("The two passphrases differ; nothing changed.")
if len(pw) < 12:
    sys.exit("Passphrase too short (at least 12 characters).")

target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(keysource.seal(bundle, pw))
check = keysource.unseal(target.read_bytes(), pw)
if (check.key, check.version, check.previous) != (bundle.key, bundle.version, bundle.previous):
    target.unlink()
    sys.exit("Verification failed; nothing changed.")

text = env_path.read_text(encoding="utf-8")
for name in ("RPM_MASTER_KEY", "RPM_MASTER_KEY_VERSION", "RPM_PREVIOUS_MASTER_KEYS"):
    text = re.sub(rf"^{name}=.*\n?", "", text, flags=re.M)
text = text.rstrip("\n") + "\nRPM_MASTER_KEY_SOURCE=file\n"
env_path.write_text(text, encoding="utf-8")
print(f"Sealed master key v{bundle.version} (+{len(bundle.previous)} older) into {target}.")
print("The keys were removed from .env. The server will now ask for the passphrase when it starts.")
