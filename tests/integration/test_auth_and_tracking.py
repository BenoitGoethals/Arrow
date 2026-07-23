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

    assert (
        client.delete(f"/tactical-objects/{obj_id}", headers=auth(token)).status_code
        == 204
    )


def _position_source(op_id: int) -> str | None:
    """Read an operator's position_source straight from the test DB.

    conftest rebinds SessionLocal to the in-memory engine for the test's lifetime,
    so this hits the same data the request handlers wrote. Used because /auth/me
    doesn't expose position_source and /tracking/live filters out operators that
    have never posted a fix (which is exactly the case under test here).
    """
    from backend.storage.database import SessionLocal
    from backend.storage.models import Operator

    db = SessionLocal()
    try:
        return db.get(Operator, op_id).position_source
    finally:
        db.close()


def test_login_with_front_header_sets_position_source(client) -> None:
    """The COP buckets device type by position_source; the desktop front must show
    as FRONT from login, before any position fix, via the X-Client-Type header."""
    callsign, _, op_id = register(client)
    assert _position_source(op_id) is None  # no fix yet -> would bucket as OTHER

    r = client.post(
        "/auth/login",
        data={"username": callsign, "password": "pw123456"},
        headers={"X-Client-Type": "FRONT"},
    )
    assert r.status_code == 200, r.text
    assert _position_source(op_id) == "FRONT"


def test_login_android_header_sets_position_source(client) -> None:
    callsign, _, op_id = register(client)
    r = client.post(
        "/auth/login",
        data={"username": callsign, "password": "pw123456"},
        headers={"X-Client-Type": "android"},  # case-insensitive
    )
    assert r.status_code == 200, r.text
    assert _position_source(op_id) == "ANDROID"


def test_login_without_client_header_leaves_source_unset(client) -> None:
    callsign, _, op_id = register(client)
    r = client.post("/auth/login", data={"username": callsign, "password": "pw123456"})
    assert r.status_code == 200
    assert _position_source(op_id) is None


def test_login_ignores_unknown_client_type(client) -> None:
    callsign, _, op_id = register(client)
    r = client.post(
        "/auth/login",
        data={"username": callsign, "password": "pw123456"},
        headers={"X-Client-Type": "SOMETHING"},
    )
    assert r.status_code == 200
    assert _position_source(op_id) is None
