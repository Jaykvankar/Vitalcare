"""Create a local .env with a fresh 256-bit master key and simulator passphrase.

    python scripts/init_env.py
"""
import base64
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = ROOT / ".env"
if env.exists():
    raise SystemExit(".env already exists; delete it first if you really want new keys (old data becomes unreadable).")

env.write_text(
    "# Local secrets - never commit this file.\n"
    f"RPM_MASTER_KEY={base64.b64encode(secrets.token_bytes(32)).decode()}\n"
    "RPM_MASTER_KEY_VERSION=1\n"
    "RPM_PREVIOUS_MASTER_KEYS=\n"
    f"RPM_SIM_PASSPHRASE={secrets.token_urlsafe(24)}\n"
    "RPM_SELF_URL=https://localhost:8443\n"
    "RPM_ALLOWED_ORIGINS=https://localhost:8443,https://127.0.0.1:8443,https://localhost:5173\n",
    encoding="utf-8",
)
print(f"Wrote {env}")
