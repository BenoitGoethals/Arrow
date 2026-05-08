from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend import token_blacklist
from backend.audit import log_event
from backend.auth.jwt_auth import (
    create_access_token,
    create_mfa_session,
    decode_token,
    get_current_operator,
    hash_password,
    oauth2_scheme,
    require_role,
    verify_password,
)
from backend.limiter import limiter
from backend.storage.database import get_db
from backend.storage.models import Operator

router = APIRouter(prefix="/auth", tags=["auth"])

_VALID_ROLES   = {"OPERATOR", "BATTLE_CAPTAIN", "ADMIN"}
_LOCK_ATTEMPTS = 5
_LOCK_MINUTES  = 15


# ── Schemas ───────────────────────────────────────────────────────────────────

class TokenOut(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    role: str = ""
    mfa_required: bool = False
    mfa_session: str | None = None


class RegisterIn(BaseModel):
    callsign: str
    password: str
    rank: str    = "OR-1"
    role: str    = "OPERATOR"
    team_id: int | None = None


class MfaVerifyIn(BaseModel):
    mfa_session: str
    code: str


class MfaCodeIn(BaseModel):
    code: str


# ── Registration ──────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def register(request: Request, payload: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    """Self-registration — always creates OPERATOR regardless of role field."""
    ip = request.client.host if request.client else None
    if len(payload.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    if db.query(Operator).filter(Operator.callsign == payload.callsign).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Callsign already taken")

    op = Operator(callsign=payload.callsign, rank=payload.rank, role="OPERATOR",
                  team_id=payload.team_id, password_hash=hash_password(payload.password))
    db.add(op); db.commit(); db.refresh(op)
    log_event(db, "REGISTER", operator_id=op.id,
              resource=f"callsign:{op.callsign}", ip_address=ip)
    return TokenOut(access_token=create_access_token(op.callsign, op.role), role=op.role)


@router.post("/register/admin", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register_elevated(
    request: Request,
    payload: RegisterIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN")),
) -> TokenOut:
    """Admin-only: create an operator with any valid role."""
    ip = request.client.host if request.client else None
    if len(payload.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    role = payload.role.upper()
    if role not in _VALID_ROLES:
        raise HTTPException(422, f"Role must be one of: {', '.join(_VALID_ROLES)}")
    if db.query(Operator).filter(Operator.callsign == payload.callsign).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Callsign already taken")

    op = Operator(callsign=payload.callsign, rank=payload.rank, role=role,
                  team_id=payload.team_id, password_hash=hash_password(payload.password))
    db.add(op); db.commit(); db.refresh(op)
    log_event(db, "REGISTER_ELEVATED", operator_id=current.id,
              resource=f"callsign:{op.callsign}", detail=f"role:{role}", ip_address=ip)
    return TokenOut(access_token=create_access_token(op.callsign, op.role), role=op.role)


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenOut:
    ip = request.client.host if request.client else None
    op = db.query(Operator).filter(Operator.callsign == form.username).first()

    # Account lockout check
    if op and op.locked_until:
        locked = op.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        if locked > datetime.now(timezone.utc):
            remaining = int((locked - datetime.now(timezone.utc)).total_seconds() / 60) + 1
            raise HTTPException(status.HTTP_423_LOCKED,
                                f"Account locked. Try again in {remaining} minute(s).")

    if not op or not verify_password(form.password, op.password_hash):
        if op:
            op.failed_login_count = (op.failed_login_count or 0) + 1
            if op.failed_login_count >= _LOCK_ATTEMPTS:
                op.locked_until = datetime.now(timezone.utc) + timedelta(minutes=_LOCK_MINUTES)
                log_event(db, "ACCOUNT_LOCKED", outcome="FAILURE", operator_id=op.id,
                          detail=f"after {op.failed_login_count} failed attempts", ip_address=ip)
            db.commit()
        log_event(db, "LOGIN_FAIL", outcome="FAILURE",
                  resource=f"callsign:{form.username}", ip_address=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad credentials")

    # Success — reset lockout counter
    op.failed_login_count = 0
    op.locked_until = None
    db.commit()

    # MFA required?
    if op.mfa_enabled:
        log_event(db, "LOGIN_MFA_REQUIRED", operator_id=op.id, ip_address=ip)
        return TokenOut(mfa_required=True, mfa_session=create_mfa_session(op.callsign))

    log_event(db, "LOGIN_SUCCESS", operator_id=op.id, ip_address=ip)
    return TokenOut(access_token=create_access_token(op.callsign, op.role), role=op.role)


# ── MFA ───────────────────────────────────────────────────────────────────────

@router.post("/mfa/verify", response_model=TokenOut)
@limiter.limit("5/minute")
def mfa_verify(request: Request, payload: MfaVerifyIn,
               db: Session = Depends(get_db)) -> TokenOut:
    """Second step of login when MFA is enabled."""
    try:
        data = decode_token(payload.mfa_session)
    except HTTPException:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA session")
    if not data.get("mfa_pending"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA session")

    callsign = data.get("sub", "")
    op = db.query(Operator).filter(Operator.callsign == callsign).first()
    if not op or not op.mfa_enabled or not op.totp_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA not configured")

    totp = pyotp.TOTP(op.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        ip = request.client.host if request.client else None
        log_event(db, "MFA_FAIL", outcome="FAILURE", operator_id=op.id, ip_address=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid TOTP code")

    ip = request.client.host if request.client else None
    log_event(db, "LOGIN_SUCCESS", operator_id=op.id, ip_address=ip, detail="via MFA")
    return TokenOut(access_token=create_access_token(op.callsign, op.role), role=op.role)


@router.post("/mfa/setup")
def mfa_setup(current: Operator = Depends(get_current_operator),
              db: Session = Depends(get_db)) -> dict:
    """Generate a new TOTP secret and provisioning URI. Call /mfa/enable to activate."""
    secret = pyotp.random_base32()
    current.totp_secret = secret
    current.mfa_enabled = False          # not active until verified
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=current.callsign, issuer_name="Arrow Tactical")
    return {"secret": secret, "uri": uri,
            "instructions": "Scan the URI with an authenticator app, then POST /auth/mfa/enable with a valid code."}


@router.post("/mfa/enable", status_code=status.HTTP_204_NO_CONTENT)
def mfa_enable(payload: MfaCodeIn, current: Operator = Depends(get_current_operator),
               db: Session = Depends(get_db)) -> None:
    """Activate MFA after verifying the first TOTP code from the authenticator app."""
    if not current.totp_secret:
        raise HTTPException(400, "Call /mfa/setup first")
    if not pyotp.TOTP(current.totp_secret).verify(payload.code, valid_window=1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid TOTP code")
    current.mfa_enabled = True
    db.commit()
    log_event(db, "MFA_ENABLED", operator_id=current.id)


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
def mfa_disable(payload: MfaCodeIn, current: Operator = Depends(get_current_operator),
                db: Session = Depends(get_db)) -> None:
    """Disable MFA after confirming with a valid TOTP code."""
    if not current.mfa_enabled or not current.totp_secret:
        raise HTTPException(400, "MFA is not enabled")
    if not pyotp.TOTP(current.totp_secret).verify(payload.code, valid_window=1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid TOTP code")
    current.mfa_enabled = False
    current.totp_secret = None
    db.commit()
    log_event(db, "MFA_DISABLED", operator_id=current.id)


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(token: str = Depends(oauth2_scheme),
           db: Session = Depends(get_db),
           current: Operator = Depends(get_current_operator)) -> None:
    """Revoke the current JWT immediately (adds jti to blacklist)."""
    payload = decode_token(token)
    jti = payload.get("jti")
    exp = payload.get("exp", 0)
    if jti:
        token_blacklist.revoke(jti, int(exp))
    log_event(db, "LOGOUT", operator_id=current.id)


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me")
def me(current: Operator = Depends(get_current_operator)) -> dict:
    return {
        "id":         current.id,
        "callsign":   current.callsign,
        "rank":       current.rank,
        "role":       current.role,
        "status":     current.status,
        "team_id":    current.team_id,
        "mfa_enabled": current.mfa_enabled,
    }
