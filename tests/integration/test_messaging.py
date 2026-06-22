"""Test that messages route correctly between operators, groups, and broadcasts."""

from __future__ import annotations

from tests.conftest import auth, register


def _recv_on_channel(ws, channel: str, max_msgs: int = 10) -> dict:
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("channel") == channel:
            return msg
    raise AssertionError(f"No message on channel '{channel}'")


def test_room_messages_visible_to_members_only(client) -> None:
    _, out_token, out_id = register(client, "OPERATOR")  # non-member
    _, member_token, member_id = register(client, "OPERATOR")  # room member
    _, capt_token, capt_id = register(client, "BATTLE_CAPTAIN")  # creator

    h_capt = auth(capt_token)
    h_member = auth(member_token)
    h_out = auth(out_token)

    # Battle Captain creates a room and adds `member`.
    r = client.post(
        "/chatrooms",
        headers=h_capt,
        json={"name": "ALPHA NET", "member_ids": [member_id]},
    )
    assert r.status_code == 201, r.text
    room = r.json()
    rid = room["id"]
    assert member_id in room["member_ids"]
    assert capt_id in room["member_ids"]  # creator is auto-added

    # Post a ROOM message.
    r = client.post(
        "/messages",
        headers=h_capt,
        json={
            "content": "net check",
            "message_type": "ROOM",
            "chatroom_id": rid,
        },
    )
    assert r.status_code == 201, r.text

    def _has(msgs: list[dict]) -> bool:
        return any(
            m["message_type"] == "ROOM"
            and m.get("chatroom_id") == rid
            and m["content"] == "net check"
            for m in msgs
        )

    assert _has(client.get("/messages", headers=h_capt).json()), "creator should see"
    assert _has(client.get("/messages", headers=h_member).json()), "member should see"
    assert not _has(
        client.get("/messages", headers=h_out).json()
    ), "non-member should NOT see"

    # A non-member may not post to the room.
    r = client.post(
        "/messages",
        headers=h_out,
        json={
            "content": "intruder",
            "message_type": "ROOM",
            "chatroom_id": rid,
        },
    )
    assert r.status_code == 403, r.text

    # Add/remove membership.
    client.post(
        f"/chatrooms/{rid}/members", headers=h_capt, json={"operator_id": out_id}
    )
    client.delete(f"/chatrooms/{rid}/members/{member_id}", headers=h_capt)
    room2 = client.get(f"/chatrooms/{rid}", headers=h_capt).json()
    assert out_id in room2["member_ids"]
    assert member_id not in room2["member_ids"]


def test_direct_and_broadcast_routing(client) -> None:
    _, op_token, op_id = register(client, "OPERATOR")
    _, capt_token, capt_id = register(client, "BATTLE_CAPTAIN")

    h_op = auth(op_token)
    h_capt = auth(capt_token)

    client.post(
        "/messages",
        headers=h_op,
        json={
            "content": "target spotted",
            "message_type": "DIRECT",
            "receiver_id": capt_id,
        },
    )
    client.post(
        "/messages",
        headers=h_capt,
        json={
            "content": "all-units stand-by",
            "message_type": "BROADCAST",
        },
    )

    capt_msgs = client.get("/messages", headers=h_capt).json()
    assert any(
        m["content"] == "target spotted" and m["message_type"] == "DIRECT"
        for m in capt_msgs
    )
    assert any(m["content"] == "all-units stand-by" for m in capt_msgs)

    op_msgs = client.get("/messages", headers=h_op).json()
    assert any(m["content"] == "all-units stand-by" for m in op_msgs)
    assert any(m["content"] == "target spotted" for m in op_msgs)


def test_message_websocket_broadcast(client) -> None:
    _, op_tok, op_id = register(client)
    _, recv_tok, recv_id = register(client)

    with client.websocket_connect(f"/ws?token={recv_tok}") as ws:
        client.post(
            "/messages",
            headers=auth(op_tok),
            json={
                "content": "incoming",
                "message_type": "BROADCAST",
            },
        )
        msg = _recv_on_channel(ws, "chat")
        assert msg["event"] == "message"
        assert msg["data"]["content"] == "incoming"
