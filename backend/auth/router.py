"""FastAPI router for /auth — presentation only, delegates to services."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend.auth.application import auth_service, mfa_service
from backend.auth.application.auth_service import AuthResult
from backend.auth.dependencies import get_current_operator, oauth2_scheme, require_role
from backend.auth.schemas import MfaCodeIn, MfaVerifyIn, RegisterIn, TokenOut
from backend.limiter import limiter
from backend.storage.database import get_db
from backend.storage.models import Operator

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _token_out(result: AuthResult) -> TokenOut:
    return TokenOut(
        access_token=result.access_token,
        role=result.role,
        mfa_required=result.mfa_required,
        mfa_session=result.mfa_session,
    )


# ── Registration ──────────────────────────────────────────────────────────────


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
def register(
    request: Request, payload: RegisterIn, db: Session = Depends(get_db)
) -> TokenOut:
    result = auth_service.register_operator(
        db,
        callsign=payload.callsign,
        password=payload.password,
        rank=payload.rank,
        team_id=payload.team_id,
        ip=_client_ip(request),
    )
    return _token_out(result)


@router.post(
    "/register/admin", response_model=TokenOut, status_code=status.HTTP_201_CREATED
)
def register_elevated(
    request: Request,
    payload: RegisterIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN")),
) -> TokenOut:
    result = auth_service.register_elevated(
        db,
        current_id=current.id,
        callsign=payload.callsign,
        password=payload.password,
        rank=payload.rank,
        role=payload.role,
        team_id=payload.team_id,
        ip=_client_ip(request),
    )
    return _token_out(result)


# ── Login ─────────────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenOut)
@limiter.limit("120/minute")
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenOut:
    result = auth_service.login(
        db,
        username=form.username,
        password=form.password,
        ip=_client_ip(request),
    )
    return _token_out(result)


# ── MFA ───────────────────────────────────────────────────────────────────────


@router.post("/mfa/verify", response_model=TokenOut)
@limiter.limit("5/minute")
def mfa_verify(
    request: Request, payload: MfaVerifyIn, db: Session = Depends(get_db)
) -> TokenOut:
    result = mfa_service.verify_second_step(
        db,
        mfa_session=payload.mfa_session,
        code=payload.code,
        ip=_client_ip(request),
    )
    return _token_out(result)


@router.post("/mfa/setup")
def mfa_setup(
    current: Operator = Depends(get_current_operator), db: Session = Depends(get_db)
) -> dict:
    return mfa_service.setup(db, current=current)


@router.post("/mfa/enable", status_code=status.HTTP_204_NO_CONTENT)
def mfa_enable(
    payload: MfaCodeIn,
    current: Operator = Depends(get_current_operator),
    db: Session = Depends(get_db),
) -> None:
    mfa_service.enable(db, current=current, code=payload.code)


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
def mfa_disable(
    payload: MfaCodeIn,
    current: Operator = Depends(get_current_operator),
    db: Session = Depends(get_db),
) -> None:
    mfa_service.disable(db, current=current, code=payload.code)


# ── Logout ────────────────────────────────────────────────────────────────────


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> None:
    auth_service.logout(db, token=token, current=current)


# ── Me ────────────────────────────────────────────────────────────────────────


@router.get("/me")
def me(current: Operator = Depends(get_current_operator)) -> dict:
    return {
        "id": current.id,
        "callsign": current.callsign,
        "rank": current.rank,
        "role": current.role,
        "status": current.status,
        "team_id": current.team_id,
        "mfa_enabled": current.mfa_enabled,
    }
