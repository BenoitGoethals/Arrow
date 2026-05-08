from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.audit import log_event
from backend.auth.jwt_auth import (
    create_access_token,
    get_current_operator,
    hash_password,
    require_role,
    verify_password,
)
from backend.storage.database import get_db
from backend.storage.models import Operator

router = APIRouter(prefix="/auth", tags=["auth"])

_VALID_ROLES = {"OPERATOR", "BATTLE_CAPTAIN", "ADMIN"}
_ELEVATED_ROLES = {"BATTLE_CAPTAIN", "ADMIN"}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class RegisterIn(BaseModel):
    callsign: str
    password: str
    rank: str    = "OR-1"
    role: str    = "OPERATOR"
    team_id: int | None = None


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    """Self-registration — always creates an OPERATOR. Role field is ignored."""
    ip = request.client.host if request.client else None
    if len(payload.password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Password must be at least 8 characters")
    if db.query(Operator).filter(Operator.callsign == payload.callsign).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Callsign already taken")

    op = Operator(
        callsign=payload.callsign,
        rank=payload.rank,
        role="OPERATOR",
        team_id=payload.team_id,
        password_hash=hash_password(payload.password),
    )
    db.add(op)
    db.commit()
    db.refresh(op)

    log_event(db, "REGISTER", operator_id=op.id,
              resource=f"callsign:{op.callsign}", ip_address=ip)
    return TokenOut(access_token=create_access_token(op.callsign, op.role), role=op.role)


@router.post("/register/admin", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register_elevated(
    payload: RegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN")),
) -> TokenOut:
    """Admin-only: create an operator with any role (BATTLE_CAPTAIN, ADMIN, OPERATOR)."""
    ip = request.client.host if request.client else None
    if len(payload.password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Password must be at least 8 characters")
    role = payload.role.upper()
    if role not in _VALID_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Invalid role. Must be one of: {', '.join(_VALID_ROLES)}")
    if db.query(Operator).filter(Operator.callsign == payload.callsign).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Callsign already taken")

    op = Operator(
        callsign=payload.callsign,
        rank=payload.rank,
        role=role,
        team_id=payload.team_id,
        password_hash=hash_password(payload.password),
    )
    db.add(op)
    db.commit()
    db.refresh(op)

    log_event(db, "REGISTER_ELEVATED", operator_id=current.id,
              resource=f"callsign:{op.callsign}",
              detail=f"role:{role}", ip_address=ip)
    return TokenOut(access_token=create_access_token(op.callsign, op.role), role=op.role)


@router.post("/login", response_model=TokenOut)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db),
) -> TokenOut:
    ip = request.client.host if (request and request.client) else None
    op = db.query(Operator).filter(Operator.callsign == form.username).first()
    if not op or not verify_password(form.password, op.password_hash):
        log_event(db, "LOGIN_FAIL", outcome="FAILURE",
                  resource=f"callsign:{form.username}", ip_address=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad credentials")
    log_event(db, "LOGIN_SUCCESS", operator_id=op.id, ip_address=ip)
    return TokenOut(access_token=create_access_token(op.callsign, op.role), role=op.role)


@router.get("/me")
def me(current: Operator = Depends(get_current_operator)) -> dict:
    return {
        "id": current.id,
        "callsign": current.callsign,
        "rank": current.rank,
        "role": current.role,
        "status": current.status,
        "team_id": current.team_id,
    }
