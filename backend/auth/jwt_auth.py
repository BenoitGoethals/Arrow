from __future__ import annotations

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


def hash_password(plain: str) -> str:
    # bcrypt's 72-byte input limit is enforced by truncating; matches typical app behaviour.
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_cfg.token_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire}
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
    payload = decode_token(token)
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
