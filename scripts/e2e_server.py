"""Start a throw-away server for end-to-end tests: fresh keys, fresh seeded database, plain HTTP on :8010.

Used by frontend/playwright.config.ts. Never touches the real .env, database or credentials.
"""
import base64
import os
import secrets
import shutil
import subprocess
import sys

import _path

E2E = _path.ROOT / ".e2e"
PORT = os.environ.get("RPM_E2E_PORT", "8010")

if E2E.exists():
    shutil.rmtree(E2E)
E2E.mkdir()

env = {
    **os.environ,
    "RPM_MASTER_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
    "RPM_MASTER_KEY_VERSION": "1",
    "RPM_PREVIOUS_MASTER_KEYS": "",
    "RPM_SIM_PASSPHRASE": secrets.token_urlsafe(16),
    "RPM_DATA_DIR": str(E2E / "data"),
    "DATABASE_URL": f"sqlite:///{(E2E / 'e2e.db').as_posix()}",
    "RPM_SIM_KEYSTORE": str(E2E / "sim" / "keystore.json"),
    "RPM_SEED_CREDENTIALS": str(E2E / "credentials.txt"),
    "RPM_SEED_HISTORY_HOURS": "3",
    "RPM_PORT": PORT,
}
subprocess.run([sys.executable, "-m", "app.seed"], cwd=_path.ROOT / "backend", env=env, check=True)  # noqa: S603  (fixed argv)
sys.exit(subprocess.call([sys.executable, str(_path.ROOT / "run_server.py"), "--http"], env=env))  # noqa: S603
