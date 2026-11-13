"""Print the current TOTP code for a seeded user (demo helper; reads seed_credentials.txt).

    python scripts/totp_code.py dr.mehta
"""
import hashlib
import sys

import _path
import pyotp

user = sys.argv[1] if len(sys.argv) > 1 else "admin"
for line in (_path.ROOT / "seed_credentials.txt").read_text().splitlines():
    if line.startswith(user + " ") and "totp_secret=" in line:
        secret = line.split("totp_secret=")[1].strip()
        print(pyotp.TOTP(secret, digits=6, interval=30, digest=hashlib.sha512).now())
        break
else:
    raise SystemExit(f"No TOTP secret for {user} in seed_credentials.txt")
