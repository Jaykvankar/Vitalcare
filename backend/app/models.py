from __future__ import annotations

from datetime import UTC, datetime

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


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
    # Last TOTP time-step accepted (replay guard, shared by all server processes)
    totp_last_step: Mapped[int] = mapped_column(BigInteger, default=0)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # Created by the demo seed. Only such accounts may see the on-screen demo code, and only in demo mode.
    demo_account: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    # Latest band and AI score: AES-256-GCM under the DEK (security/labels.py). The clear columns below are only
    # read for rows written before migration 0005 and are always NULL now.
    last_status_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    last_band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Crypto-shredding: when set, the wrapped DEK has been destroyed and all ciphertext is unreadable
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    kind: Mapped[str] = mapped_column(String(16), default="device")  # device | import (historical upload batch)
    # Catalog id from app/device_catalog.py (e.g. "pulse_oximeter"); a plain-language label, not used by crypto
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    # AES-256-GCM under the patient DEK: vitals, NEWS2, band, AI risk and reason codes (security/labels.py)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    # Legacy clear labels: only rows written before migration 0005; NULL for every new reading.
    band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason_codes: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ReadingRollup(Base):
    """5-minute aggregate of a patient's readings, AES-256-GCM encrypted under the patient DEK.

    Lets 24 h / 7 d charts decrypt a few hundred rollups instead of every raw reading.
    """
    __tablename__ = "reading_rollups"
    __table_args__ = (UniqueConstraint("patient_id", "bucket_ts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    bucket_ts: Mapped[int] = mapped_column(BigInteger)
    blob: Mapped[bytes] = mapped_column(LargeBinary)  # includes the bucket's worst band
    worst_band: Mapped[str | None] = mapped_column(String(16), nullable=True)  # legacy only (before 0005)


class Alert(Base):
    __tablename__ = "alerts"
    # At most one OPEN alert per patient and reason, enforced by the database on the blind index (reason_tag),
    # so the rule holds without the reason being readable (security/labels.py).
    __table_args__ = (
        Index("uq_alert_open_tag", "patient_id", "reason_tag", unique=True,
              sqlite_where=text("status = 'open'"), postgresql_where=text("status = 'open'")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    reason_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)   # HMAC-SHA-512 blind index
    details_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # AES-GCM {reason_code, severity}
    reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)   # legacy only (before 0005)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)      # legacy only (before 0005)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | acknowledged
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ack_note_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(String(40))  # ISO-8601, part of the hashed content
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48))
    target: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    # Unique: two writers can never both append after the same row, so the chain cannot fork.
    prev_hash: Mapped[str] = mapped_column(String(128), unique=True)
    hash: Mapped[str] = mapped_column(String(128))


class AuditCheckpoint(Base):
    __tablename__ = "audit_checkpoints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_audit_id: Mapped[int] = mapped_column(Integer, unique=True)
    head_hash: Mapped[str] = mapped_column(String(128))
    signature: Mapped[bytes] = mapped_column(LargeBinary)  # ECDSA P-384 / SHA-512
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecoveryCode(Base):
    """One-time MFA recovery codes, stored only as PBKDF2-HMAC-SHA-512 hashes."""
    __tablename__ = "recovery_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(256))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RateLimit(Base):
    """Fixed-window request counters shared by all server processes."""
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    window_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class ImportBatch(Base):
    """Record of a bulk import (people or historical vitals)."""
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # people | vitals
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rows: Mapped[int] = mapped_column(Integer)
    sha512: Mapped[str] = mapped_column(String(128))  # digest of the uploaded file
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True)
