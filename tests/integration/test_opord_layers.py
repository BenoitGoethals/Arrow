"""OPORD layer attachments — freeze, list, detach, export, PDF, self-containment."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import admin_token, auth


def _mk_overlay(client: TestClient, tok: str) -> int:
    ids = []
    for i in range(2):
        r = client.post(
            "/tactical-objects",
            headers=auth(tok),
            json={"type": "POI", "latitude": 50.85 + i, "longitude": 4.35 + i},
        )
        ids.append(r.json()["id"])
    return client.post(
        "/overlays", headers=auth(tok), json={"name": "OV", "object_ids": ids}
    ).json()["id"]


def _mk_opord(client: TestClient, tok: str) -> int:
    r = client.post("/opord", headers=auth(tok), json={"title": "OPORD ONE"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_attach_lists_with_frozen_envelope(client: TestClient) -> None:
    tok = admin_token(client)
    ov_id = _mk_overlay(client, tok)
    opord_id = _mk_opord(client, tok)

    r = client.post(
        f"/opord/{opord_id}/layers",
        headers=auth(tok),
        json={"kind": "OVERLAY", "source_id": ov_id},
    )
    assert r.status_code == 200, r.text
    attachments = r.json()["attached_layers"]
    assert len(attachments) == 1
    att = attachments[0]
    assert att["kind"] == "OVERLAY"
    assert att["source_id"] == ov_id
    assert att["envelope"]["payload"]["objects"]  # embedded, self-contained

    # The list endpoint omits the bulky envelope.
    listing = client.get("/opord", headers=auth(tok)).json()
    listed = next(o for o in listing if o["id"] == opord_id)
    assert listed["attached_layers"][0]["envelope"] is None


def test_attachment_survives_source_deletion(client: TestClient) -> None:
    tok = admin_token(client)
    ov_id = _mk_overlay(client, tok)
    opord_id = _mk_opord(client, tok)
    client.post(
        f"/opord/{opord_id}/layers",
        headers=auth(tok),
        json={"kind": "OVERLAY", "source_id": ov_id},
    )

    # Delete the live overlay — the frozen attachment must remain intact.
    assert client.delete(f"/overlays/{ov_id}", headers=auth(tok)).status_code == 204
    opord = client.get(f"/opord/{opord_id}", headers=auth(tok)).json()
    assert len(opord["attached_layers"]) == 1
    assert opord["attached_layers"][0]["envelope"]["payload"]["objects"]


def test_attachment_export_is_reimportable(client: TestClient) -> None:
    tok = admin_token(client)
    ov_id = _mk_overlay(client, tok)
    opord_id = _mk_opord(client, tok)
    att = client.post(
        f"/opord/{opord_id}/layers",
        headers=auth(tok),
        json={"kind": "OVERLAY", "source_id": ov_id},
    ).json()["attached_layers"][0]

    exp = client.get(f"/opord/{opord_id}/layers/{att['id']}/export", headers=auth(tok))
    assert exp.status_code == 200, exp.text
    env = exp.json()
    assert env["arrow_layer_export"] == "1"
    # The exported frozen envelope re-imports cleanly.
    res = client.post("/layers/import", headers=auth(tok), json=env)
    assert res.status_code == 200, res.text


def test_detach(client: TestClient) -> None:
    tok = admin_token(client)
    ov_id = _mk_overlay(client, tok)
    opord_id = _mk_opord(client, tok)
    att_id = client.post(
        f"/opord/{opord_id}/layers",
        headers=auth(tok),
        json={"kind": "OVERLAY", "source_id": ov_id},
    ).json()["attached_layers"][0]["id"]

    r = client.delete(f"/opord/{opord_id}/layers/{att_id}", headers=auth(tok))
    assert r.status_code == 200
    assert r.json()["attached_layers"] == []


def test_pdf_includes_attachments(client: TestClient) -> None:
    tok = admin_token(client)
    ov_id = _mk_overlay(client, tok)
    opord_id = _mk_opord(client, tok)
    client.post(
        f"/opord/{opord_id}/layers",
        headers=auth(tok),
        json={"kind": "OVERLAY", "source_id": ov_id},
    )
    r = client.get(f"/opord/{opord_id}/pdf", headers=auth(tok))
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_attach_unknown_source_404(client: TestClient) -> None:
    tok = admin_token(client)
    opord_id = _mk_opord(client, tok)
    r = client.post(
        f"/opord/{opord_id}/layers",
        headers=auth(tok),
        json={"kind": "OVERLAY", "source_id": 99999},
    )
    assert r.status_code == 404
