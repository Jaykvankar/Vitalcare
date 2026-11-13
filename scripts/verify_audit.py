"""Verify the audit ledger: recompute the SHA-512 chain and check every ECDSA checkpoint.

    python scripts/verify_audit.py
"""
import json

import _path  # noqa: F401

from app.config import get_settings
from app.db import init_engine
from app.security import audit

init_engine(get_settings().database_url)
result = audit.verify()
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["ok"] else 1)
