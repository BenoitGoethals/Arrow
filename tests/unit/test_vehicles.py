"""CRUD, role-gating, and derived-position behaviour for vehicles."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import admin_token, auth, register


def test_admin_create_and_list(client: TestClient) -> None:
    tok = admin_token(client)
    r = client.post("/vehicles", headers=auth(tok), json={
        "callsign": "WARHORSE-1",
        "vehicle_type": "Boxer",
        "affiliation": "FRIENDLY",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["callsign"] == "WARHORSE-1"
    assert body["ops_status"] == "OPS"
    assert body["latitude"] is None and body["online"] is False

    listing = client.get("/vehicles", headers=auth(tok)).json()
    assert any(v["id"] == body["id"] for v in listing)


def test_operator_cannot_mutate(client: TestClient) -> None:
    _, op_tok, _ = register(client, role="OPERATOR")
    r = client.post("/vehicles", headers=auth(op_tok), json={"callsign": "X"})
    assert r.status_code == 403


def test_invalid_ops_status_rejected(client: TestClient) -> None:
    tok = admin_token(client)
    r = client.post("/vehicles", headers=auth(tok),
                    json={"callsign": "X", "ops_status": "BOGUS"})
    assert r.status_code == 422


def test_position_follows_assigned_operator(client: TestClient) -> None:
    tok = admin_token(client)
    _, op_tok, op_id = register(client, role="OPERATOR")

    # Operator reports a fix → becomes ONLINE with a position.
    r = client.post("/tracking/position", headers=auth(op_tok),
                    json={"latitude": 50.85, "longitude": 4.35, "altitude": 10.0})
    assert r.status_code == 200, r.text

    veh = client.post("/vehicles", headers=auth(tok), json={
        "callsign": "MULE-1", "operator_id": op_id,
    }).json()

    got = client.get(f"/vehicles/{veh['id']}", headers=auth(tok)).json()
    assert got["latitude"] == 50.85
    assert got["longitude"] == 4.35
    assert got["online"] is True


def test_ops_status_endpoint_sets_operator_status(client: TestClient) -> None:
    tok = admin_token(client)
    _, _, op_id = register(client, role="OPERATOR")

    r = client.patch(f"/operators/{op_id}/ops-status", headers=auth(tok),
                     json={"ops_status": "KIA"})
    assert r.status_code == 200, r.text
    assert r.json()["ops_status"] == "KIA"

    me = client.get(f"/operators/{op_id}", headers=auth(tok)).json()
    assert me["ops_status"] == "KIA"


def test_ops_status_rejects_invalid(client: TestClient) -> None:
    tok = admin_token(client)
    _, _, op_id = register(client, role="OPERATOR")
    r = client.patch(f"/operators/{op_id}/ops-status", headers=auth(tok),
                     json={"ops_status": "NOPE"})
    assert r.status_code == 422
