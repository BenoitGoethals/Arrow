from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import OperatorOut, OperatorUpdate, PasswordReset
from backend.auth.jwt_auth import get_current_operator, hash_password, require_role
from backend.storage.database import get_db
from backend.storage.models import Operator

router = APIRouter(prefix="/operators", tags=["operators"])


@router.get("", response_model=list[OperatorOut])
def list_operators(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[Operator]:
    return db.query(Operator).all()


@router.get("/{operator_id}", response_model=OperatorOut)
def get_operator(
    operator_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Operator:
    op = db.get(Operator, operator_id)
    if not op:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return op


@router.patch("/{operator_id}", response_model=OperatorOut)
def update_operator(
    operator_id: int,
    payload: OperatorUpdate,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> Operator:
    op = db.get(Operator, operator_id)
    if not op:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(op, field, value)
    db.commit()
    db.refresh(op)
    return op


@router.post("/{operator_id}/set-password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(
    operator_id: int,
    payload: PasswordReset,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> None:
    op = db.get(Operator, operator_id)
    if not op:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    op.password_hash = hash_password(payload.password)
    db.commit()


@router.delete("/{operator_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_operator(
    operator_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> None:
    op = db.get(Operator, operator_id)
    if not op:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(op)
    db.commit()
