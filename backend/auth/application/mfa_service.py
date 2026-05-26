"""MFA use-cases: setup, enable, disable, verify (second step of login)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.audit import log_event
from backend.auth.application.auth_service import AuthResult
from backend.auth.infrastructure import token_service, totp_provider
from backend.storage.models import Operator


def setup(db: Session, *, current: Operator) -> dict:
    """Generate a new TOTP secret. Activated only after /mfa/enable verifies a code."""
    secret = totp_provider.new_secret()
    current.totp_secret = secret
    current.mfa_enabled = False
    db.commit()
    return {
        "secret": secret,
        "uri": totp_provider.provisioning_uri(secret, current.callsign),
        "instructions": "Scan the URI with an authenticator app, then POST /auth/mfa/enable with a valid code.",
    }


def enable(db: Session, *, current: Operator, code: str) -> None:
    if not current.totp_secret:
        raise HTTPException(400, "Call /mfa/setup first")
    if not totp_provider.verify(current.totp_secret, code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid TOTP code")
    current.mfa_enabled = True
    db.commit()
    log_event(db, "MFA_ENABLED", operator_id=current.id)


def disable(db: Session, *, current: Operator, code: str) -> None:
    if not current.mfa_enabled or not current.totp_secret:
        raise HTTPException(400, "MFA is not enabled")
    if not totp_provider.verify(current.totp_secret, code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid TOTP code")
    current.mfa_enabled = False
    current.totp_secret = None
    db.commit()
    log_event(db, "MFA_DISABLED", operator_id=current.id)


def verify_second_step(
    db: Session, *, mfa_session: str, code: str, ip: str | None,
) -> AuthResult:
    try:
        data = token_service.decode_token(mfa_session)
    except HTTPException:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA session")
    if not token_service.is_mfa_pending(data):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA session")

    callsign = data.get("sub", "")
    op = db.query(Operator).filter(Operator.callsign == callsign).first()
    if not op or not op.mfa_enabled or not op.totp_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA not configured")

    if not totp_provider.verify(op.totp_secret, code):
        log_event(db, "MFA_FAIL", outcome="FAILURE", operator_id=op.id, ip_address=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid TOTP code")

    jti = str(uuid.uuid4())
    op.session_jti = jti
    db.commit()
    log_event(db, "LOGIN_SUCCESS", operator_id=op.id, ip_address=ip, detail="via MFA")
    return AuthResult(token_service.create_access_token(op.callsign, op.role, jti=jti), op.role)
