"""CRUD + role-gating + filtering for saved overlays."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import admin_token, auth, register


def _make_objects(client: TestClient, token: str, n: int = 3) -> list[int]:
    """Drop a handful of tactical objects so overlays have real ids to point at."""
    ids: list[int] = []
    for i in range(n):
        r = client.post(
            "/tactical-objects",
            headers=auth(token),
            json={
                "type": "POI",
                "latitude": 50.85 + i * 0.01,
                "longitude": 4.35 + i * 0.01,
                "notes": f"poi-{i}",
                "visibility": "COMPANY",
            },
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


def test_create_list_get(client: TestClient) -> None:
    tok = admin_token(client)
    ids = _make_objects(client, tok, 3)

    r = client.post(
        "/overlays",
        headers=auth(tok),
        json={
            "name": "Op Alpha",
            "description": "Phase 1 graphics",
            "object_ids": ids,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Op Alpha"
    assert sorted(body["object_ids"]) == sorted(ids)
    overlay_id = body["id"]

    rows = client.get("/overlays", headers=auth(tok)).json()
    assert any(o["id"] == overlay_id for o in rows)

    detail = client.get(f"/overlays/{overlay_id}", headers=auth(tok)).json()
    assert sorted(detail["object_ids"]) == sorted(ids)


def test_unknown_object_ids_are_dropped(client: TestClient) -> None:
    tok = admin_token(client)
    real = _make_objects(client, tok, 1)[0]
    r = client.post(
        "/overlays",
        headers=auth(tok),
        json={
            "name": "Mixed",
            "object_ids": [real, 99999, 88888],
        },
    )
    assert r.status_code == 201
    assert r.json()["object_ids"] == [real]


def test_patch_round_trip(client: TestClient) -> None:
    tok = admin_token(client)
    ids = _make_objects(client, tok, 2)
    overlay = client.post(
        "/overlays",
        headers=auth(tok),
        json={
            "name": "Draft",
            "object_ids": ids[:1],
        },
    ).json()

    r = client.patch(
        f"/overlays/{overlay['id']}",
        headers=auth(tok),
        json={
            "name": "Final",
            "object_ids": ids,
        },
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Final"
    assert sorted(r.json()["object_ids"]) == sorted(ids)


def test_operator_cannot_mutate(client: TestClient) -> None:
    admin_tok = admin_token(client)
    ids = _make_objects(client, admin_tok, 1)
    _, op_token, _ = register(client, role="OPERATOR")

    # Operators can read.
    assert client.get("/overlays", headers=auth(op_token)).status_code == 200

    # Operators cannot create.
    r = client.post(
        "/overlays",
        headers=auth(op_token),
        json={
            "name": "Forbidden",
            "object_ids": ids,
        },
    )
    assert r.status_code == 403

    # Or delete.
    overlay = client.post(
        "/overlays",
        headers=auth(admin_tok),
        json={
            "name": "X",
            "object_ids": ids,
        },
    ).json()
    assert (
        client.delete(f"/overlays/{overlay['id']}", headers=auth(op_token)).status_code
        == 403
    )


def test_delete(client: TestClient) -> None:
    tok = admin_token(client)
    ids = _make_objects(client, tok, 1)
    overlay = client.post(
        "/overlays",
        headers=auth(tok),
        json={
            "name": "Doomed",
            "object_ids": ids,
        },
    ).json()
    assert (
        client.delete(f"/overlays/{overlay['id']}", headers=auth(tok)).status_code
        == 204
    )
    assert (
        client.get(f"/overlays/{overlay['id']}", headers=auth(tok)).status_code == 404
    )


def test_empty_object_list_is_valid(client: TestClient) -> None:
    """An overlay with no members is a useful placeholder while the BC is building it."""
    tok = admin_token(client)
    r = client.post(
        "/overlays",
        headers=auth(tok),
        json={
            "name": "Empty placeholder",
            "object_ids": [],
        },
    )
    assert r.status_code == 201
    assert r.json()["object_ids"] == []
