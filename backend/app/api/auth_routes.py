from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Session_, User
from ..security import audit, auth
from ..security.hashing import burn_password_time, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MfaIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)  # 6-digit TOTP or XXXXX-XXXXX recovery code


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def user_out(db: Session, u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
            "patient_id": u.patient.id if u.patient else None,
            "must_change_password": u.must_change_password,
            "recovery_codes_left": auth.recovery_codes_left(db, u) if u.role in auth.MFA_ROLES else None}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    ip = auth.client_ip(request)
    auth.login_limiter.check(ip)
    user = auth.find_user(db, body.username.strip())   # usernames never contain spaces; passwords are used exactly
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
        return {"mfa": "none", "user": user_out(db, user)}
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
    code = body.code.strip()
    method = "totp"
    ok = auth.verify_totp(db, user, code)
    if not ok and user.totp_confirmed and not code.isdigit():
        ok = auth.use_recovery_code(db, user, code)
        method = "recovery_code"
    if not ok:
        auth.register_failure(db, user)
        audit.append("mfa_failed", actor_id=user.id, actor=user.username)
        raise HTTPException(401, "Invalid code")
    recovery_codes = None
    if not user.totp_confirmed:
        user.totp_confirmed = True
        recovery_codes = auth.issue_recovery_codes(db, user)
        audit.append("mfa_enrolled", actor_id=user.id, actor=user.username)
    sess.mfa_ok = True
    auth.register_success(db, user)
    db.commit()
    audit.append("login", actor_id=user.id, actor=user.username,
                 detail=f"ip={auth.client_ip(request)} mfa={method}")
    return {"user": user_out(db, user), "recovery_codes": recovery_codes}


@router.post("/password")
def change_password(body: PasswordIn, pair: tuple[User, Session_] = Depends(auth.authenticated),
                    db: Session = Depends(get_db)) -> dict:
    user, sess = pair
    if not verify_password(body.current_password, user.password_hash):
        auth.register_failure(db, user)
        raise HTTPException(401, "Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(422, "New password must be different")
    auth.check_password_policy(user, body.new_password)
    auth.set_password(user, body.new_password)
    db.commit()
    auth.revoke_other_sessions(db, user, keep=sess)
    audit.append("password_changed", actor_id=user.id, actor=user.username)
    return {"user": user_out(db, user)}


@router.post("/recovery-codes")
def regenerate_recovery_codes(user: User = Depends(auth.require_role("admin", "clinician")),
                              db: Session = Depends(get_db)) -> dict:
    codes = auth.issue_recovery_codes(db, user)
    audit.append("recovery_codes_regenerated", actor_id=user.id, actor=user.username)
    return {"recovery_codes": codes}


# Demo helpers answer only callers on this machine. "testclient" is the in-process test client's name; it can never
# be a network address. run_server.py also refuses to start demo mode on a non-local address.
LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def is_local(request: Request) -> bool:
    return request.client is not None and request.client.host in LOCAL_CLIENTS


@router.get("/demo-accounts")
def demo_accounts(request: Request, db: Session = Depends(get_db)) -> dict:
    """Demo helper for the sign-in page's "Try a role" buttons.

    Only in demo mode. The readable password from seed_credentials.txt is included so the sign-in page can fill
    it in. The database stores only the PBKDF2 hash, and TOTP secrets and recovery codes stay in the file.
    """
    import os

    from sqlalchemy import select

    from ..config import PROJECT_DIR, get_settings
    from ..seed import previous_passwords

    if not get_settings().demo_mode or not is_local(request):
        return {"demo": False, "accounts": []}
    passwords = previous_passwords(os.environ.get("RPM_SEED_CREDENTIALS", str(PROJECT_DIR / "seed_credentials.txt")))
    users = db.scalars(select(User).where(User.demo_account.is_(True), User.active.is_(True)).order_by(User.id)).all()
    accounts = []
    for u in users:
        row = {"username": u.username, "role": u.role, "full_name": u.full_name}
        if u.username in passwords:
            row["password"] = passwords[u.username]
        accounts.append(row)
    return {"demo": True, "accounts": accounts}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    auth.destroy_session(request, db, response)
    return {"ok": True}


@router.get("/me")
def me(pair: tuple[User, Session_] = Depends(auth.authenticated), db: Session = Depends(get_db)) -> dict:
    return user_out(db, pair[0])
