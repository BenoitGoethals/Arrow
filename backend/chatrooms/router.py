"""Chat rooms: named multi-operator conversations with explicit membership.

A ChatRoom maps 1:1 to an ATAK GeoChat named room. Operators with ADMIN /
BATTLE_CAPTAIN role (or the room creator) manage membership; any member can post
ROOM messages to it (see backend.messaging.router).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import ChatRoomIn, ChatRoomMemberIn, ChatRoomOut
from backend.auth.jwt_auth import get_current_operator
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import ChatRoom, ChatRoomMember, Mission, Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/chatrooms", tags=["chatrooms"])

_MGR_ROLES = {"ADMIN", "BATTLE_CAPTAIN"}


# ── shared helpers (also imported by the ATAK GeoChat bridge) ──────────────────

def member_ids(db: Session, room_id: int) -> list[int]:
    return [m.operator_id for m in
            db.query(ChatRoomMember).filter(ChatRoomMember.chatroom_id == room_id).all()]


def is_member(db: Session, room_id: int, op_id: int) -> bool:
    return db.query(ChatRoomMember).filter(
        ChatRoomMember.chatroom_id == room_id,
        ChatRoomMember.operator_id == op_id,
    ).first() is not None


def add_member(db: Session, room_id: int, op_id: int) -> bool:
    """Add an operator to a room (idempotent). Returns True if newly added."""
    if is_member(db, room_id, op_id):
        return False
    db.add(ChatRoomMember(chatroom_id=room_id, operator_id=op_id))
    db.commit()
    return True


def get_or_create_room(db: Session, name: str, creator_id: int,
                       origin: str = "ARROW", mission_id: int | None = None) -> ChatRoom:
    """Look up a room by name (case-insensitive), creating it if absent."""
    room = db.query(ChatRoom).filter(ChatRoom.name.ilike(name)).first()
    if room is None:
        room = ChatRoom(name=name, created_by=creator_id, origin=origin, mission_id=mission_id)
        db.add(room)
        db.commit()
        db.refresh(room)
    return room


def room_out(db: Session, room: ChatRoom) -> dict:
    rows = (db.query(ChatRoomMember.operator_id, Operator.callsign)
              .join(Operator, Operator.id == ChatRoomMember.operator_id)
              .filter(ChatRoomMember.chatroom_id == room.id).all())
    members = [{"operator_id": oid, "callsign": cs} for oid, cs in rows]
    return {
        "id": room.id, "name": room.name, "created_by": room.created_by,
        "created_at": room.created_at.isoformat() if room.created_at else None,
        "mission_id": room.mission_id, "origin": room.origin,
        "member_ids": [m["operator_id"] for m in members],
        "members": members,
    }


async def _broadcast_room(db: Session, room: ChatRoom, event: str) -> None:
    await broadcaster.broadcast({
        "channel": "chat", "event": event,
        "mission_id": room.mission_id, "data": room_out(db, room),
    })


def _require_manage(db: Session, room: ChatRoom, op: Operator) -> None:
    if op.role not in _MGR_ROLES and room.created_by != op.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage this room")


# ── endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ChatRoomOut])
def list_rooms(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> list[dict]:
    """Rooms the caller belongs to (ADMIN / BATTLE_CAPTAIN see all rooms)."""
    if current.role in _MGR_ROLES:
        rooms = db.query(ChatRoom).order_by(ChatRoom.name).all()
    else:
        ids = [m.chatroom_id for m in
               db.query(ChatRoomMember).filter(ChatRoomMember.operator_id == current.id).all()]
        rooms = (db.query(ChatRoom).filter(ChatRoom.id.in_(ids)).order_by(ChatRoom.name).all()
                 if ids else [])
    return [room_out(db, r) for r in rooms]


@router.post("", response_model=ChatRoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(
    payload: ChatRoomIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> dict:
    room = ChatRoom(name=payload.name.strip() or "Room", created_by=current.id,
                    origin="ARROW", mission_id=mission.id if mission else None)
    db.add(room)
    db.commit()
    db.refresh(room)
    # Creator is always a member; plus any requested members.
    wanted = {current.id, *payload.member_ids}
    for oid in wanted:
        if db.get(Operator, oid):
            add_member(db, room.id, oid)
    await _broadcast_room(db, room, "room_created")
    return room_out(db, room)


@router.get("/{room_id}", response_model=ChatRoomOut)
def get_room(
    room_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> dict:
    room = db.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if current.role not in _MGR_ROLES and not is_member(db, room_id, current.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this room")
    return room_out(db, room)


@router.post("/{room_id}/members", response_model=ChatRoomOut)
async def add_room_member(
    room_id: int,
    payload: ChatRoomMemberIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> dict:
    room = db.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _require_manage(db, room, current)
    if not db.get(Operator, payload.operator_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Operator not found")
    add_member(db, room_id, payload.operator_id)
    await _broadcast_room(db, room, "member_added")
    return room_out(db, room)


@router.delete("/{room_id}/members/{operator_id}", response_model=ChatRoomOut)
async def remove_room_member(
    room_id: int,
    operator_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> dict:
    room = db.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Managers can remove anyone; an operator may always remove themselves (leave).
    if operator_id != current.id:
        _require_manage(db, room, current)
    db.query(ChatRoomMember).filter(
        ChatRoomMember.chatroom_id == room_id,
        ChatRoomMember.operator_id == operator_id,
    ).delete()
    db.commit()
    await _broadcast_room(db, room, "member_removed")
    return room_out(db, room)


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> None:
    room = db.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _require_manage(db, room, current)
    mid = room.mission_id
    rid = room.id
    db.delete(room)
    db.commit()
    await broadcaster.broadcast({
        "channel": "chat", "event": "room_deleted",
        "mission_id": mid, "data": {"id": rid},
    })
