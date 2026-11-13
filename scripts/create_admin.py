"""First-time setup for a real installation: create the database and the first administrator.

    python scripts/create_admin.py --username it.admin --name "IT Administrator"

The password is read interactively (or from RPM_ADMIN_PASSWORD for automation). The admin sets up
two-step sign-in (TOTP) at first login. No demo users or data are created.
"""
import argparse
import getpass
import os

import _path  # noqa: F401

from app import services
from app.config import get_settings
from app.db import SessionLocal, create_schema, init_engine
from app.models import User
from app.security import audit, server_keys

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--username", required=True)
p.add_argument("--name", required=True, help="Full name shown in the app")
a = p.parse_args()

init_engine(get_settings().database_url)
create_schema()
server_keys.load_or_create()
db = SessionLocal()
if db.query(User).filter_by(username=a.username.lower()).first():
    raise SystemExit(f"User {a.username} already exists")

password = os.environ.get("RPM_ADMIN_PASSWORD") or getpass.getpass("Password (min 12 chars): ")
if len(password) < 12 or a.username.lower() in password.lower():
    raise SystemExit("Password must be at least 12 characters and must not contain the username")
if not os.environ.get("RPM_ADMIN_PASSWORD") and getpass.getpass("Repeat password: ") != password:
    raise SystemExit("Passwords do not match")

user = services.create_user(db, username=a.username, full_name=a.name, role="admin", password=password)
audit.append("user_created", actor="create_admin.py", target=f"user:{user.id}", detail="role=admin bootstrap")
print(f"Created administrator '{user.username}'. Start the server and sign in; you will be asked to set up TOTP.")
