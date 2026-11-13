"""Authentication: PBKDF2-HMAC-SHA-512 passwords, server-side sessions, TOTP (HMAC-SHA-512), lockout."""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Session_, User
from .crypto import decrypt_with_master, encrypt_with_master
from .hashing import sha512_hex

COOKIE = "rpm_session"
MFA_ROLES = {"admin", "clinician"}
MAX_FAILED = 5
LOCK_MINUTES = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------- rate limiting

class RateLimiter:
    """Sliding-window limiter kept in memory (single-process demo)."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(429, "Too many requests, slow down")
            q.append(now)


login_limiter = RateLimiter(limit=10, window_s=60)
mfa_limiter = RateLimiter(limit=10, window_s=60)
ingest_limiter = RateLimiter(limit=120, window_s=60)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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
    if not user.totp_secret_enc:
        return None
    return decrypt_with_master(user.totp_secret_enc, f"totp:{user.id}", user.totp_key_version).decode()


_last_totp_step: dict[int, int] = {}


def verify_totp(user: User, code: str) -> bool:
    secret = load_totp_secret(user)
    if not secret or not code or not code.isdigit():
        return False
    t = totp(secret)
    now = time.time()
    for drift in (-1, 0, 1):  # allow one 30 s step of clock drift
        step = int(now // 30) + drift
        if secrets.compare_digest(t.at(step * 30), code):
            if _last_totp_step.get(user.id, -1) >= step:
                return False  # code already used: block replay
            _last_totp_step[user.id] = step
            return True
    return False


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


def pending_user(request: Request, db: Session = Depends(get_db)) -> tuple[User, Session_]:
    """Logged in with password, MFA may still be outstanding."""
    sess = _session_from_request(request, db)
    if sess is None:
        raise HTTPException(401, "Not signed in")
    user = db.get(User, sess.user_id)
    if user is None or not user.active:
        raise HTTPException(401, "Not signed in")
    return user, sess


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user, sess = pending_user(request, db)
    if user.role in MFA_ROLES and not sess.mfa_ok:
        raise HTTPException(401, "Multi-factor authentication required")
    sess.last_seen = _now()
    db.commit()
    return user


def require_role(*roles: str):  # noqa: ANN201
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Not allowed for your role")
        return user
    return dep


# ---------------------------------------------------------------- lockout

def is_locked(user: User) -> bool:
    lu = _aware(user.locked_until)
    return lu is not None and lu > _now()


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
