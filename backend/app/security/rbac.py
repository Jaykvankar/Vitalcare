"""Authorization: who may decrypt which patient's data.

- patient   : only their own record
- clinician : only patients assigned to them
- admin     : manages accounts, never decrypts clinical data
Revoked consent blocks every decrypt (and ingest).
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assignment, Patient, User


def can_access_patient(db: Session, user: User, patient: Patient) -> bool:
    if user.role == "patient":
        return patient.user_id == user.id
    if user.role == "clinician":
        return db.execute(
            select(Assignment.id).where(
                Assignment.clinician_id == user.id, Assignment.patient_id == patient.id
            )
        ).first() is not None
    return False


def patient_for_read(db: Session, user: User, patient_id: int, *, need_consent: bool = True) -> Patient:
    patient = db.get(Patient, patient_id)
    # Same 404 whether the patient does not exist or is not yours: no ID probing.
    if patient is None or not can_access_patient(db, user, patient):
        raise HTTPException(404, "Patient not found")
    if patient.erased_at is not None:
        raise HTTPException(410, "This patient's record has been erased")
    # Consent governs processing/sharing by others; patients can always see their own record.
    if need_consent and user.role != "patient" and not patient.consent_active:
        raise HTTPException(403, "Patient has revoked consent for data processing")
    return patient
