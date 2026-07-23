"""Auth use-cases: register, login, logout.

Receives a Session per call (FastAPI dependency lifecycle), uses the
infrastructure adapters, raises HTTPException at policy boundaries so the
router stays a pass-through.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend import token_blacklist
from backend.audit import log_event
from backend.auth.domain.policies import (
    LOCK_ATTEMPTS,
    LOCK_MINUTES,
    MIN_PASSWORD_LEN,
    VALID_ROLES,
)
from backend.auth.infrastructure import password_hasher, token_service
from backend.storage.models import Operator


@dataclass(frozen=True)
class AuthResult:
    access_token: str | None
    role: str
    mfa_required: bool = False
    mfa_session: str | None = None


# Client/device types we record on the operator so the COP can filter by source.
# Mirrors the set accepted by the tracking endpoint (tracking/router.py); anything
# else is ignored here and left to a later position fix to classify.
_KNOWN_APP_CLIENTS = {"FRONT", "ANDROID"}


def _require_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            422, f"Password must be at least {MIN_PASSWORD_LEN} characters"
        )


def _require_callsign_free(db: Session, callsign: str) -> None:
    if db.query(Operator).filter(Operator.callsign == callsign).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Callsign already taken")


def register_operator(
    db: Session,
    *,
    callsign: str,
    password: str,
    rank: str,
    team_id: int | None,
    ip: str | None,
) -> AuthResult:
    """Self-registration — always OPERATOR regardless of any role hint."""
    _require_password_strength(password)
    _require_callsign_free(db, callsign)

    jti = str(uuid.uuid4())
    op = Operator(
        callsign=callsign,
        rank=rank,
        role="OPERATOR",
        team_id=team_id,
        password_hash=password_hasher.hash_password(password),
        session_jti=jti,
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    log_event(
        db,
        "REGISTER",
        operator_id=op.id,
        resource=f"callsign:{op.callsign}",
        ip_address=ip,
    )
    return AuthResult(
        token_service.create_access_token(op.callsign, op.role, jti=jti), op.role
    )


def register_elevated(
    db: Session,
    *,
    current_id: int,
    callsign: str,
    password: str,
    rank: str,
    role: str,
    team_id: int | None,
    ip: str | None,
) -> AuthResult:
    _require_password_strength(password)
    role_upper = role.upper()
    if role_upper not in VALID_ROLES:
        raise HTTPException(
            422, f"Role must be one of: {', '.join(sorted(VALID_ROLES))}"
        )
    _require_callsign_free(db, callsign)

    jti = str(uuid.uuid4())
    op = Operator(
        callsign=callsign,
        rank=rank,
        role=role_upper,
        team_id=team_id,
        password_hash=password_hasher.hash_password(password),
        session_jti=jti,
        # ADMINs get top clearance so the mission-classification gate can't lock
        # them out; other elevated roles start UNCLASSIFIED (raise via admin PATCH).
        clearance=4 if role_upper == "ADMIN" else 0,
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    log_event(
        db,
        "REGISTER_ELEVATED",
        operator_id=current_id,
        resource=f"callsign:{op.callsign}",
        detail=f"role:{role_upper}",
        ip_address=ip,
    )
    return AuthResult(
        token_service.create_access_token(op.callsign, op.role, jti=jti), op.role
    )


def _check_lockout(op: Operator) -> None:
    if not op.locked_until:
        return
    locked = op.locked_until
    if locked.tzinfo is None:
        locked = locked.replace(tzinfo=timezone.utc)
    if locked > datetime.now(timezone.utc):
        remaining = int((locked - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Account locked. Try again in {remaining} minute(s).",
        )


def _record_failure(
    db: Session, op: Operator | None, username: str, ip: str | None
) -> None:
    if op:
        op.failed_login_count = (op.failed_login_count or 0) + 1
        if op.failed_login_count >= LOCK_ATTEMPTS:
            op.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=LOCK_MINUTES
            )
            log_event(
                db,
                "ACCOUNT_LOCKED",
                outcome="FAILURE",
                operator_id=op.id,
                detail=f"after {op.failed_login_count} failed attempts",
                ip_address=ip,
            )
        db.commit()
    log_event(
        db,
        "LOGIN_FAIL",
        outcome="FAILURE",
        resource=f"callsign:{username}",
        ip_address=ip,
    )


def login(
    db: Session,
    *,
    username: str,
    password: str,
    ip: str | None,
    client: str | None = None,
) -> AuthResult:
    op = db.query(Operator).filter(Operator.callsign == username).first()

    if op:
        _check_lockout(op)

    if not op or not password_hasher.verify_password(password, op.password_hash):
        _record_failure(db, op, username, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad credentials")

    op.failed_login_count = 0
    op.locked_until = None
    db.commit()

    if op.mfa_enabled:
        log_event(db, "LOGIN_MFA_REQUIRED", operator_id=op.id, ip_address=ip)
        return AuthResult(
            None,
            "",
            mfa_required=True,
            mfa_session=token_service.create_mfa_session(op.callsign),
        )

    jti = str(uuid.uuid4())
    op.session_jti = jti
    # Record the device the operator signed in from (from the X-Client-Type header)
    # so the COP categorises them immediately, before any position fix is posted.
    # A later /tracking/position fix overwrites this with its own source.
    _client = (client or "").strip().upper()
    if _client in _KNOWN_APP_CLIENTS:
        op.position_source = _client
    db.commit()
    log_event(db, "LOGIN_SUCCESS", operator_id=op.id, ip_address=ip)
    return AuthResult(
        token_service.create_access_token(op.callsign, op.role, jti=jti), op.role
    )


def logout(db: Session, *, token: str, current: Operator) -> None:
    payload = token_service.decode_token(token)
    jti = payload.get("jti")
    exp = payload.get("exp", 0)
    if jti:
        token_blacklist.revoke(jti, int(exp))
    current.session_jti = None
    db.commit()
    log_event(db, "LOGOUT", operator_id=current.id)
