import base64
import os
import secrets
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("rpm")
    os.environ.update({
        "RPM_MASTER_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        "RPM_MASTER_KEY_VERSION": "1",
        "RPM_PREVIOUS_MASTER_KEYS": "",
        "RPM_DATA_DIR": str(tmp / "data"),
        "DATABASE_URL": f"sqlite:///{(tmp / 'test.db').as_posix()}",
        "RPM_SIM_KEYSTORE": str(tmp / "sim" / "keystore.json"),
        "RPM_SIM_PASSPHRASE": "test-passphrase",
        "RPM_ALLOWED_ORIGINS": "https://testserver",
    })
    from app import config
    from app.security import server_keys

    config.reset_settings()
    server_keys.reset_cache()
    return tmp


@pytest.fixture(scope="session")
def app_client(env):
    from fastapi.testclient import TestClient

    from app.main import create_app, init_backend

    init_backend()
    app = create_app(with_lifespan=False)
    return app


@pytest.fixture(scope="session")
def world(app_client):
    """Users, patients, devices and assignments shared by API tests."""
    from app import services
    from app.db import SessionLocal
    from app.models import Assignment
    from app.security import auth, signatures

    db = SessionLocal()
    pw = "a-very-long-test-password"
    admin = services.create_user(db, username="admin", full_name="Admin", role="admin", password=pw)
    c1 = services.create_user(db, username="clin1", full_name="Clin One", role="clinician", password=pw)
    c2 = services.create_user(db, username="clin2", full_name="Clin Two", role="clinician", password=pw)
    p1 = services.create_user(db, username="pat1", full_name="Pat One", role="patient", password=pw,
                              dob="1960-01-01", phone="123", address="Street 1")
    p2 = services.create_user(db, username="pat2", full_name="Pat Two", role="patient", password=pw)
    secrets_ = {}
    for u in (admin, c1, c2):
        s = auth.new_totp_secret()
        auth.store_totp_secret(u, s)
        u.totp_confirmed = True
        secrets_[u.username] = s
    db.add(Assignment(clinician_id=c1.id, patient_id=p1.patient.id))
    db.commit()

    dev_key = signatures.rsa_generate()
    dev = services.register_device(db, patient_id=p1.patient.id, label="test",
                                   public_key_pem=signatures.public_pem(dev_key), device_id="dev-test-1")
    dev2_key = signatures.rsa_generate()
    services.register_device(db, patient_id=p2.patient.id, label="test",
                             public_key_pem=signatures.public_pem(dev2_key), device_id="dev-test-2")
    ids = {"admin": admin.id, "clin1": c1.id, "clin2": c2.id,
           "p1": p1.patient.id, "p2": p2.patient.id, "p1_user": p1.id}
    db.close()
    return {"pw": pw, "totp": secrets_, "dev_key": dev_key, "dev_id": dev.id,
            "dev2_key": dev2_key, "ids": ids, "app": app_client}


@pytest.fixture
def client_for(world):
    """Return a logged-in TestClient for a username (handles TOTP)."""
    import hashlib
    import time

    import pyotp
    from fastapi.testclient import TestClient

    from app.security import auth

    def make(username: str):
        c = TestClient(world["app"], base_url="https://testserver")
        c.headers["X-RPM-Request"] = "1"
        r = c.post("/api/auth/login", json={"username": username, "password": world["pw"]})
        assert r.status_code == 200, r.text
        if r.json()["mfa"] == "verify":
            totp = pyotp.TOTP(world["totp"][username], digest=hashlib.sha512)
            # Tests log in many times within one 30 s step; clear the replay guard between logins.
            auth._last_totp_step.clear()
            r = c.post("/api/auth/mfa", json={"code": totp.at(time.time())})
            assert r.status_code == 200, r.text
        return c

    return make
