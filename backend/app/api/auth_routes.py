from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import audit, auth
from ..security.hashing import burn_password_time, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MfaIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
            "patient_id": u.patient.id if u.patient else None}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    ip = auth.client_ip(request)
    auth.login_limiter.check(ip)
    user = auth.find_user(db, body.username)
    generic = HTTPException(401, "Invalid username or password")
    if user is None or not user.active:
        burn_password_time(body.password)
        audit.append("login_failed", actor=body.username[:64], detail=f"ip={ip} unknown user")
        raise generic
    if auth.is_locked(user):
        audit.append("login_blocked", actor_id=user.id, actor=user.username, detail=f"ip={ip} locked")
        raise HTTPException(423, "Account temporarily locked after repeated failures. Try again later.")
    if not verify_password(body.password, user.password_hash):
        auth.register_failure(db, user)
        audit.append("login_failed", actor_id=user.id, actor=user.username, detail=f"ip={ip}")
        raise generic

    auth.register_success(db, user)
    needs_mfa = user.role in auth.MFA_ROLES
    auth.create_session(db, user, response, mfa_ok=not needs_mfa)
    if not needs_mfa:
        audit.append("login", actor_id=user.id, actor=user.username, detail=f"ip={ip}")
        return {"mfa": "none", "user": user_out(user)}
    if user.totp_confirmed:
        return {"mfa": "verify"}
    # First login for an MFA role: enrol an authenticator.
    secret = auth.new_totp_secret()
    auth.store_totp_secret(user, secret)
    db.commit()
    return {"mfa": "enroll", "otpauth_uri": auth.provisioning_uri(user, secret), "secret": secret}


@router.post("/mfa")
def mfa(body: MfaIn, request: Request, db: Session = Depends(get_db)) -> dict:
    user, sess = auth.pending_user(request, db)
    auth.mfa_limiter.check(f"{user.id}")
    if not auth.verify_totp(user, body.code):
        auth.register_failure(db, user)
        audit.append("mfa_failed", actor_id=user.id, actor=user.username)
        raise HTTPException(401, "Invalid code")
    if not user.totp_confirmed:
        user.totp_confirmed = True
        audit.append("mfa_enrolled", actor_id=user.id, actor=user.username)
    sess.mfa_ok = True
    auth.register_success(db, user)
    db.commit()
    audit.append("login", actor_id=user.id, actor=user.username, detail=f"ip={auth.client_ip(request)} mfa=totp")
    return {"user": user_out(user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    auth.destroy_session(request, db, response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(auth.current_user)) -> dict:
    return user_out(user)
