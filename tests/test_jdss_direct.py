"""Tests for the native Front↔JDSS protocol core (front/jdss/direct.py).

Pure functions only — no Qt, no network — so they run in the standard suite.
The Qt wrapper (front.jdss.client) needs PyQt6 + a live gateway and is exercised
by the live end-to-end check in the repo's tooling, not here.
"""

from __future__ import annotations

import pytest

from front.jdss import direct


@pytest.mark.parametrize(
    "affiliation,type_,expected",
    [
        ("FRIENDLY", "MARKER", 3),
        ("FRIEND", None, 3),
        ("NEUTRAL", None, 4),
        ("HOSTILE", None, 6),
        ("ENEMY", None, 6),
        ("UNKNOWN", None, 1),
        ("", "ENEMY", 6),  # affiliation missing → infer from type
        ("", "POI", 1),  # nothing → UNKNOWN, never silently hostile
        (None, None, 1),
    ],
)
def test_affiliation_to_identity(affiliation, type_, expected):
    assert direct.affiliation_to_identity(affiliation, type_) == expected


def test_ws_url():
    assert (
        direct.ws_url("http://192.168.0.167:8000")
        == "ws://192.168.0.167:8000/ws/events"
    )
    assert direct.ws_url("https://gw:8000/") == "wss://gw:8000/ws/events"


def test_presence_payload_carries_identity():
    p = direct.presence_payload(50.1, 4.2, "A1")
    assert p == {
        "lat": 50.1,
        "lon": 4.2,
        "callsign": "A1",
        "battery_pct": None,
        "identity": 3,
    }


def test_contact_payload_compliance_fields():
    p = direct.contact_payload(
        51.0, 4.0, "tank", identity=6, callsign="tank", sidc="SHGPUCI-----"
    )
    assert p["identity"] == 6
    assert p["callsign"] == "tank"
    assert p["sidc"] == "SHGPUCI-----"
    assert p["description"] == "tank"


def test_chat_payload():
    assert direct.chat_payload("hi") == {"text": "hi", "recipient": "all"}


def test_is_inbound_received_vs_sent():
    assert direct.is_inbound({"direction": "received", "originator_id": "rif-1"})
    assert not direct.is_inbound({"direction": "sent", "originator_id": "rif-1"})
    assert not direct.is_inbound({"direction": "snapshot"})
    assert not direct.is_inbound({"direction": "heartbeat"})


def test_is_inbound_skips_own_node():
    evt = {"direction": "received", "originator_id": "node-a"}
    assert direct.is_inbound(evt, own_node_id="other")
    assert not direct.is_inbound(evt, own_node_id="node-a")


def test_normalize_contact_event():
    evt = {
        "direction": "received",
        "type": "ContactSighting",
        "originator_id": "obs-1",
        "callsign": "OBS-1",
        "message_id": "c1",
        "body": {
            "type": "ContactSighting",
            "location": {"lat": 51.0, "lon": 4.0},
            "identity": 6,
            "description": "2x dismounts",
            "sidc": "10061000001100000000",
        },
    }
    n = direct.normalize_event(evt)
    assert n is not None
    assert n["type"] == "ContactSighting"
    assert n["lat"] == 51.0 and n["lon"] == 4.0
    assert n["identity"] == 6 and n["affiliation"] == "HOSTILE"
    assert n["description"] == "2x dismounts"
    assert n["callsign"] == "OBS-1"


def test_normalize_ignores_non_message_frames():
    assert direct.normalize_event({"direction": "snapshot", "snapshot": {}}) is None
    assert direct.normalize_event({"direction": "heartbeat"}) is None
