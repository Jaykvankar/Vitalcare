"""Print the current TOTP code for a seeded user (demo helper; reads seed_credentials.txt).

    python scripts/totp_code.py dr.mehta
"""
import hashlib
import sys

import _path
import pyotp


def field(text: str, user: str, label: str) -> str | None:
    """Value under `label:` in the user's block (`== user (role)` ... blank line)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"== {user} ("):
            block = lines[i + 1:]
            for j, b in enumerate(block):
                if not b.strip():
                    return None
                if b == f"{label}:" and j + 1 < len(block):
                    return block[j + 1].strip()
    return None


user = sys.argv[1] if len(sys.argv) > 1 else "admin"
secret = field((_path.ROOT / "seed_credentials.txt").read_text(encoding="utf-8"), user, "totp secret")
if not secret:
    raise SystemExit(f"No TOTP secret for {user} in seed_credentials.txt")
print(pyotp.TOTP(secret, digits=6, interval=30, digest=hashlib.sha512).now())
