from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import (
    create_access_token,
    get_current_operator,
    hash_password,
    verify_password,
)
from backend.storage.database import get_db
from backend.storage.models import Operator

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class RegisterIn(BaseModel):
    callsign: str
    password: str
    rank: str    = "OR-1"
    role: str    = "OPERATOR"
    team_id: int | None = None   # assign directly at creation — no separate PATCH needed


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    if len(payload.password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Password must be at least 8 characters")
    if db.query(Operator).filter(Operator.callsign == payload.callsign).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Callsign already taken")

    op = Operator(
        callsign=payload.callsign,
        rank=payload.rank,
        role=payload.role,
        team_id=payload.team_id,
        password_hash=hash_password(payload.password),
    )
    db.add(op)
    db.commit()
    db.refresh(op)

    return TokenOut(access_token=create_access_token(op.callsign, op.role), role=op.role)


@router.post("/login", response_model=TokenOut)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenOut:
    op = db.query(Operator).filter(Operator.callsign == form.username).first()
    if not op or not verify_password(form.password, op.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad credentials")
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
