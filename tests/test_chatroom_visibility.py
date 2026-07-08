"""Bridged (ATAK/JDSS-origin) chat rooms are visible mission-wide.

A native (ARROW) room stays member-only, but a room bridged in from ATAK/JDSS is
visible to every operator in the room's mission (or global rooms), capped by the
caller's clearance. Managers (ADMIN/BATTLE_CAPTAIN) still see everything.
"""

from __future__ import annotations

import backend.storage.database as _db
from backend.storage.models import ChatRoom
from tests.conftest import auth, register


def _make_room(name: str, origin: str, classification: int = 0) -> int:
    with _db.SessionLocal() as db:
        room = ChatRoom(
            name=name, created_by=1, origin=origin, classification=classification
        )
        db.add(room)
        db.commit()
        db.refresh(room)
        return room.id


def test_bridged_room_visible_to_non_member(client):
    _, tok, _ = register(client, role="OPERATOR")
    atak_id = _make_room("ATAK Coalition Net", "ATAK")
    arrow_id = _make_room("Private Arrow Room", "ARROW")

    r = client.get("/chatrooms", headers=auth(tok))
    assert r.status_code == 200
    rooms = {room["id"]: room for room in r.json()}

    assert atak_id in rooms, "bridged ATAK room should be visible mission-wide"
    assert rooms[atak_id]["origin"] == "ATAK"
    assert arrow_id not in rooms, "native room they are not a member of stays hidden"


def test_bridged_room_hidden_above_clearance(client):
    # A freshly registered operator has clearance 0; a SECRET(3) bridged room
    # must not leak to them.
    _, tok, _ = register(client, role="OPERATOR")
    secret_id = _make_room("ATAK Secret Net", "ATAK", classification=3)

    r = client.get("/chatrooms", headers=auth(tok))
    assert r.status_code == 200
    assert secret_id not in {room["id"] for room in r.json()}
