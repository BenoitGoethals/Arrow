"""Tests for the GET /photos catalogue endpoint used by the Photos browser."""

from __future__ import annotations

import io

from tests.conftest import auth, register


def _upload_photo(client, tok, name="test.jpg") -> int:
    # Tiny JPEG header — enough for the photos endpoint to accept.
    data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    r = client.post(
        "/photos",
        files={"file": (name, io.BytesIO(data), "image/jpeg")},
        headers=auth(tok),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_list_photos_requires_auth(client) -> None:
    assert client.get("/photos").status_code == 401


def test_list_photos_empty(client) -> None:
    _, tok, _ = register(client)
    assert client.get("/photos", headers=auth(tok)).json() == []


def test_list_photos_returns_metadata_with_back_refs(client) -> None:
    _, tok, op_id = register(client)

    # Upload three photos and attach them to:
    #   1. a tactical object (photo_id field)
    #   2. a chat message  (photo_id field)
    #   3. a report        (payload contains "photo_id": N as JSON)
    pid_to  = _upload_photo(client, tok, "obj.jpg")
    pid_msg = _upload_photo(client, tok, "msg.jpg")
    pid_rep = _upload_photo(client, tok, "rep.jpg")
    pid_orph = _upload_photo(client, tok, "orph.jpg")

    to_id = client.post("/tactical-objects", headers=auth(tok), json={
        "type": "POI", "latitude": 50.85, "longitude": 4.35,
        "photo_id": pid_to, "notes": "obj attached",
    }).json()["id"]

    msg_id = client.post("/messages", headers=auth(tok), json={
        "content": "with photo", "message_type": "BROADCAST",
        "photo_id": pid_msg,
    }).json()["id"]

    rep_id = client.post("/reports", headers=auth(tok), json={
        "type": "SPOT",
        "payload": {"grid": "31UFS123456", "photo_id": pid_rep},
    }).json()["id"]

    listed = client.get("/photos", headers=auth(tok)).json()
    by_id = {p["id"]: p for p in listed}
    assert {pid_to, pid_msg, pid_rep, pid_orph}.issubset(by_id.keys())

    assert by_id[pid_to]["tactical_object_id"] == to_id
    assert by_id[pid_to]["message_id"] is None

    assert by_id[pid_msg]["message_id"] == msg_id
    assert by_id[pid_msg]["tactical_object_id"] is None

    assert by_id[pid_rep]["report_id"] == rep_id

    # Orphan photo: still listed, but no back-refs
    orph = by_id[pid_orph]
    assert orph["tactical_object_id"] is None
    assert orph["message_id"]         is None
    assert orph["report_id"]          is None
    assert orph["mime_type"]          == "image/jpeg"
    assert orph["url"]                == f"/photos/{pid_orph}"
