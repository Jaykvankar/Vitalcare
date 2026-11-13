"""Authentication: PBKDF2-HMAC-SHA-512 passwords, server-side sessions, TOTP (HMAC-SHA-512),
recovery codes, lockout, forced password change, and database-backed rate limiting.

All security state (lockouts, TOTP replay guard, rate-limit counters) lives in the database,
so it survives restarts and is shared by every server process.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta

import pyotp
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import RateLimit, RecoveryCode, Session_, User
from .crypto import decrypt_with_master, encrypt_with_master
from .hashing import hash_password, sha512_hex, verify_password

COOKIE = "rpm_session"
MFA_ROLES = {"admin", "clinician"}
MAX_FAILED = 5
LOCK_MINUTES = 5
RECOVERY_CODES = 10
RECOVERY_ITERATIONS = 20_000  # codes are high-entropy random strings, so fewer iterations suffice
MIN_PASSWORD = 12


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


# ---------------------------------------------------------------- rate limiting

class RateLimiter:
    """Fixed-window counter stored in the database (shared across processes and restarts)."""

    def __init__(self, name: str, limit: int, window_s: int):
        self.name, self.limit, self.window = name, limit, window_s

    def check(self, key: str) -> None:
        window = int(time.time()) // self.window * self.window
        full_key = f"{self.name}:{key}"[:128]
        db = SessionLocal()
        try:
            for _ in range(3):
                res = db.execute(
                    update(RateLimit).where(RateLimit.key == full_key, RateLimit.window_start == window)
                    .values(count=RateLimit.count + 1)
                )
                if res.rowcount == 0:
                    try:
                        db.add(RateLimit(key=full_key, window_start=window, count=1))
                        db.commit()
                        return
                    except IntegrityError:
                        db.rollback()
                        continue
                db.commit()
                count = db.execute(
                    select(RateLimit.count).where(RateLimit.key == full_key, RateLimit.window_start == window)
                ).scalar_one()
                if count > self.limit:
                    raise HTTPException(429, "Too many requests, slow down")
                return
        finally:
            db.close()

    def reset(self) -> None:
        db = SessionLocal()
        try:
            db.execute(delete(RateLimit).where(RateLimit.key.like(f"{self.name}:%")))
            db.commit()
        finally:
            db.close()


login_limiter = RateLimiter("login", limit=10, window_s=60)
mfa_limiter = RateLimiter("mfa", limit=10, window_s=60)
ingest_limiter = RateLimiter("ingest", limit=120, window_s=60)
pair_limiter = RateLimiter("pair", limit=20, window_s=60)
import_limiter = RateLimiter("import", limit=20, window_s=300)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- passwords

def check_password_policy(user: User, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f"Password must be at least {MIN_PASSWORD} characters")
    if user.username.lower() in password.lower():
        raise HTTPException(422, "Password must not contain your username")
    if len(set(password)) < 6:
        raise HTTPException(422, "Password is too repetitive")


def set_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password, get_settings().pbkdf2_iterations)
    user.password_changed_at = _now()
    user.must_change_password = False


# ---------------------------------------------------------------- TOTP

def new_totp_secret() -> str:
    return pyotp.random_base32(length=32)


def totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret, digits=6, interval=30, digest=hashlib.sha512)


def provisioning_uri(user: User, secret: str) -> str:
    return totp(secret).provisioning_uri(name=user.username, issuer_name="SecureRPM")


def store_totp_secret(user: User, secret: str) -> None:
    blob, version = encrypt_with_master(secret.encode(), f"totp:{user.id}")
    user.totp_secret_enc, user.totp_key_version = blob, version


def load_totp_secret(user: User) -> str | None:
    if not user.totp_secret_enc or user.totp_key_version is None:
        return None
    return decrypt_with_master(user.totp_secret_enc, f"totp:{user.id}", user.totp_key_version).decode()


def verify_totp(db: Session, user: User, code: str) -> bool:
    secret = load_totp_secret(user)
    if not secret or not code or not code.isdigit() or len(code) != 6:
        return False
    t = totp(secret)
    now = time.time()
    for drift in (-1, 0, 1):  # allow one 30 s step of clock drift
        step = int(now // 30) + drift
        if secrets.compare_digest(t.at(step * 30), code):
            # Atomic replay guard: only succeeds if this step is newer than the last one used.
            res = db.execute(update(User).where(User.id == user.id, User.totp_last_step < step)
                             .values(totp_last_step=step))
            db.commit()
            return res.rowcount == 1
    return False


# ---------------------------------------------------------------- recovery codes

_RC_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _norm_recovery(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


def issue_recovery_codes(db: Session, user: User) -> list[str]:
    """Replace any existing codes with 10 new ones. Returned once; only hashes are stored."""
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(_RC_ALPHABET) for _ in range(10))  # ~49 bits each
        codes.append(f"{raw[:5]}-{raw[5:]}")
        db.add(RecoveryCode(user_id=user.id, code_hash=hash_password(raw, RECOVERY_ITERATIONS)))
    db.commit()
    return codes


def use_recovery_code(db: Session, user: User, code: str) -> bool:
    raw = _norm_recovery(code)
    if len(raw) != 10:
        return False
    for rc in db.execute(select(RecoveryCode).where(RecoveryCode.user_id == user.id,
                                                    RecoveryCode.used_at.is_(None))).scalars():
        if verify_password(raw, rc.code_hash):
            res = db.execute(update(RecoveryCode).where(RecoveryCode.id == rc.id, RecoveryCode.used_at.is_(None))
                             .values(used_at=_now()))
            db.commit()
            return res.rowcount == 1
    return False


def recovery_codes_left(db: Session, user: User) -> int:
    return len(db.execute(select(RecoveryCode.id).where(RecoveryCode.user_id == user.id,
                                                        RecoveryCode.used_at.is_(None))).all())


# ---------------------------------------------------------------- sessions

def create_session(db: Session, user: User, response: Response, mfa_ok: bool) -> None:
    token = secrets.token_urlsafe(32)
    db.add(Session_(token_hash=sha512_hex(token.encode()), user_id=user.id, mfa_ok=mfa_ok))
    db.commit()
    response.set_cookie(
        COOKIE, token, httponly=True, secure=get_settings().secure_cookies, samesite="strict",
        max_age=get_settings().session_absolute_hours * 3600, path="/",
    )


def _session_from_request(request: Request, db: Session) -> Session_ | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    sess = db.get(Session_, sha512_hex(token.encode()))
    if sess is None or sess.revoked:
        return None
    s = get_settings()
    now = _now()
    if now - _aware(sess.last_seen) > timedelta(minutes=s.session_idle_minutes) or \
            now - _aware(sess.created_at) > timedelta(hours=s.session_absolute_hours):
        sess.revoked = True
        db.commit()
        return None
    return sess


def destroy_session(request: Request, db: Session, response: Response) -> None:
    sess = _session_from_request(request, db)
    if sess:
        sess.revoked = True
        db.commit()
    response.delete_cookie(COOKIE, path="/")


def revoke_other_sessions(db: Session, user: User, keep: Session_ | None) -> None:
    q = update(Session_).where(Session_.user_id == user.id, Session_.revoked.is_(False))
    if keep is not None:
        q = q.where(Session_.token_hash != keep.token_hash)
    db.execute(q.values(revoked=True))
    db.commit()


def pending_user(request: Request, db: Session = Depends(get_db)) -> tuple[User, Session_]:
    """Logged in with password, MFA may still be outstanding."""
    sess = _session_from_request(request, db)
    if sess is None:
        raise HTTPException(401, "Not signed in")
    user = db.get(User, sess.user_id)
    if user is None or not user.active:
        raise HTTPException(401, "Not signed in")
    return user, sess


def authenticated(request: Request, db: Session = Depends(get_db)) -> tuple[User, Session_]:
    """Password + MFA done; a forced password change may still be outstanding."""
    user, sess = pending_user(request, db)
    if user.role in MFA_ROLES and not sess.mfa_ok:
        raise HTTPException(401, "Multi-factor authentication required")
    sess.last_seen = _now()
    db.commit()
    return user, sess


def current_user(pair: tuple[User, Session_] = Depends(authenticated)) -> User:
    user, _ = pair
    if user.must_change_password:
        raise HTTPException(403, "Password change required")
    return user


def require_role(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Not allowed for your role")
        return user
    return dep


# ---------------------------------------------------------------- lockout

def is_locked(user: User) -> bool:
    return user.locked_until is not None and _aware(user.locked_until) > _now()


def register_failure(db: Session, user: User) -> None:
    user.failed_logins += 1
    if user.failed_logins >= MAX_FAILED:
        user.locked_until = _now() + timedelta(minutes=LOCK_MINUTES)
        user.failed_logins = 0
    db.commit()


def register_success(db: Session, user: User) -> None:
    user.failed_logins = 0
    user.locked_until = None
    db.commit()


def find_user(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username.strip().lower())).scalar_one_or_none()
