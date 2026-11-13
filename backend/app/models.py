from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # admin | clinician | patient
    password_hash: Mapped[str] = mapped_column(String(256))
    # TOTP secret, AES-256-GCM encrypted under the master key (never stored in the clear)
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    totp_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient: Mapped[Patient | None] = relationship(back_populates="user", uselist=False)


class Session_(Base):
    __tablename__ = "sessions"
    # SHA-512 of the random cookie token: a stolen DB does not reveal live session cookies
    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mfa_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    # Per-patient AES-256 data key (DEK), wrapped with AES-256-GCM under master key `key_version`
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer)
    # PII encrypted with the patient's DEK
    dob_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    address_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    consent_active: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Rolling baseline (EWMA mean/var + previous reading) for ML features, encrypted with the DEK
    state_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Latest scoring summary (no vital values, only band/score/reason codes)
    last_band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="patient")


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("clinician_id", "patient_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinician_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    # The server stores the device's RSA *public* key only
    public_key_pem: Mapped[str] = mapped_column(Text)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    paired_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PairingCode(Base):
    """One-time device pairing code. The code itself is stored AES-GCM encrypted under the master key."""
    __tablename__ = "pairing_codes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    code_enc: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Reading(Base):
    __tablename__ = "readings"
    __table_args__ = (
        Index("ix_readings_patient_ts", "patient_id", "ts"),
        UniqueConstraint("device_id", "seq"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    seq: Mapped[int] = mapped_column(BigInteger)
    ts: Mapped[int] = mapped_column(BigInteger)  # unix seconds
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)  # AES-256-GCM(vitals JSON) under patient DEK
    band: Mapped[str] = mapped_column(String(16))  # normal | warning | critical
    risk_score: Mapped[float] = mapped_column(Float)
    reason_codes: Mapped[str] = mapped_column(String(256), default="")


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    reason_code: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | acknowledged
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ack_note_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(String(40))  # ISO-8601, part of the hashed content
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48))
    target: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    prev_hash: Mapped[str] = mapped_column(String(128))
    hash: Mapped[str] = mapped_column(String(128))


class AuditCheckpoint(Base):
    __tablename__ = "audit_checkpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_audit_id: Mapped[int] = mapped_column(Integer)
    head_hash: Mapped[str] = mapped_column(String(128))
    signature: Mapped[bytes] = mapped_column(LargeBinary)  # ECDSA P-384 / SHA-512
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
