"""JWT issuance and decoding.

`_cfg` is loaded at import time, matching the pre-refactor behavior — when
config.xml changes during development, restart the process.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt

from backend.auth.domain.policies import MFA_SESSION_MINUTES
from backend.config.xml_config import load_config

_cfg = load_config().auth

_MFA_PENDING = "mfa_pending"


def create_access_token(subject: str, role: str, jti: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_cfg.token_expire_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "jti": jti or str(uuid.uuid4()),
    }
    return jwt.encode(payload, _cfg.secret, algorithm=_cfg.algorithm)


def create_mfa_session(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=MFA_SESSION_MINUTES)
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


def is_mfa_pending(payload: dict) -> bool:
    return bool(payload.get(_MFA_PENDING))
