from __future__ import annotations

from tests.conftest import auth, register


def test_health(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_me(client) -> None:
    callsign, token, _ = register(client)
    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["callsign"] == callsign


def test_position_update_and_live(client) -> None:
    _, token, _ = register(client)
    r = client.post(
        "/tracking/position",
        headers=auth(token),
        json={"latitude": 50.85, "longitude": 4.35, "altitude": 50.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["latitude"] == 50.85
    assert body["status"] == "ONLINE"

    live = client.get("/tracking/live", headers=auth(token)).json()
    assert any(o["callsign"] == body["callsign"] for o in live)


def test_tactical_object_lifecycle(client) -> None:
    _, token, _ = register(client)
    r = client.post(
        "/tactical-objects",
        headers=auth(token),
        json={
            "type": "ENEMY",
            "symbol_code": "SHGPUCI----D",
            "latitude": 50.9,
            "longitude": 4.4,
            "notes": "Suspected vehicle",
        },
    )
    assert r.status_code == 201
    obj_id = r.json()["id"]

    listed = client.get("/tactical-objects", headers=auth(token)).json()
    assert any(o["id"] == obj_id for o in listed)

    assert client.delete(f"/tactical-objects/{obj_id}", headers=auth(token)).status_code == 204
