"""Test that messages route correctly between operators, groups, and broadcasts."""

from __future__ import annotations

from tests.conftest import auth, register


def _recv_on_channel(ws, channel: str, max_msgs: int = 10) -> dict:
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("channel") == channel:
            return msg
    raise AssertionError(f"No message on channel '{channel}'")


def test_group_messages_visible_to_battle_captains_only(client) -> None:
    _, op_token, op_id     = register(client, "OPERATOR")
    _, capt_token, capt_id = register(client, "BATTLE_CAPTAIN")
    _, admin_token, _      = register(client, "ADMIN")

    h_admin = auth(admin_token)
    h_capt  = auth(capt_token)
    h_op    = auth(op_token)

    r = client.post("/messages", headers=h_admin, json={
        "content": "BC sync at 1800",
        "message_type": "GROUP",
        "group_id": "BATTLE_CAPTAINS",
    })
    assert r.status_code == 201, r.text

    def _has_bc_msg(messages: list[dict]) -> bool:
        return any(
            m["message_type"] == "GROUP"
            and m["group_id"] == "BATTLE_CAPTAINS"
            and m["content"] == "BC sync at 1800"
            for m in messages
        )

    assert _has_bc_msg(client.get("/messages", headers=h_admin).json()), "admin should see"
    assert _has_bc_msg(client.get("/messages", headers=h_capt).json()),  "BC should see"
    assert not _has_bc_msg(client.get("/messages", headers=h_op).json()), "OPERATOR should NOT see"


def test_direct_and_broadcast_routing(client) -> None:
    _, op_token, op_id     = register(client, "OPERATOR")
    _, capt_token, capt_id = register(client, "BATTLE_CAPTAIN")

    h_op   = auth(op_token)
    h_capt = auth(capt_token)

    client.post("/messages", headers=h_op, json={
        "content": "target spotted",
        "message_type": "DIRECT",
        "receiver_id": capt_id,
    })
    client.post("/messages", headers=h_capt, json={
        "content": "all-units stand-by",
        "message_type": "BROADCAST",
    })

    capt_msgs = client.get("/messages", headers=h_capt).json()
    assert any(m["content"] == "target spotted" and m["message_type"] == "DIRECT"
               for m in capt_msgs)
    assert any(m["content"] == "all-units stand-by" for m in capt_msgs)

    op_msgs = client.get("/messages", headers=h_op).json()
    assert any(m["content"] == "all-units stand-by" for m in op_msgs)
    assert any(m["content"] == "target spotted" for m in op_msgs)


def test_message_websocket_broadcast(client) -> None:
    _, op_tok, op_id   = register(client)
    _, recv_tok, recv_id = register(client)

    with client.websocket_connect(f"/ws?token={recv_tok}") as ws:
        client.post("/messages", headers=auth(op_tok), json={
            "content": "incoming",
            "message_type": "BROADCAST",
        })
        msg = _recv_on_channel(ws, "chat")
        assert msg["event"] == "message"
        assert msg["data"]["content"] == "incoming"
