"""Pydantic schemas for the /auth endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class TokenOut(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    role: str = ""
    mfa_required: bool = False
    mfa_session: str | None = None


class RegisterIn(BaseModel):
    callsign: str
    password: str
    rank: str = "OR-1"
    role: str = "OPERATOR"
    team_id: int | None = None


class MfaVerifyIn(BaseModel):
    mfa_session: str
    code: str


class MfaCodeIn(BaseModel):
    code: str
