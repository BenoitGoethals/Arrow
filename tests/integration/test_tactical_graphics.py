"""Tests for the new tactical control graphics on TacticalObject.

Phase 1 of the tactical-graphics layer added two columns:

  • ``rotation`` (float, default 0) — heading clockwise from north for oriented
    point graphics (attack axis, ambush, defense).
  • ``geometry`` (text JSON, default "") — full geometry for line/polygon
    graphics: ``{"type": "line"|"polygon", "coords": [[lat,lon], ...]}``.

These tests cover the wire-format round trip + the WS broadcast so a future
schema rename can't silently break either client.
"""

from __future__ import annotations

import json

from tests.conftest import auth, register


def test_create_oriented_point_graphic_persists_rotation(client) -> None:
    _, tok, _ = register(client)
    r = client.post("/tactical-objects", headers=auth(tok), json={
        "type": "ATK_AXIS",
        "latitude": 50.85, "longitude": 4.35,
        "rotation": 137.5,
        "notes": "main effort, axis BLUE",
    })
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["rotation"] == 137.5
    assert out["geometry"] == ""
    # Round-trip via list endpoint
    listed = client.get("/tactical-objects", headers=auth(tok)).json()
    found = next(o for o in listed if o["id"] == out["id"])
    assert found["rotation"] == 137.5


def test_create_line_graphic_persists_geometry(client) -> None:
    _, tok, _ = register(client)
    coords = [[50.85, 4.35], [50.86, 4.37], [50.87, 4.40]]
    payload_geom = json.dumps({"type": "line", "coords": coords})
    r = client.post("/tactical-objects", headers=auth(tok), json={
        "type": "FLET",
        "latitude": coords[0][0], "longitude": coords[0][1],
        "rotation": 0,
        "geometry": payload_geom,
    })
    assert r.status_code == 201, r.text
    out = r.json()
    parsed = json.loads(out["geometry"])
    assert parsed["type"] == "line"
    assert parsed["coords"] == coords


def test_create_polygon_graphic_persists_geometry(client) -> None:
    _, tok, _ = register(client)
    coords = [[50.85, 4.35], [50.86, 4.37], [50.84, 4.38]]
    r = client.post("/tactical-objects", headers=auth(tok), json={
        "type": "OBJ_AREA",
        "latitude": coords[0][0], "longitude": coords[0][1],
        "geometry": json.dumps({"type": "polygon", "coords": coords}),
    })
    assert r.status_code == 201, r.text
    out = r.json()
    parsed = json.loads(out["geometry"])
    assert parsed["type"] == "polygon"
    assert parsed["coords"] == coords


def test_default_rotation_and_geometry(client) -> None:
    """Existing clients that don't set rotation/geometry must still work."""
    _, tok, _ = register(client)
    r = client.post("/tactical-objects", headers=auth(tok), json={
        "type": "POI",
        "latitude": 50.85, "longitude": 4.35,
    })
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["rotation"] == 0.0
    assert out["geometry"] == ""


def test_graphic_creation_broadcasts_via_websocket(client) -> None:
    _, prod_tok, _    = register(client)
    _, watcher_tok, _ = register(client)
    with client.websocket_connect(f"/ws?token={watcher_tok}") as ws:
        client.post("/tactical-objects", headers=auth(prod_tok), json={
            "type": "AMBUSH",
            "latitude": 50.85, "longitude": 4.35,
            "rotation": 270,
        })
        # Drain non-stream channels until we get the tactical-object event
        for _ in range(20):
            msg = ws.receive_json()
            if msg.get("channel") == "tactical-object":
                break
        else:
            raise AssertionError("no tactical-object broadcast received")
        assert msg["event"] == "created"
        assert msg["data"]["type"] == "AMBUSH"
        assert msg["data"]["rotation"] == 270


def test_echelon_persists_across_round_trip(client) -> None:
    """Echelon tag (TM/SEC/PL/COY) survives create + list + WS broadcast."""
    _, tok, _ = register(client)
    _, watcher_tok, _ = register(client)

    with client.websocket_connect(f"/ws?token={watcher_tok}") as ws:
        for echelon in ("TM", "SEC", "PL", "COY"):
            r = client.post("/tactical-objects", headers=auth(tok), json={
                "type": "ATK_AXIS",
                "latitude": 50.85, "longitude": 4.35,
                "rotation": 90,
                "echelon": echelon,
            })
            assert r.status_code == 201, r.text
            assert r.json()["echelon"] == echelon
            # WebSocket broadcast carries the echelon
            for _ in range(20):
                msg = ws.receive_json()
                if msg.get("channel") == "tactical-object":
                    break
            else:
                raise AssertionError("no broadcast")
            assert msg["data"]["echelon"] == echelon

    # GET list returns it
    listed = client.get("/tactical-objects", headers=auth(tok)).json()
    assert {o["echelon"] for o in listed if o["type"] == "ATK_AXIS"} >= {"TM", "SEC", "PL", "COY"}


def test_echelon_default_empty(client) -> None:
    """Clients that don't set echelon must still create successfully."""
    _, tok, _ = register(client)
    r = client.post("/tactical-objects", headers=auth(tok), json={
        "type": "POI",
        "latitude": 50.85, "longitude": 4.35,
    })
    assert r.status_code == 201, r.text
    assert r.json()["echelon"] == ""


def test_new_task_types_round_trip(client) -> None:
    """COUNTERATTACK / BLOCK / BYPASS / WITHDRAW are stored as opaque type strings."""
    _, tok, _ = register(client)
    for t in ("COUNTERATTACK", "BLOCK", "BYPASS", "WITHDRAW"):
        r = client.post("/tactical-objects", headers=auth(tok), json={
            "type": t,
            "latitude": 50.85, "longitude": 4.35,
            "rotation": 45,
            "echelon": "PL",
        })
        assert r.status_code == 201, f"{t}: {r.text}"
        out = r.json()
        assert out["type"] == t
        assert out["echelon"] == "PL"
        assert out["rotation"] == 45


def test_invalid_geometry_string_still_accepted_as_opaque(client) -> None:
    """`geometry` is opaque JSON text on the backend — invalid JSON is the client's
    problem, not a server error. Only the schema (string) is enforced."""
    _, tok, _ = register(client)
    r = client.post("/tactical-objects", headers=auth(tok), json={
        "type": "FLOT",
        "latitude": 50.85, "longitude": 4.35,
        "geometry": "this is not JSON, but the wire field is just a string",
    })
    assert r.status_code == 201, r.text
    assert r.json()["geometry"].startswith("this is not JSON")
