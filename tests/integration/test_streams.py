"""End-to-end tests for the live video stream relay (`backend/streams/router.py`).

Covers:
  • Auth — both /produce and /consume require a valid JWT in the `token` query
    string; this guards against the regression we just fixed where `token: str = ""`
    swallowed the query value.
  • Lifecycle — a connected producer registers in GET /streams; broadcasts a
    `{channel:"stream", event:"started"}` event to /ws subscribers; and is
    de-registered when the producer disconnects (with an `event:"ended"`).
  • Frame relay — binary frames sent by the producer are delivered verbatim to
    every connected consumer.
  • Multi-consumer fanout — two consumers each receive their own copy of the
    same frame.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import auth, register

# ── Helpers ──────────────────────────────────────────────────────────────────


def _wait_for_stream(
    client: TestClient, token: str, sid: str, timeout: float = 2.0
) -> None:
    """Block until /streams reports `sid` is active (producer fully registered)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get("/streams", headers=auth(token))
        if r.status_code == 200 and any(s["id"] == sid for s in r.json()):
            return
        time.sleep(0.02)
    raise AssertionError(f"stream {sid} never appeared in /streams within {timeout}s")


def _wait_for_stream_gone(
    client: TestClient, token: str, sid: str, timeout: float = 2.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get("/streams", headers=auth(token))
        if r.status_code == 200 and not any(s["id"] == sid for s in r.json()):
            return
        time.sleep(0.02)
    raise AssertionError(f"stream {sid} still in /streams after {timeout}s")


def _recv_on_channel(ws, channel: str, max_msgs: int = 20) -> dict:
    """Drain non-matching messages until we get one with the requested channel."""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("channel") == channel:
            return msg
    raise AssertionError(f"No message on channel '{channel}' after {max_msgs} reads")


# ── Auth ─────────────────────────────────────────────────────────────────────


def test_produce_rejects_missing_token(client) -> None:
    """No `?token=` → server should refuse the upgrade."""
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect("/streams/x/produce"):
            pass


def test_produce_rejects_bogus_token(client) -> None:
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect("/streams/x/produce?token=NOTAJWT"):
            pass


def test_consume_rejects_missing_token(client) -> None:
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect("/streams/x/consume"):
            pass


def test_consume_rejects_unknown_stream(client) -> None:
    """Valid token, but `does-not-exist` stream is not in the registry."""
    _, tok, _ = register(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/streams/does-not-exist/consume?token={tok}"):
            pass


def test_streams_list_requires_auth(client) -> None:
    assert client.get("/streams").status_code == 401


# ── Lifecycle ────────────────────────────────────────────────────────────────


def test_produce_registers_stream_in_listing(client) -> None:
    _, tok, _ = register(client)
    sid = "test-lifecycle-1"
    with client.websocket_connect(f"/streams/{sid}/produce?token={tok}"):
        _wait_for_stream(client, tok, sid)
        r = client.get("/streams", headers=auth(tok))
        entry = next(s for s in r.json() if s["id"] == sid)
        assert entry["viewers"] == 0
        assert entry["callsign"]  # set from JWT 'sub'

    # After context exit, producer disconnected → stream evicted
    _wait_for_stream_gone(client, tok, sid)


def test_started_event_broadcast_to_ws_subscribers(client) -> None:
    _, prod_tok, _ = register(client)
    _, watcher_tok, _ = register(client)
    sid = "test-broadcast-started"

    with client.websocket_connect(f"/ws?token={watcher_tok}") as watcher:
        # /ws emits a presence event on connect — skip it via the channel filter.
        with client.websocket_connect(f"/streams/{sid}/produce?token={prod_tok}"):
            msg = _recv_on_channel(watcher, "stream")
            assert msg["event"] == "started"
            assert msg["data"]["id"] == sid


def test_ended_event_broadcast_when_producer_disconnects(client) -> None:
    _, prod_tok, _ = register(client)
    _, watcher_tok, _ = register(client)
    sid = "test-broadcast-ended"

    with client.websocket_connect(f"/ws?token={watcher_tok}") as watcher:
        with client.websocket_connect(f"/streams/{sid}/produce?token={prod_tok}"):
            _ = _recv_on_channel(watcher, "stream")  # consume "started"
        # Producer context exited → backend should fire "ended"
        msg = _recv_on_channel(watcher, "stream")
        assert msg["event"] == "ended"
        assert msg["data"]["id"] == sid


# ── Frame relay ──────────────────────────────────────────────────────────────


def test_frame_relay_from_producer_to_single_consumer(client) -> None:
    _, prod_tok, _ = register(client)
    _, cons_tok, _ = register(client)
    sid = "test-frame-relay-1"

    with client.websocket_connect(f"/streams/{sid}/produce?token={prod_tok}") as prod:
        _wait_for_stream(client, prod_tok, sid)

        with client.websocket_connect(
            f"/streams/{sid}/consume?token={cons_tok}"
        ) as cons:
            # Give the backend a moment to add cons to stream.consumers
            time.sleep(0.05)

            payload = b"\xff\xd8\xff\xe0FAKE_JPEG_FRAME_PAYLOAD\xff\xd9"
            prod.send_bytes(payload)

            received = cons.receive_bytes()
            assert received == payload


def test_frame_relay_to_multiple_consumers(client) -> None:
    _, prod_tok, _ = register(client)
    _, cons1_tok, _ = register(client)
    _, cons2_tok, _ = register(client)
    sid = "test-frame-relay-multi"

    with client.websocket_connect(f"/streams/{sid}/produce?token={prod_tok}") as prod:
        _wait_for_stream(client, prod_tok, sid)

        with (
            client.websocket_connect(f"/streams/{sid}/consume?token={cons1_tok}") as c1,
            client.websocket_connect(f"/streams/{sid}/consume?token={cons2_tok}") as c2,
        ):
            time.sleep(0.05)

            r = client.get("/streams", headers=auth(prod_tok))
            entry = next(s for s in r.json() if s["id"] == sid)
            assert entry["viewers"] == 2

            payload = b"FRAME-FOR-MULTIPLE-CONSUMERS"
            prod.send_bytes(payload)

            assert c1.receive_bytes() == payload
            assert c2.receive_bytes() == payload


def test_producer_creates_recording_with_frames(client) -> None:
    """Each producer connection auto-saves a recording the admin can replay."""
    _, prod_tok, _ = register(client)
    sid = "test-record-1"
    with client.websocket_connect(f"/streams/{sid}/produce?token={prod_tok}") as prod:
        _wait_for_stream(client, prod_tok, sid)
        prod.send_bytes(b"\xff\xd8\xff\xe0FRAME-1\xff\xd9")
        prod.send_bytes(b"\xff\xd8\xff\xe0FRAME-2\xff\xd9")
        time.sleep(0.10)  # let the producer task flush both frames to disk

    # After the WS closes, the recording should be sealed
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        rows = client.get("/streams/recordings", headers=auth(prod_tok)).json()
        match = [r for r in rows if r["stream_id"] == sid]
        if match and not match[0]["live"]:
            break
        time.sleep(0.05)
    assert match, "recording was never registered for the stream"
    rec = match[0]
    assert rec["frame_count"] == 2
    assert rec["byte_size"] > 0
    assert rec["live"] is False
    assert rec["ended_at"]
    rec_id = rec["id"]

    # Thumbnail returns the first frame as image/jpeg
    th = client.get(f"/streams/recordings/{rec_id}/thumbnail", headers=auth(prod_tok))
    assert th.status_code == 200
    assert th.headers["content-type"] == "image/jpeg"
    assert th.content == b"\xff\xd8\xff\xe0FRAME-1\xff\xd9"

    # Download returns the raw .arrowmjpeg file
    dl = client.get(f"/streams/recordings/{rec_id}/download", headers=auth(prod_tok))
    assert dl.status_code == 200
    assert "arrow-" in dl.headers.get("content-disposition", "")


def test_recording_delete_requires_admin_or_bc(client) -> None:
    _, prod_tok, _ = register(client, "OPERATOR")
    _, admin_tok, _ = register(client, "ADMIN")
    sid = "test-record-delete"
    with client.websocket_connect(f"/streams/{sid}/produce?token={prod_tok}") as prod:
        _wait_for_stream(client, prod_tok, sid)
        prod.send_bytes(b"\xff\xd8frame\xff\xd9")
        time.sleep(0.05)
    # Wait for it to seal
    deadline = time.monotonic() + 2.0
    rec_id = None
    while time.monotonic() < deadline:
        rows = client.get("/streams/recordings", headers=auth(admin_tok)).json()
        match = [r for r in rows if r["stream_id"] == sid]
        if match and not match[0]["live"]:
            rec_id = match[0]["id"]
            break
        time.sleep(0.05)
    assert rec_id

    # Operator may not delete
    assert (
        client.delete(
            f"/streams/recordings/{rec_id}", headers=auth(prod_tok)
        ).status_code
        == 403
    )
    # Admin can
    assert (
        client.delete(
            f"/streams/recordings/{rec_id}", headers=auth(admin_tok)
        ).status_code
        == 204
    )
    # And after delete the row is gone
    rows = client.get("/streams/recordings", headers=auth(admin_tok)).json()
    assert not any(r["id"] == rec_id for r in rows)


def test_consumer_disconnect_does_not_affect_producer(client) -> None:
    """A consumer dropping out should not crash the producer or evict the stream."""
    _, prod_tok, _ = register(client)
    _, cons_tok, _ = register(client)
    sid = "test-consumer-drop"

    with client.websocket_connect(f"/streams/{sid}/produce?token={prod_tok}") as prod:
        _wait_for_stream(client, prod_tok, sid)

        with client.websocket_connect(
            f"/streams/{sid}/consume?token={cons_tok}"
        ) as cons:
            time.sleep(0.05)
            prod.send_bytes(b"first")
            assert cons.receive_bytes() == b"first"
        # Consumer left — producer should still be able to send (no exception)
        time.sleep(0.05)
        prod.send_bytes(b"second-after-consumer-left")

        # Stream still listed
        r = client.get("/streams", headers=auth(prod_tok))
        assert any(s["id"] == sid for s in r.json())
