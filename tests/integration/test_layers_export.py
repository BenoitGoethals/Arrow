"""Portable layer export/import — overlays, KML layers, OSINT boards across missions."""

from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient

from tests.conftest import admin_token, auth, register

_SAMPLE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>HQ</name>
      <Point><coordinates>4.35,50.85,0</coordinates></Point>
    </Placemark>
    <Placemark><name>AO Bravo</name>
      <Point><coordinates>4.36,50.86,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""


def _mk_mission(client: TestClient, tok: str, name: str) -> int:
    r = client.post("/missions", headers=auth(tok), json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mk_objects(client: TestClient, tok: str, mission_id: int, n: int = 3) -> list[int]:
    hdrs = {**auth(tok), "X-Mission-ID": str(mission_id)}
    ids = []
    for i in range(n):
        r = client.post(
            "/tactical-objects",
            headers=hdrs,
            json={
                "type": "POI",
                "latitude": 50.85 + i * 0.01,
                "longitude": 4.35 + i * 0.01,
                "notes": f"poi-{i}",
                "geometry": "",
            },
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


# ── Overlay round-trip ──────────────────────────────────────────────────────


def test_overlay_export_then_import_into_other_mission(client: TestClient) -> None:
    tok = admin_token(client)
    mission_a = _mk_mission(client, tok, "ALPHA")
    mission_b = _mk_mission(client, tok, "BRAVO")
    ids = _mk_objects(client, tok, mission_a, 3)

    overlay = client.post(
        "/overlays",
        headers=auth(tok),
        json={"name": "Phase 1", "description": "graphics", "object_ids": ids},
    ).json()

    # Export → portable envelope with embedded object data, not bare ids.
    exp = client.get(f"/layers/overlays/{overlay['id']}/export", headers=auth(tok))
    assert exp.status_code == 200, exp.text
    env = exp.json()
    assert env["arrow_layer_export"] == "1"
    assert env["kind"] == "OVERLAY"
    assert len(env["payload"]["objects"]) == 3
    assert env["payload"]["objects"][0]["type"] == "POI"
    assert "latitude" in env["payload"]["objects"][0]

    # Import into mission B.
    res = client.post(
        "/layers/import",
        headers={**auth(tok), "X-Mission-ID": str(mission_b)},
        json=env,
    )
    assert res.status_code == 200, res.text
    assert res.json()["kind"] == "OVERLAY"
    new_overlay = client.get(f"/overlays/{res.json()['id']}", headers=auth(tok)).json()

    # Fresh objects with new ids — original overlay untouched.
    new_ids = new_overlay["object_ids"]
    assert len(new_ids) == 3
    assert set(new_ids).isdisjoint(set(ids))
    assert sorted(
        client.get(f"/overlays/{overlay['id']}", headers=auth(tok)).json()["object_ids"]
    ) == sorted(ids)

    # The recreated objects are scoped to mission B, not A.
    b_objs = client.get(
        "/tactical-objects", headers={**auth(tok), "X-Mission-ID": str(mission_b)}
    ).json()
    b_obj_ids = {o["id"] for o in b_objs}
    assert set(new_ids).issubset(b_obj_ids)
    a_objs = client.get(
        "/tactical-objects", headers={**auth(tok), "X-Mission-ID": str(mission_a)}
    ).json()
    assert set(new_ids).isdisjoint({o["id"] for o in a_objs})


# ── KML round-trip ──────────────────────────────────────────────────────────


def test_kml_export_then_import(client: TestClient) -> None:
    tok = admin_token(client)
    up = client.post(
        "/kml-layers",
        headers=auth(tok),
        files={
            "file": (
                "ao.kml",
                BytesIO(_SAMPLE_KML),
                "application/vnd.google-earth.kml+xml",
            )
        },
    )
    assert up.status_code == 201, up.text
    layer_id = up.json()["id"]
    feature_count = up.json()["feature_count"]

    env = client.get(f"/layers/kml/{layer_id}/export", headers=auth(tok)).json()
    assert env["kind"] == "KML"
    assert env["payload"]["feature_count"] == feature_count

    res = client.post("/layers/import", headers=auth(tok), json=env)
    assert res.status_code == 200, res.text
    new = client.get(f"/kml-layers/{res.json()['id']}", headers=auth(tok)).json()
    assert new["feature_count"] == feature_count
    assert len(new["features"]) == feature_count


# ── OSINT round-trip ────────────────────────────────────────────────────────


def test_osint_export_then_import_into_other_mission(client: TestClient) -> None:
    tok = admin_token(client)
    mission_a = _mk_mission(client, tok, "ALPHA")
    mission_b = _mk_mission(client, tok, "BRAVO")
    ha = {**auth(tok), "X-Mission-ID": str(mission_a)}

    pid = client.post(
        "/osint/projects", headers=ha, json={"name": "BOARD", "color": "#abcdef"}
    ).json()["id"]
    note = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=ha,
        json={"node_type": "NOTE", "title": "n1", "content": "hello", "x": 10, "y": 20},
    ).json()
    entity = client.post(
        f"/osint/projects/{pid}/nodes",
        headers=ha,
        json={"node_type": "ENTITY", "entity_type": "PERSON", "title": "Subject"},
    ).json()
    client.post(
        f"/osint/projects/{pid}/links",
        headers=ha,
        json={
            "source_node_id": note["id"],
            "target_node_id": entity["id"],
            "link_type": "ASSOCIATED_WITH",
        },
    )

    env = client.get(f"/layers/osint/{pid}/export", headers=auth(tok)).json()
    assert env["kind"] == "OSINT"
    assert len(env["payload"]["nodes"]) == 2
    assert env["payload"]["links"][0]["source"] in (0, 1)

    res = client.post(
        "/layers/import",
        headers={**auth(tok), "X-Mission-ID": str(mission_b)},
        json=env,
    )
    assert res.status_code == 200, res.text
    board = client.get(f"/osint/projects/{res.json()['id']}", headers=auth(tok)).json()
    assert board["project"]["mission_id"] == mission_b
    assert len(board["nodes"]) == 2
    assert len(board["links"]) == 1
    # Link endpoints point at the freshly-created nodes.
    node_ids = {n["id"] for n in board["nodes"]}
    assert board["links"][0]["source_node_id"] in node_ids
    assert board["links"][0]["target_node_id"] in node_ids


def test_osint_report_node_degrades_to_note(client: TestClient) -> None:
    tok = admin_token(client)
    report = client.post(
        "/reports",
        headers=auth(tok),
        json={"type": "SPOT", "payload": {"detail": "tank at grid 123456"}},
    ).json()
    pid = client.post("/osint/projects", headers=auth(tok), json={"name": "B"}).json()[
        "id"
    ]
    client.post(
        f"/osint/projects/{pid}/nodes",
        headers=auth(tok),
        json={"node_type": "REPORT", "report_id": report["id"]},
    )

    env = client.get(f"/layers/osint/{pid}/export", headers=auth(tok)).json()
    res = client.post("/layers/import", headers=auth(tok), json=env)
    board = client.get(f"/osint/projects/{res.json()['id']}", headers=auth(tok)).json()
    assert len(board["nodes"]) == 1
    node = board["nodes"][0]
    assert node["node_type"] == "NOTE"  # degraded — no dangling report FK
    assert node["report_id"] is None
    assert "SPOT" in (node["title"] or "")


# ── Guards ──────────────────────────────────────────────────────────────────


def test_import_rejects_unknown_version(client: TestClient) -> None:
    tok = admin_token(client)
    bad = {
        "arrow_layer_export": "999",
        "kind": "OVERLAY",
        "name": "x",
        "exported_at": "2026-01-01T00:00:00Z",
        "exported_by": 1,
        "payload": {"objects": []},
    }
    r = client.post("/layers/import", headers=auth(tok), json=bad)
    assert r.status_code == 422


def test_import_rejects_unknown_kind(client: TestClient) -> None:
    tok = admin_token(client)
    bad = {
        "arrow_layer_export": "1",
        "kind": "BOGUS",
        "name": "x",
        "exported_at": "2026-01-01T00:00:00Z",
        "exported_by": 1,
        "payload": {},
    }
    r = client.post("/layers/import", headers=auth(tok), json=bad)
    assert r.status_code == 422


def test_operator_cannot_import(client: TestClient) -> None:
    admin_tok = admin_token(client)
    _, op_tok, _ = register(client, role="OPERATOR")
    pid = client.post(
        "/osint/projects", headers=auth(admin_tok), json={"name": "B"}
    ).json()["id"]
    env = client.get(f"/layers/osint/{pid}/export", headers=auth(admin_tok)).json()
    # Export is readable by any operator…
    assert (
        client.get(f"/layers/osint/{pid}/export", headers=auth(op_tok)).status_code
        == 200
    )
    # …but import is gated to ADMIN/BATTLE_CAPTAIN.
    assert (
        client.post("/layers/import", headers=auth(op_tok), json=env).status_code == 403
    )
