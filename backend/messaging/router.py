from fastapi import APIRouter, Depends, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.api.schemas import MessageIn, MessageOut
from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import Message, Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/messages", tags=["messaging"])

# Role → list of group_ids the user is a member of. Extend as new groups are added.
_ROLE_GROUPS: dict[str, list[str]] = {
    "ADMIN": ["BATTLE_CAPTAINS"],
    "BATTLE_CAPTAIN": ["BATTLE_CAPTAINS"],
}


def _groups_for(op: Operator) -> list[str]:
    return _ROLE_GROUPS.get(op.role, [])


@router.get("", response_model=list[MessageOut])
def list_messages(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> list[Message]:
    clauses = [
        Message.sender_id == current.id,
        Message.receiver_id == current.id,
        Message.message_type == "BROADCAST",
    ]
    groups = _groups_for(current)
    if groups:
        clauses.append(Message.group_id.in_(groups))

    q = db.query(Message).filter(or_(*clauses))
    return q.order_by(Message.timestamp.desc()).limit(200).all()


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    payload: MessageIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> Message:
    msg = Message(sender_id=current.id, **payload.model_dump())
    db.add(msg)
    db.commit()
    db.refresh(msg)
    await broadcaster.broadcast(
        {
            "channel": "chat",
            "event": "message",
            "data": MessageOut.model_validate(msg).model_dump(mode="json"),
        }
    )
    return msg
