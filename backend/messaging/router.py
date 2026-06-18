from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.api.schemas import MessageIn, MessageOut
from backend.auth.jwt_auth import get_current_operator
from backend.chatrooms.router import is_member
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import ChatRoom, ChatRoomMember, Message, Mission, Operator, Photo
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/messages", tags=["messaging"])

_MGR_ROLES = {"ADMIN", "BATTLE_CAPTAIN"}


@router.get("")
def list_messages(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[dict]:
    # A message is visible if I sent it, it's addressed to me, it's a broadcast,
    # or it belongs to a chat room I'm a member of.
    my_rooms = [m.chatroom_id for m in
                db.query(ChatRoomMember).filter(ChatRoomMember.operator_id == current.id).all()]
    clauses = [
        Message.sender_id == current.id,
        Message.receiver_id == current.id,
        Message.message_type == "BROADCAST",
    ]
    if my_rooms:
        clauses.append(Message.chatroom_id.in_(my_rooms))

    q = db.query(Message).filter(or_(*clauses))
    if mission:
        q = q.filter(Message.mission_id == mission.id)
    msgs = q.order_by(Message.timestamp.desc()).limit(200).all()

    photo_ids = {m.photo_id for m in msgs if m.photo_id}
    mime_map: dict[int, str] = {}
    if photo_ids:
        for p in db.query(Photo.id, Photo.mime_type).filter(Photo.id.in_(photo_ids)).all():
            mime_map[p.id] = p.mime_type

    sender_ids = {m.sender_id for m in msgs}
    callsign_map: dict[int, str] = {}
    if sender_ids:
        for op in db.query(Operator.id, Operator.callsign).filter(Operator.id.in_(sender_ids)).all():
            callsign_map[op.id] = op.callsign

    return [
        {**MessageOut.model_validate(m).model_dump(mode="json"),
         "photo_mime_type": mime_map.get(m.photo_id) if m.photo_id else None,
         "sender_callsign": callsign_map.get(m.sender_id, f"op#{m.sender_id}")}
        for m in msgs
    ]


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    payload: MessageIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> Message:
    mtype   = (payload.message_type or "DIRECT").upper()
    content = payload.content or ""
    if not content.strip() and not payload.photo_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Empty message")

    # A chatroom_id implies a ROOM message regardless of the declared type.
    if payload.chatroom_id:
        mtype = "ROOM"

    receiver_id = None
    chatroom_id = None
    if mtype == "ROOM":
        if not payload.chatroom_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "chatroom_id required")
        room = db.get(ChatRoom, payload.chatroom_id)
        if not room:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat room not found")
        if current.role not in _MGR_ROLES and not is_member(db, room.id, current.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this room")
        chatroom_id = room.id
    elif mtype == "DIRECT":
        if not payload.receiver_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "receiver_id required")
        receiver_id = payload.receiver_id
    elif mtype != "BROADCAST":
        mtype = "DIRECT"
        receiver_id = payload.receiver_id

    msg = Message(
        sender_id=current.id,
        receiver_id=receiver_id,
        chatroom_id=chatroom_id,
        content=content,
        message_type=mtype,
        photo_id=payload.photo_id,
        mission_id=mission.id if mission else current.mission_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    data = MessageOut.model_validate(msg).model_dump(mode="json")
    data["sender_callsign"] = current.callsign
    await broadcaster.broadcast({
        "channel": "chat",
        "event": "message",
        "mission_id": msg.mission_id,
        "data": data,
    })

    # Bridge to ATAK GeoChat so ATAK operators see Arrow chat (two-way bridge).
    from backend.cot.tcp_server import broadcast_chat_to_atak
    await broadcast_chat_to_atak(msg, current)

    return msg
