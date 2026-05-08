from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.config.xml_config import load_config
from backend.storage.database import get_db
from backend.storage.models import Operator

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
_cfg = load_config().auth

_MFA_PENDING = "mfa_pending"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_cfg.token_expire_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _cfg.secret, algorithm=_cfg.algorithm)


def create_mfa_session(subject: str) -> str:
    """Short-lived (5 min) token used during the MFA second-step only."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "sub": subject,
        _MFA_PENDING: True,
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _cfg.secret, algorithm=_cfg.algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _cfg.secret, algorithms=[_cfg.algorithm])
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc


def get_current_operator(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Operator:
    from backend import token_blacklist

    payload = decode_token(token)

    # Reject MFA session tokens — they may not be used for API access
    if payload.get(_MFA_PENDING):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA verification required")

    # Reject revoked tokens
    jti = payload.get("jti")
    if jti and token_blacklist.is_revoked(jti):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")

    callsign = payload.get("sub")
    if not callsign:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    op = db.query(Operator).filter(Operator.callsign == callsign).first()
    if not op:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Operator not found")
    return op


def require_role(*roles: str):
    def _dep(op: Operator = Depends(get_current_operator)) -> Operator:
        if op.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return op

    return _dep
