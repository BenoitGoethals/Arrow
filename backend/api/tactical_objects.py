from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.api.schemas import TacticalObjectIn, TacticalObjectOut, TacticalObjectPatch
from backend.auth.jwt_auth import get_current_operator
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import Mission, Operator, TacticalObject
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/tactical-objects", tags=["tactical"])


@router.get("", response_model=list[TacticalObjectOut])
def list_objects(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[TacticalObject]:
    q = db.query(TacticalObject)
    if mission:
        # Always include global objects (mission_id=NULL) alongside mission-scoped ones
        # so CBRN overlays, reference graphics, and KML-derived markers are always visible.
        q = q.filter(or_(TacticalObject.mission_id == mission.id,
                         TacticalObject.mission_id.is_(None)))
    return q.all()


@router.post("", response_model=TacticalObjectOut, status_code=status.HTTP_201_CREATED)
async def create_object(
    payload: TacticalObjectIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> TacticalObject:
    obj = TacticalObject(
        created_by=current.id,
        mission_id=mission.id if mission else None,
        **payload.model_dump(),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

    await broadcaster.broadcast({
        "channel": "tactical-object",
        "event": "created",
        "mission_id": mission.id if mission else None,
        "data": TacticalObjectOut.model_validate(obj).model_dump(mode="json"),
    })

    # Bridge the tactical object to connected ATAK devices as a CoT event.
    from backend.cot.tcp_server import broadcast_tactical_object_to_atak
    await broadcast_tactical_object_to_atak(obj)

    # Bridge geo-pinned photos to connected ATAK devices as an image CoT.
    if obj.photo_id:
        from backend.cot.tcp_server import broadcast_photo_to_atak
        await broadcast_photo_to_atak(obj, current)

    return obj


@router.patch("/{object_id}", response_model=TacticalObjectOut)
async def patch_object(
    object_id: int,
    payload: TacticalObjectPatch,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> TacticalObject:
    obj = db.get(TacticalObject, object_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if obj.created_by != current.id and current.role not in {"ADMIN", "BATTLE_CAPTAIN"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    await broadcaster.broadcast({
        "channel": "tactical-object",
        "event": "updated",
        "mission_id": obj.mission_id,
        "data": TacticalObjectOut.model_validate(obj).model_dump(mode="json"),
    })

    # Re-broadcast the updated CoT (same UID — ATAK treats it as a move).
    from backend.cot.tcp_server import broadcast_tactical_object_to_atak
    await broadcast_tactical_object_to_atak(obj)
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
    mid = obj.mission_id
    # Snapshot the object so we can emit a stale-CoT to ATAK after the row is gone.
    from copy import copy
    obj_snapshot = copy(obj)
    db.delete(obj)
    db.commit()
    await broadcaster.broadcast({
        "channel": "tactical-object",
        "event": "deleted",
        "mission_id": mid,
        "data": {"id": object_id},
    })

    # Tell connected ATAK clients to drop this marker.
    from backend.cot.tcp_server import broadcast_tactical_object_delete_to_atak
    await broadcast_tactical_object_delete_to_atak(obj_snapshot)
