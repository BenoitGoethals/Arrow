"""Message origin marker (source = ARROW | JDSS | ATAK).

Native messages sent through the API default to ARROW; the field is persisted and
surfaced on MessageOut so the web client can badge each bubble by origin. JDSS/ATAK
tagging is covered in ``test_jdss_bridge`` and the CoT GeoChat path respectively.
"""

from __future__ import annotations

from tests.conftest import admin_token, auth


def test_native_message_source_defaults_to_arrow(client):
    tok = admin_token(client)
    r = client.post(
        "/messages",
        json={"content": "sitrep all stations", "message_type": "BROADCAST"},
        headers=auth(tok),
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["source"] == "ARROW"


def test_message_list_carries_source(client):
    tok = admin_token(client)
    client.post(
        "/messages",
        json={"content": "hello", "message_type": "BROADCAST"},
        headers=auth(tok),
    )
    r = client.get("/messages", headers=auth(tok))
    assert r.status_code == 200
    assert r.json()
    assert all("source" in m for m in r.json())
