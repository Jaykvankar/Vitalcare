"""Account and device provisioning shared by the admin API and the seed script."""
from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Device, Patient, User
from .security import crypto
from .security.hashing import hash_password

ROLES = ("admin", "clinician", "patient")


def create_user(db: Session, *, username: str, full_name: str, role: str, password: str,
                dob: str | None = None, phone: str | None = None, address: str | None = None) -> User:
    if role not in ROLES:
        raise ValueError("invalid role")
    user = User(username=username.strip().lower(), full_name=full_name.strip(), role=role,
                password_hash=hash_password(password, get_settings().pbkdf2_iterations))
    db.add(user)
    db.flush()
    if role == "patient":
        patient = Patient(user_id=user.id, wrapped_dek=b"", key_version=0)
        db.add(patient)
        db.flush()
        dek = crypto.new_dek()
        patient.wrapped_dek, patient.key_version = crypto.wrap_dek(dek, patient.id)
        patient.dob_enc = crypto.encrypt_field(dek, dob, patient_id=patient.id, field="dob")
        patient.phone_enc = crypto.encrypt_field(dek, phone, patient_id=patient.id, field="phone")
        patient.address_enc = crypto.encrypt_field(dek, address, patient_id=patient.id, field="address")
    db.commit()
    db.refresh(user)
    return user


def register_device(db: Session, *, patient_id: int, label: str, public_key_pem: str,
                    device_id: str | None = None) -> Device:
    device = Device(id=device_id or f"dev-{secrets.token_hex(6)}", patient_id=patient_id, label=label,
                    public_key_pem=public_key_pem)
    db.add(device)
    db.commit()
    return device


def provision_simulated_device(db: Session, patient_id: int, label: str) -> Device:
    """The simulator generates the key pair; the server stores only the public key."""
    from .simulator import runner

    device_id = f"dev-{secrets.token_hex(6)}"
    public_pem = runner.keystore.create_device(device_id, patient_id)
    return register_device(db, patient_id=patient_id, label=label, public_key_pem=public_pem, device_id=device_id)
