"""Start the Vitalcare HTTPS server (default https://localhost:8443; RPM_HOST, RPM_PORT, RPM_TLS_CERT, RPM_TLS_KEY)

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
    # Demo mode shows demo passwords and sign-in codes on the sign-in page: never on an address others can reach.
    if os.environ.get("RPM_DEMO_MODE", "").lower() == "true" and \
            os.environ.get("RPM_HOST", "127.0.0.1") not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Demo mode only runs on this computer (RPM_HOST must be 127.0.0.1). "
                         "Unset RPM_DEMO_MODE for a real installation.")
    if "--http" in sys.argv:
        # Localhost-only plain-HTTP mode for browsers that do not trust the self-signed cert.
        # Device payloads are still DH+AES sealed and RSA signed; only the outer TLS layer is off.
        port = int(os.environ.get("RPM_PORT", "8000"))
        os.environ.update({"RPM_SECURE_COOKIES": "false", "RPM_SELF_URL": f"http://localhost:{port}",
                           "RPM_ALLOWED_ORIGINS": f"http://localhost:{port},http://127.0.0.1:{port}"})
        uvicorn.run("app.main:app", host="127.0.0.1", port=port, workers=1, server_header=False, access_log=False)
        raise SystemExit(0)
    # A hospital points these at its own certificate and key; the defaults are the self-signed dev pair.
    cert = Path(os.environ.get("RPM_TLS_CERT", ROOT / "certs" / "dev-cert.pem"))
    key = Path(os.environ.get("RPM_TLS_KEY", ROOT / "certs" / "dev-key.pem"))
    if not cert.exists() or not key.exists():
        raise SystemExit(f"TLS certificate or key not found ({cert}, {key}). "
                         "Set RPM_TLS_CERT / RPM_TLS_KEY, or run: python scripts/gen_dev_cert.py")
    uvicorn.run(
        "app.main:app", host=os.environ.get("RPM_HOST", "127.0.0.1"), port=int(os.environ.get("RPM_PORT", "8443")),
        ssl_certfile=str(cert), ssl_keyfile=str(key), workers=1, proxy_headers=False, server_header=False, access_log=False,
    )
