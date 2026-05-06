from __future__ import annotations

import uuid


def _register(client, role: str = "OPERATOR") -> tuple[str, str]:
    callsign = f"OP-{uuid.uuid4().hex[:8].upper()}"
    r = client.post(
        "/auth/register",
        json={"callsign": callsign, "password": "pw123456", "role": role},
    )
    assert r.status_code == 201, r.text
    return callsign, r.json()["access_token"]


def test_health(client) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_me(client) -> None:
    callsign, token = _register(client)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["callsign"] == callsign


def test_position_update_and_live(client) -> None:
    _, token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/tracking/position",
        headers=headers,
        json={"latitude": 50.85, "longitude": 4.35, "altitude": 50.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["latitude"] == 50.85
    assert body["status"] == "ONLINE"

    live = client.get("/tracking/live", headers=headers).json()
    assert any(o["callsign"] == body["callsign"] for o in live)


def test_tactical_object_lifecycle(client) -> None:
    _, token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/tactical-objects",
        headers=headers,
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

    listed = client.get("/tactical-objects", headers=headers).json()
    assert any(o["id"] == obj_id for o in listed)

    assert client.delete(f"/tactical-objects/{obj_id}", headers=headers).status_code == 204
