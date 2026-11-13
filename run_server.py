"""Start the HTTPS server: https://localhost:8443

    .venv\\Scripts\\python run_server.py
"""
import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

if __name__ == "__main__":
    if "--http" in sys.argv:
        # Localhost-only plain-HTTP mode for browsers that do not trust the self-signed cert.
        # Device payloads are still DH+AES sealed and RSA signed; only the outer TLS layer is off.
        port = int(os.environ.get("RPM_PORT", "8000"))
        os.environ.update({"RPM_SECURE_COOKIES": "false", "RPM_SELF_URL": f"http://localhost:{port}",
                           "RPM_ALLOWED_ORIGINS": f"http://localhost:{port},http://127.0.0.1:{port}"})
        uvicorn.run("app.main:app", host="127.0.0.1", port=port, workers=1, server_header=False)
        raise SystemExit(0)
    cert, key = ROOT / "certs" / "dev-cert.pem", ROOT / "certs" / "dev-key.pem"
    if not cert.exists():
        raise SystemExit("No TLS certificate. Run: python scripts/gen_dev_cert.py")
    uvicorn.run(
        "app.main:app", host=os.environ.get("RPM_HOST", "127.0.0.1"), port=int(os.environ.get("RPM_PORT", "8443")),
        ssl_certfile=str(cert), ssl_keyfile=str(key), workers=1, proxy_headers=False, server_header=False,
    )
