from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.audit import log_event
from backend.api.schemas import (
    OperatorOut,
    OperatorUpdate,
    OpsStatusUpdate,
    PasswordReset,
)
from backend.auth.jwt_auth import get_current_operator, hash_password, require_role
from backend.storage.database import get_db
from backend.storage.models import Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/operators", tags=["operators"])

VALID_OPS_STATUS = {"OPS", "INOPS", "KIA", "MIA"}


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
    current: Operator = Depends(require_role("ADMIN")),
) -> Operator:
    op = db.get(Operator, operator_id)
    if not op:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    changes = payload.model_dump(exclude_unset=True)
    if "clearance" in changes and changes["clearance"] is not None:
        from backend.classification import clamp

        changes["clearance"] = clamp(changes["clearance"])
    for field, value in changes.items():
        setattr(op, field, value)
    db.commit()
    db.refresh(op)
    log_event(
        db,
        "OPERATOR_UPDATE",
        operator_id=current.id,
        resource=f"operator:{operator_id}",
        detail=str(changes),
    )
    return op


@router.patch("/{operator_id}/ops-status", response_model=OperatorOut)
async def set_ops_status(
    operator_id: int,
    payload: OpsStatusUpdate,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Operator:
    value = payload.ops_status.upper()
    if value not in VALID_OPS_STATUS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"ops_status must be one of {sorted(VALID_OPS_STATUS)}",
        )
    op = db.get(Operator, operator_id)
    if not op:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    op.ops_status = value
    db.commit()
    db.refresh(op)
    log_event(
        db,
        "OPERATOR_OPS_STATUS",
        operator_id=current.id,
        resource=f"operator:{operator_id}",
        detail=value,
    )
    await broadcaster.broadcast(
        {
            "channel": "presence",
            "event": "ops_status",
            "data": {
                "operator_id": op.id,
                "callsign": op.callsign,
                "ops_status": value,
            },
        }
    )
    return op


@router.post("/{operator_id}/set-password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(
    operator_id: int,
    payload: PasswordReset,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN")),
) -> None:
    op = db.get(Operator, operator_id)
    if not op:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    op.password_hash = hash_password(payload.password)
    op.failed_login_count = 0
    op.locked_until = None
    db.commit()
    log_event(
        db, "PASSWORD_RESET", operator_id=current.id, resource=f"operator:{operator_id}"
    )


@router.delete("/{operator_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_operator(
    operator_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN")),
) -> None:
    op = db.get(Operator, operator_id)
    if not op:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    callsign = op.callsign
    db.delete(op)
    db.commit()
    log_event(
        db,
        "OPERATOR_DELETE",
        operator_id=current.id,
        resource=f"operator:{operator_id}",
        detail=f"callsign:{callsign}",
    )
