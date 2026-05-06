from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import TacticalObjectIn, TacticalObjectOut
from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import Operator, TacticalObject
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/tactical-objects", tags=["tactical"])


@router.get("", response_model=list[TacticalObjectOut])
def list_objects(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[TacticalObject]:
    return db.query(TacticalObject).all()


@router.post("", response_model=TacticalObjectOut, status_code=status.HTTP_201_CREATED)
async def create_object(
    payload: TacticalObjectIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> TacticalObject:
    obj = TacticalObject(created_by=current.id, **payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)

    await broadcaster.broadcast(
        {
            "channel": "tactical-object",
            "event": "created",
            "data": TacticalObjectOut.model_validate(obj).model_dump(mode="json"),
        }
    )
    return obj


@router.delete("/{object_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_object(
    object_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> None:
    obj = db.get(TacticalObject, object_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if obj.created_by != current.id and current.role not in {"ADMIN", "BATTLE_CAPTAIN"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    db.delete(obj)
    db.commit()
    await broadcaster.broadcast(
        {"channel": "tactical-object", "event": "deleted", "data": {"id": object_id}}
    )
