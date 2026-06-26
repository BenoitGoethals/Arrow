"""EPIC intelligence workboard — CRUD and cascade tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import admin_token, auth

# ── Helpers ───────────────────────────────────────────────────────────────────


def _mk_project(client: TestClient, tok: str, name: str = "TEST PROJ") -> int:
    r = client.post(
        "/osint/projects",
        headers=auth(tok),
        json={"name": name, "description": "test", "color": "#388bfd"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mk_report(client: TestClient, tok: str) -> int:
    r = client.post(
        "/reports",
        headers=auth(tok),
        json={"type": "SPOT", "payload": {"detail": "spotted vehicle at grid 123456"}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mk_photo(client: TestClient, tok: str) -> int | None:
    hdrs = {**auth(tok), "Content-Type": "image/jpeg", "X-Filename": "test.jpg"}
    r = client.post("/photos", headers=hdrs, content=b"fakejpegdata")
    return r.json().get("id") if r.status_code in (200, 201) else None


# ── Project tests ─────────────────────────────────────────────────────────────


def test_create_project(client: TestClient) -> None:
    tok = admin_token(client)
    r = client.post(
        "/osint/projects",
        headers=auth(tok),
        json={
            "name": "ALPHA COLLECTION",
            "description": "Intel ops",
            "color": "#c084fc",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "ALPHA COLLECTION"
    assert body["color"] == "#c084fc"
    assert body["status"] == "ACTIVE"
    assert body["node_count"] == 0


def test_list_projects(client: TestClient) -> None:
    tok = admin_token(client)
    _mk_project(client, tok, "PROJ A")
    _mk_project(client, tok, "PROJ B")
    r = client.get("/osint/projects", headers=auth(tok))
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "PROJ A" in names and "PROJ B" in names


def test_update_project(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    r = client.put(
        f"/osint/projects/{pid}",
        headers=auth(tok),
        json={"name": "RENAMED", "color": "#3fb950"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "RENAMED"
    assert r.json()["color"] == "#3fb950"


def test_archive_project(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    r = client.put(
        f"/osint/projects/{pid}",
        headers=auth(tok),
        json={"status": "ARCHIVED"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ARCHIVED"


def test_invalid_status_rejected(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    r = client.put(
        f"/osint/projects/{pid}",
        headers=auth(tok),
        json={"status": "BOGUS"},
    )
    assert r.status_code == 422


def test_delete_project_cascade(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep_id = _mk_report(client, tok)

    # Add a node
    client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep_id, "x": 100, "y": 100},
    )
    # Delete project
    r = client.delete(f"/osint/projects/{pid}", headers=auth(tok))
    assert r.status_code == 204

    # Board must 404
    r2 = client.get(f"/osint/projects/{pid}", headers=auth(tok))
    assert r2.status_code == 404


# ── Node tests ────────────────────────────────────────────────────────────────


def test_add_report_node(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep_id = _mk_report(client, tok)

    r = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep_id, "x": 200, "y": 150},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["node_type"] == "REPORT"
    assert body["report_id"] == rep_id
    assert body["report_type"] == "SPOT"


def test_report_node_denormalized_fields(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep_id = _mk_report(client, tok)

    r = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep_id, "x": 10, "y": 10},
    )
    body = r.json()
    assert body["report_type"] == "SPOT"
    assert body["report_payload_preview"] is not None
    assert "spotted" in body["report_payload_preview"]


def test_add_note_node(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)

    r = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={
            "node_type": "NOTE",
            "title": "Analyst hypothesis",
            "content": "Three sightings suggest pre-positioning.",
            "tags": ["isr", "pattern"],
            "x": 300,
            "y": 200,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["node_type"] == "NOTE"
    assert body["title"] == "Analyst hypothesis"
    assert "isr" in body["tags"]


def test_add_entity_node(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)

    r = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={
            "node_type": "ENTITY",
            "entity_type": "VEHICLE",
            "title": "SUSPECT TRUCK",
            "x": 400,
            "y": 300,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["entity_type"] == "VEHICLE"


def test_invalid_node_type_rejected(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    r = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "BOGUS", "x": 10, "y": 10},
    )
    assert r.status_code == 422


def test_report_node_requires_report_id(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    r = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "x": 10, "y": 10},
    )
    assert r.status_code == 422


def test_move_node(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep_id = _mk_report(client, tok)

    r = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep_id, "x": 100, "y": 100},
    )
    nid = r.json()["id"]

    r2 = client.patch(
        f"/osint/projects/{pid}/nodes/{nid}",
        headers=auth(tok),
        json={"x": 500.0, "y": 350.0},
    )
    assert r2.status_code == 200
    assert r2.json()["x"] == 500.0
    assert r2.json()["y"] == 350.0


def test_patch_note_content(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)

    nid = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "NOTE", "content": "original", "x": 10, "y": 10},
    ).json()["id"]

    r = client.patch(
        f"/osint/projects/{pid}/nodes/{nid}",
        headers=auth(tok),
        json={"content": "updated", "tags": ["confirmed"]},
    )
    assert r.status_code == 200
    assert r.json()["content"] == "updated"
    assert "confirmed" in r.json()["tags"]


def test_delete_node_cascades_links(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep1 = _mk_report(client, tok)
    rep2 = _mk_report(client, tok)

    nid1 = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep1, "x": 10, "y": 10},
    ).json()["id"]
    nid2 = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep2, "x": 200, "y": 10},
    ).json()["id"]

    # Link them
    lk = client.post(
        f"/osint/projects/{pid}/links",
        headers=auth(tok),
        json={"source_node_id": nid1, "target_node_id": nid2, "link_type": "RELATED"},
    ).json()

    # Delete source node → link must be gone
    client.delete(f"/osint/projects/{pid}/nodes/{nid1}", headers=auth(tok))
    board = client.get(f"/osint/projects/{pid}", headers=auth(tok)).json()
    link_ids = [lk2["id"] for lk2 in board["links"]]
    assert lk["id"] not in link_ids


# ── Link tests ────────────────────────────────────────────────────────────────


def test_create_link(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep1 = _mk_report(client, tok)
    rep2 = _mk_report(client, tok)

    nid1 = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep1, "x": 10, "y": 10},
    ).json()["id"]
    nid2 = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep2, "x": 200, "y": 10},
    ).json()["id"]

    r = client.post(
        f"/osint/projects/{pid}/links",
        headers=auth(tok),
        json={
            "source_node_id": nid1,
            "target_node_id": nid2,
            "link_type": "CONFIRMS",
            "label": "Same callsign",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["link_type"] == "CONFIRMS"
    assert body["label"] == "Same callsign"


def test_self_link_rejected(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep_id = _mk_report(client, tok)
    nid = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep_id, "x": 10, "y": 10},
    ).json()["id"]

    r = client.post(
        f"/osint/projects/{pid}/links",
        headers=auth(tok),
        json={"source_node_id": nid, "target_node_id": nid, "link_type": "RELATED"},
    )
    assert r.status_code == 422


def test_invalid_link_type_rejected(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep1 = _mk_report(client, tok)
    rep2 = _mk_report(client, tok)

    nid1 = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep1, "x": 10, "y": 10},
    ).json()["id"]
    nid2 = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep2, "x": 200, "y": 10},
    ).json()["id"]

    r = client.post(
        f"/osint/projects/{pid}/links",
        headers=auth(tok),
        json={"source_node_id": nid1, "target_node_id": nid2, "link_type": "BOGUS"},
    )
    assert r.status_code == 422


def test_delete_link(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep1 = _mk_report(client, tok)
    rep2 = _mk_report(client, tok)

    nid1 = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep1, "x": 10, "y": 10},
    ).json()["id"]
    nid2 = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep2, "x": 200, "y": 10},
    ).json()["id"]

    lid = client.post(
        f"/osint/projects/{pid}/links",
        headers=auth(tok),
        json={"source_node_id": nid1, "target_node_id": nid2, "link_type": "RELATED"},
    ).json()["id"]

    r = client.delete(f"/osint/projects/{pid}/links/{lid}", headers=auth(tok))
    assert r.status_code == 204

    board = client.get(f"/osint/projects/{pid}", headers=auth(tok)).json()
    assert not any(lk2["id"] == lid for lk2 in board["links"])


# ── Board and search ──────────────────────────────────────────────────────────


def test_get_board_returns_nodes_and_links(client: TestClient) -> None:
    tok = admin_token(client)
    pid = _mk_project(client, tok)
    rep_id = _mk_report(client, tok)

    client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": rep_id, "x": 10, "y": 10},
    )

    r = client.get(f"/osint/projects/{pid}", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert "project" in body and "nodes" in body and "links" in body
    assert body["project"]["id"] == pid
    assert len(body["nodes"]) == 1


def test_search_reports(client: TestClient) -> None:
    tok = admin_token(client)
    _mk_report(client, tok)

    r = client.get("/osint/search?q=SPOT&types=REPORT", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert "reports" in body and "photos" in body
    assert any(rep["type"] == "SPOT" for rep in body["reports"])


def test_search_empty_query(client: TestClient) -> None:
    tok = admin_token(client)
    _mk_report(client, tok)

    r = client.get("/osint/search?q=&types=REPORT", headers=auth(tok))
    assert r.status_code == 200
    assert len(r.json()["reports"]) >= 1


def test_unauthenticated_rejected(client: TestClient) -> None:
    r = client.get("/osint/projects")
    assert r.status_code == 401
