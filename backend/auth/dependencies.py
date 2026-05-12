"""FastAPI dependencies for protected routes.

`get_current_operator` resolves a JWT to a DB-loaded Operator; `require_role`
wraps it with a role check. Routers should depend on one of these — never
decode tokens directly.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.auth.infrastructure import token_service
from backend.storage.database import get_db
from backend.storage.models import Operator

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_operator(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Operator:
    from backend import token_blacklist

    payload = token_service.decode_token(token)

    if token_service.is_mfa_pending(payload):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA verification required")

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
