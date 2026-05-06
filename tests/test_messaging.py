"""Test that battle-captain-group messages are visible to admins/BCs but not regular operators."""

from __future__ import annotations

import uuid


def _register(client, role: str = "OPERATOR") -> tuple[str, str, int]:
    callsign = f"M-{uuid.uuid4().hex[:8].upper()}"
    r = client.post(
        "/auth/register",
        json={"callsign": callsign, "password": "pw123456", "role": role},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return callsign, token, me["id"]


def test_group_messages_visible_to_battle_captains_only(client) -> None:
    _, op_token, op_id = _register(client, "OPERATOR")
    _, capt_token, capt_id = _register(client, "BATTLE_CAPTAIN")
    _, admin_token, admin_id = _register(client, "ADMIN")

    h_admin = {"Authorization": f"Bearer {admin_token}"}
    h_capt = {"Authorization": f"Bearer {capt_token}"}
    h_op = {"Authorization": f"Bearer {op_token}"}

    # Admin posts to BATTLE_CAPTAINS group.
    r = client.post(
        "/messages",
        headers=h_admin,
        json={"content": "BC sync at 1800", "message_type": "GROUP", "group_id": "BATTLE_CAPTAINS"},
    )
    assert r.status_code == 201, r.text

    def _has_bc_msg(messages: list[dict]) -> bool:
        return any(
            m["message_type"] == "GROUP"
            and m["group_id"] == "BATTLE_CAPTAINS"
            and m["content"] == "BC sync at 1800"
            for m in messages
        )

    assert _has_bc_msg(client.get("/messages", headers=h_admin).json()), "admin (sender) should see"
    assert _has_bc_msg(client.get("/messages", headers=h_capt).json()), "battle captain should see"
    assert not _has_bc_msg(client.get("/messages", headers=h_op).json()), "regular operator should NOT see"


def test_direct_and_broadcast_routing(client) -> None:
    _, op_token, op_id = _register(client, "OPERATOR")
    _, capt_token, capt_id = _register(client, "BATTLE_CAPTAIN")

    h_op = {"Authorization": f"Bearer {op_token}"}
    h_capt = {"Authorization": f"Bearer {capt_token}"}

    # Direct from op → capt
    client.post("/messages", headers=h_op, json={
        "content": "target spotted", "message_type": "DIRECT", "receiver_id": capt_id,
    })
    # Broadcast from capt
    client.post("/messages", headers=h_capt, json={"content": "all-units stand-by", "message_type": "BROADCAST"})

    capt_msgs = client.get("/messages", headers=h_capt).json()
    assert any(m["content"] == "target spotted" and m["message_type"] == "DIRECT" for m in capt_msgs)
    assert any(m["content"] == "all-units stand-by" for m in capt_msgs)

    op_msgs = client.get("/messages", headers=h_op).json()
    assert any(m["content"] == "all-units stand-by" for m in op_msgs)
    # Direct should be visible to op (sender)
    assert any(m["content"] == "target spotted" for m in op_msgs)
