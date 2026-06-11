from fastapi import APIRouter, Depends, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.api.schemas import MessageIn, MessageOut
from backend.auth.jwt_auth import get_current_operator
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import Message, Mission, Operator, Photo
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/messages", tags=["messaging"])

_ROLE_GROUPS: dict[str, list[str]] = {
    "ADMIN": ["BATTLE_CAPTAINS"],
    "BATTLE_CAPTAIN": ["BATTLE_CAPTAINS"],
}


def _groups_for(op: Operator) -> list[str]:
    return _ROLE_GROUPS.get(op.role, [])


@router.get("")
def list_messages(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[dict]:
    clauses = [
        Message.sender_id == current.id,
        Message.receiver_id == current.id,
        Message.message_type == "BROADCAST",
    ]
    groups = _groups_for(current)
    if groups:
        clauses.append(Message.group_id.in_(groups))

    q = db.query(Message).filter(or_(*clauses))
    if mission:
        q = q.filter(Message.mission_id == mission.id)
    msgs = q.order_by(Message.timestamp.desc()).limit(200).all()

    photo_ids = {m.photo_id for m in msgs if m.photo_id}
    mime_map: dict[int, str] = {}
    if photo_ids:
        for p in db.query(Photo.id, Photo.mime_type).filter(Photo.id.in_(photo_ids)).all():
            mime_map[p.id] = p.mime_type

    return [
        {**MessageOut.model_validate(m).model_dump(mode="json"),
         "photo_mime_type": mime_map.get(m.photo_id) if m.photo_id else None}
        for m in msgs
    ]


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    payload: MessageIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> Message:
    msg = Message(
        sender_id=current.id,
        mission_id=mission.id if mission else current.mission_id,
        **payload.model_dump(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    await broadcaster.broadcast({
        "channel": "chat",
        "event": "message",
        "mission_id": msg.mission_id,
        "data": MessageOut.model_validate(msg).model_dump(mode="json"),
    })
    return msg
