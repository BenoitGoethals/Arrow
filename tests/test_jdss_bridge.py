"""Tests for the JDSSArrow bridge (backend/jdss/bridge.py).

Inbound ingestion is exercised by feeding sample JDSS wire frames to
``_handle_event`` and asserting the right Arrow rows appear and the right
broadcast fires. Outbound publishing is exercised with a fake httpx client.
No network is touched.
"""

from __future__ import annotations

import asyncio
import json
import types

import pytest

import backend.storage.database as _db
from backend.jdss import bridge
from backend.storage.models import Alert, CotTrack, Message, Report, TacticalObject
from backend.websocket.manager import broadcaster
from tests.conftest import auth


@pytest.fixture(autouse=True)
def _reset_bridge():
    """Snapshot/restore module-level state so tests don't bleed into each other."""
    saved_cfg = dict(bridge._cfg)
    saved_client = bridge._client
    bridge._seen.clear()
    bridge._seen_set.clear()
    bridge._state = bridge._State()
    yield
    bridge._cfg.clear()
    bridge._cfg.update(saved_cfg)
    bridge._client = saved_client
    bridge._seen.clear()
    bridge._seen_set.clear()
    bridge._state = bridge._State()


def _capture(monkeypatch) -> list[dict]:
    """Replace broadcaster.broadcast with a capturing async stub."""
    events: list[dict] = []

    async def _fake(msg: dict) -> None:
        events.append(msg)

    monkeypatch.setattr(broadcaster, "broadcast", _fake)
    return events


# ── Config persistence ────────────────────────────────────────────────────────


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "_CFG_FILE", tmp_path / "jdss_config.json")
    out = bridge.update_config(
        {"base_url": "http://10.0.0.5:8000", "enabled": False, "publish_chat": False}
    )
    assert out["base_url"] == "http://10.0.0.5:8000"
    assert out["enabled"] is False

    on_disk = json.loads((tmp_path / "jdss_config.json").read_text())
    assert on_disk["base_url"] == "http://10.0.0.5:8000"
    assert on_disk["enabled"] is False
    assert on_disk["publish_chat"] is False


def test_update_config_ignores_unknown_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "_CFG_FILE", tmp_path / "jdss_config.json")
    out = bridge.update_config({"bogus": "x", "enabled": True})
    assert "bogus" not in out
    assert out["enabled"] is True


# ── Inbound ingestion ─────────────────────────────────────────────────────────


def test_ingest_presence_creates_cot_track(client, monkeypatch):
    events = _capture(monkeypatch)
    evt = {
        "direction": "in",
        "type": "Presence",
        "originator_id": "SOLDIER-1",
        "callsign": "ALPHA-1",
        "message_id": "m1",
        "classification": 0,
        "body": {
            "type": "Presence",
            "location": {"lat": 50.85, "lon": 4.35},
            "callsign": "ALPHA-1",
            "battery_pct": 88,
        },
    }
    asyncio.run(bridge._handle_event(evt))

    assert any(e["channel"] == "cot-track" for e in events)
    with _db.SessionLocal() as db:
        t = db.query(CotTrack).filter(CotTrack.cot_uid == "JDSS.SOLDIER-1").first()
        assert t is not None
        assert t.callsign == "ALPHA-1"
        assert t.latitude == 50.85
    assert bridge._state.rx_messages == 1


def test_ingest_contact_creates_hostile_tactical_object(client, monkeypatch):
    events = _capture(monkeypatch)
    evt = {
        "direction": "in",
        "type": "ContactSighting",
        "originator_id": "OBS-1",
        "callsign": "OBS-1",
        "message_id": "c1",
        "classification": 0,
        "body": {
            "type": "ContactSighting",
            "location": {"lat": 51.0, "lon": 4.0},
            "identity": 6,  # HOSTILE
            "description": "2x dismounts",
        },
    }
    asyncio.run(bridge._handle_event(evt))

    assert any(e["channel"] == "tactical-object" for e in events)
    with _db.SessionLocal() as db:
        obj = db.query(TacticalObject).filter(TacticalObject.type == "ENEMY").first()
        assert obj is not None
        assert obj.affiliation == "HOSTILE"
        assert obj.notes == "2x dismounts"


def test_ingest_chat_broadcasts_message(client, monkeypatch):
    events = _capture(monkeypatch)
    evt = {
        "direction": "in",
        "type": "Chat",
        "originator_id": "NODE-B",
        "callsign": "BRAVO",
        "message_id": "chat1",
        "classification": 0,
        "body": {"type": "Chat", "text": "contact front", "recipient": "all"},
    }
    asyncio.run(bridge._handle_event(evt))

    chat_events = [e for e in events if e["channel"] == "chat"]
    assert chat_events
    assert chat_events[0]["data"]["source"] == "JDSS"
    assert chat_events[0]["data"]["sender_callsign"] == "BRAVO"
    with _db.SessionLocal() as db:
        m = db.query(Message).filter(Message.content == "contact front").first()
        assert m is not None
        assert m.message_type == "BROADCAST"


def test_ingest_casevac_creates_report_and_alert(client, monkeypatch):
    events = _capture(monkeypatch)
    evt = {
        "direction": "in",
        "type": "CasevacRequest",
        "originator_id": "MEDIC-1",
        "callsign": "DOC",
        "message_id": "cv1",
        "classification": 0,
        "body": {
            "type": "CasevacRequest",
            "location": {"lat": 50.5, "lon": 4.5},
            "patients_urgent": 1,
        },
    }
    asyncio.run(bridge._handle_event(evt))

    channels = {e["channel"] for e in events}
    assert "report" in channels and "alert" in channels
    with _db.SessionLocal() as db:
        assert db.query(Report).filter(Report.type == "CASEVAC").first() is not None
        assert db.query(Alert).filter(Alert.type == "MEDEVAC").first() is not None


def test_received_direction_is_ingested(client, monkeypatch):
    # "received" is JDSSArrow's real inbound marker (not "in").
    events = _capture(monkeypatch)
    evt = {
        "direction": "received",
        "type": "Presence",
        "originator_id": "rifleman-1",
        "callsign": "RIF-1",
        "message_id": "rcv1",
        "body": {
            "type": "Presence",
            "location": {"lat": 51.0, "lon": 4.1},
            "callsign": "RIF-1",
        },
    }
    asyncio.run(bridge._handle_event(evt))
    assert any(e["channel"] == "cot-track" for e in events)
    assert bridge._state.rx_messages == 1


@pytest.mark.parametrize("direction", ["sent", "out"])
def test_outbound_directions_not_ingested(client, monkeypatch, direction):
    # "sent"/"out" = messages this node originated (incl. Arrow's publishes) → skip.
    events = _capture(monkeypatch)
    evt = {
        "direction": direction,
        "type": "Presence",
        "originator_id": "SELF",
        "message_id": f"{direction}1",
        "body": {
            "type": "Presence",
            "location": {"lat": 1.0, "lon": 2.0},
            "callsign": "X",
        },
    }
    asyncio.run(bridge._handle_event(evt))
    assert events == []
    assert bridge._state.rx_messages == 0


def test_own_node_origination_not_ingested(client, monkeypatch):
    # A message received back that this gateway node itself originated must be
    # skipped (echo guard) — identified by originator_id == snapshot node_id.
    events = _capture(monkeypatch)
    bridge._state.snapshot = {"node_id": "node-a"}
    evt = {
        "direction": "received",
        "type": "ContactSighting",
        "originator_id": "node-a",  # our own gateway → Arrow-published, don't echo
        "message_id": "echo1",
        "body": {
            "type": "ContactSighting",
            "location": {"lat": 5.0, "lon": 6.0},
            "identity": 6,
        },
    }
    asyncio.run(bridge._handle_event(evt))
    assert events == []
    assert bridge._state.rx_messages == 0


def test_duplicate_message_id_ingested_once(client, monkeypatch):
    _capture(monkeypatch)
    evt = {
        "direction": "in",
        "type": "Presence",
        "originator_id": "SOLDIER-9",
        "callsign": "NINE",
        "message_id": "dup",
        "body": {
            "type": "Presence",
            "location": {"lat": 3.0, "lon": 4.0},
            "callsign": "NINE",
        },
    }
    asyncio.run(bridge._handle_event(evt))
    asyncio.run(bridge._handle_event(evt))
    assert bridge._state.rx_messages == 1


def test_snapshot_and_heartbeat_frames(client, monkeypatch):
    events = _capture(monkeypatch)
    asyncio.run(
        bridge._handle_event({"direction": "snapshot", "snapshot": {"buffered": 5}})
    )
    asyncio.run(bridge._handle_event({"direction": "heartbeat"}))
    assert bridge._state.snapshot == {"buffered": 5}
    assert events == []


# ── Outbound publishing ───────────────────────────────────────────────────────


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url: str, json: dict | None = None):  # noqa: A002
        self.calls.append((url, json or {}))
        return types.SimpleNamespace(status_code=200)


def _use_fake_client() -> _FakeClient:
    fake = _FakeClient()
    bridge._client = fake  # type: ignore[assignment]
    bridge._cfg["enabled"] = True
    return fake


def test_publish_operator_presence():
    fake = _use_fake_client()
    bridge._cfg["publish_presence"] = True
    op = types.SimpleNamespace(latitude=50.1, longitude=4.2, callsign="A1")
    asyncio.run(bridge.publish_operator_presence(op))
    url, payload = fake.calls[0]
    assert url == "/api/publish/presence"
    assert payload["lat"] == 50.1 and payload["callsign"] == "A1"
    assert payload["identity"] == 3  # FRIEND — own forces are friendly
    assert bridge._state.tx_presence == 1


def test_publish_tactical_object_carries_affiliation():
    fake = _use_fake_client()
    bridge._cfg["publish_contacts"] = True
    obj = types.SimpleNamespace(
        latitude=51.0,
        longitude=4.0,
        notes="tank",
        type="ENEMY",
        affiliation="HOSTILE",
        symbol_code="SHGPUCI-----",  # 2525C letter code — not a valid 2525D SIDC
    )
    asyncio.run(bridge.publish_tactical_object(obj))
    url, payload = fake.calls[0]
    assert url == "/api/publish/contact"
    assert payload["description"] == "tank"
    assert payload["identity"] == 6  # HOSTILE
    assert payload["callsign"] == "tank"
    assert (
        payload["sidc"] == "SHGPUCI-----"
    )  # passed as a hint; JDSS ignores if invalid
    assert bridge._state.tx_contacts == 1


@pytest.mark.parametrize(
    "affiliation,expected",
    [("FRIENDLY", 3), ("NEUTRAL", 4), ("UNKNOWN", 1), ("HOSTILE", 6), ("ENEMY", 6)],
)
def test_publish_tactical_object_identity_mapping(affiliation, expected):
    fake = _use_fake_client()
    bridge._cfg["publish_contacts"] = True
    obj = types.SimpleNamespace(
        latitude=1.0, longitude=2.0, notes="x", type="MARKER", affiliation=affiliation
    )
    asyncio.run(bridge.publish_tactical_object(obj))
    assert fake.calls[0][1]["identity"] == expected


def test_publish_chat_broadcast():
    fake = _use_fake_client()
    bridge._cfg["publish_chat"] = True
    msg = types.SimpleNamespace(
        message_type="BROADCAST", content="hello", receiver_id=None
    )
    asyncio.run(bridge.publish_chat(msg, sender=types.SimpleNamespace(callsign="A1")))
    assert fake.calls == [("/api/publish/chat", {"text": "hello", "recipient": "all"})]
    assert bridge._state.tx_chat == 1


def test_publish_noop_when_toggle_off():
    fake = _use_fake_client()
    bridge._cfg["publish_presence"] = False
    op = types.SimpleNamespace(latitude=1.0, longitude=2.0, callsign="A1")
    asyncio.run(bridge.publish_operator_presence(op))
    assert fake.calls == []


def test_publish_noop_when_client_down():
    bridge._client = None
    bridge._cfg["enabled"] = True
    bridge._cfg["publish_presence"] = True
    op = types.SimpleNamespace(latitude=1.0, longitude=2.0, callsign="A1")
    asyncio.run(bridge.publish_operator_presence(op))  # must not raise
    assert bridge._state.tx_presence == 0


# ── Admin endpoints ───────────────────────────────────────────────────────────


def test_status_endpoint_requires_auth(client):
    assert client.get("/jdss/status").status_code == 401


def test_status_endpoint_ok(client):
    from tests.conftest import admin_token

    tok = admin_token(client)
    r = client.get("/jdss/status", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert "base_url" in body and "rx_messages" in body


def test_config_get_and_put(client, tmp_path, monkeypatch):
    from tests.conftest import admin_token

    monkeypatch.setattr(bridge, "_CFG_FILE", tmp_path / "jdss_config.json")
    tok = admin_token(client)
    assert client.get("/jdss/config", headers=auth(tok)).status_code == 200

    r = client.put(
        "/jdss/config",
        json={"base_url": "http://192.168.0.202:8000", "enabled": False},
        headers=auth(tok),
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_config_put_forbidden_for_operator(client):
    from tests.conftest import register

    _, tok, _ = register(client, role="OPERATOR")
    r = client.put("/jdss/config", json={"enabled": True}, headers=auth(tok))
    assert r.status_code == 403
