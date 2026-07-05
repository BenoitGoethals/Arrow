"""Map reset + snapshot history + restore — `backend/admin/router.py`.

Lifecycle covered:
  • POST /admin/map/reset            captures every TacticalObject + clears the map
  • GET  /admin/map/snapshots        lists snapshots with metadata
  • GET  /admin/map/snapshots/{id}   returns the full payload
  • POST /admin/map/snapshots/{id}/restore  re-creates the objects (additive)
  • DELETE /admin/map/snapshots/{id} removes the snapshot record

Auth: every endpoint requires ADMIN. OPERATORS and BATTLE_CAPTAINS get 403.
"""

from __future__ import annotations

from tests.conftest import auth, register


def _make_object(client, tok, type_, **extras) -> int:
    r = client.post(
        "/tactical-objects",
        headers=auth(tok),
        json={
            "type": type_,
            "latitude": 50.85,
            "longitude": 4.35,
            **extras,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_reset_captures_and_clears(client) -> None:
    _, op_tok, _ = register(client, "OPERATOR")
    _, admin_tok, _ = register(client, "ADMIN")

    # Plant a mix of legacy + tactical-graphic objects
    a = _make_object(
        client, op_tok, "ENEMY", symbol_code="SHGPU-------", notes="hostile"
    )
    b = _make_object(client, op_tok, "POI", notes="cache")
    c = _make_object(
        client, op_tok, "ATK_AXIS", rotation=120.0, echelon="PL", notes="attack"
    )

    assert {a, b, c}.issubset(
        {
            o["id"]
            for o in client.get("/tactical-objects", headers=auth(admin_tok)).json()
        }
    )

    r = client.post(
        "/admin/map/reset", headers=auth(admin_tok), json={"name": "before refit"}
    )
    assert r.status_code == 201, r.text
    snap = r.json()
    # 3 tactical objects + 1 OPERATOR (now also captured & wiped)
    assert snap["counts"]["tactical_objects"] == 3
    assert snap["counts"]["operators"] == 1
    assert snap["object_count"] == 4
    assert snap["name"] == "before refit"
    assert snap["id"] >= 1

    # Map is now empty
    listed = client.get("/tactical-objects", headers=auth(admin_tok)).json()
    assert listed == []


def test_reset_default_name_when_blank(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")
    _make_object(client, admin_tok, "POI")
    r = client.post("/admin/map/reset", headers=auth(admin_tok), json={})
    assert r.status_code == 201
    assert r.json()["name"].startswith("Map reset ")


def test_reset_with_no_objects_still_creates_snapshot(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")
    r = client.post("/admin/map/reset", headers=auth(admin_tok), json={"name": "empty"})
    assert r.status_code == 201
    assert r.json()["object_count"] == 0


def test_snapshot_list_and_detail(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")
    _make_object(
        client, admin_tok, "ATK_AXIS", rotation=45.0, echelon="COY", notes="lead axis"
    )
    _make_object(
        client,
        admin_tok,
        "FLET",
        geometry='{"type":"line","coords":[[50.85,4.35],[50.86,4.37]]}',
    )

    r = client.post(
        "/admin/map/reset", headers=auth(admin_tok), json={"name": "phase-1"}
    )
    snap_id = r.json()["id"]

    listed = client.get("/admin/map/snapshots", headers=auth(admin_tok)).json()
    assert any(s["id"] == snap_id and s["name"] == "phase-1" for s in listed)

    detail = client.get(
        f"/admin/map/snapshots/{snap_id}", headers=auth(admin_tok)
    ).json()
    assert detail["object_count"] == 2
    assert detail["counts"]["tactical_objects"] == 2
    types = {o["type"] for o in detail["state"]["tactical_objects"]}
    assert types == {"ATK_AXIS", "FLET"}
    # Snapshot preserves the new tactical-graphic fields
    atk = next(
        o for o in detail["state"]["tactical_objects"] if o["type"] == "ATK_AXIS"
    )
    assert atk["rotation"] == 45.0
    assert atk["echelon"] == "COY"
    flet = next(o for o in detail["state"]["tactical_objects"] if o["type"] == "FLET")
    assert "coords" in flet["geometry"]


def test_reset_captures_messages_reports_alerts_fire_missions(client) -> None:
    """The snapshot net should pull every operational record, not just tac-objects."""
    _, op_cs, op_tok, op_id = (
        (*register(client, "OPERATOR"),)[0:4]
        if False
        else (None, *register(client, "OPERATOR"))
    )
    _, admin_tok, _ = register(client, "ADMIN")

    _make_object(client, op_tok, "ENEMY", symbol_code="SHGPUCI-----", notes="contact")

    # Message — broadcast (no receiver_id required)
    assert (
        client.post(
            "/messages",
            headers=auth(op_tok),
            json={
                "content": "CONTACT — moving NE",
                "message_type": "BROADCAST",
            },
        ).status_code
        == 201
    )

    # Report
    assert (
        client.post(
            "/reports",
            headers=auth(op_tok),
            json={
                "type": "SPOT",
                "payload": {"grid": "31UFS123456", "direction": "N", "distance": 600},
            },
        ).status_code
        == 201
    )

    # Alert
    assert (
        client.post(
            "/alerts",
            headers=auth(op_tok),
            json={
                "type": "TIC",
                "latitude": 50.85,
                "longitude": 4.35,
            },
        ).status_code
        == 201
    )

    # Fire mission
    fm = client.post(
        "/fire-missions",
        headers=auth(op_tok),
        json={
            "latitude": 50.85,
            "longitude": 4.35,
            "altitude": 0.0,
            "direction": 90.0,
            "mission_type": "ADJUST_FIRE",
            "ammunition": "HE",
            "quantity": 4,
            "description": "Massed dismounts in tree-line",
        },
    )
    assert fm.status_code == 201, fm.text

    r = client.post("/admin/map/reset", headers=auth(admin_tok), json={})
    assert r.status_code == 201
    out = r.json()
    assert out["counts"]["tactical_objects"] == 1
    assert out["counts"]["messages"] == 1
    assert out["counts"]["reports"] == 1
    assert out["counts"]["alerts"] == 1
    assert out["counts"]["fire_missions"] == 1
    # The OPERATOR that posted the records is also wiped now.
    assert out["counts"]["operators"] == 1
    assert out["object_count"] == 6

    # Live state empty across the board
    h = auth(admin_tok)
    assert client.get("/tactical-objects", headers=h).json() == []
    assert client.get("/messages", headers=h).json() == []
    assert client.get("/reports", headers=h).json() == []
    assert client.get("/alerts", headers=h).json() == []
    assert client.get("/fire-missions", headers=h).json() == []


def test_restore_recreates_messages_reports_alerts_fire_missions(client) -> None:
    _, op_tok, _ = register(client, "OPERATOR")
    _, admin_tok, _ = register(client, "ADMIN")

    client.post(
        "/messages",
        headers=auth(op_tok),
        json={"content": "BROADCAST 1", "message_type": "BROADCAST"},
    )
    client.post(
        "/reports",
        headers=auth(op_tok),
        json={"type": "SPOT", "payload": {"grid": "31UFS123456"}},
    )
    client.post(
        "/alerts",
        headers=auth(op_tok),
        json={"type": "MEDICAL", "latitude": 50.85, "longitude": 4.35},
    )
    client.post(
        "/fire-missions",
        headers=auth(op_tok),
        json={
            "latitude": 50.85,
            "longitude": 4.35,
            "altitude": 0,
            "direction": 180,
            "mission_type": "FIRE_FOR_EFFECT",
            "ammunition": "HE",
            "quantity": 3,
            "description": "tgt",
        },
    )

    snap_id = client.post(
        "/admin/map/reset", headers=auth(admin_tok), json={"name": "before refit"}
    ).json()["id"]

    h = auth(admin_tok)
    r = client.post(f"/admin/map/snapshots/{snap_id}/restore", headers=h)
    assert r.status_code == 201, r.text
    counts = r.json()["counts"]
    assert counts["messages"] == 1
    assert counts["reports"] == 1
    assert counts["alerts"] == 1
    assert counts["fire_missions"] == 1

    # Verify the records actually came back
    assert any(
        m["content"] == "BROADCAST 1" for m in client.get("/messages", headers=h).json()
    )
    assert len(client.get("/reports", headers=h).json()) == 1
    assert any(a["type"] == "MEDICAL" for a in client.get("/alerts", headers=h).json())
    fms = client.get("/fire-missions", headers=h).json()
    assert any(f["mission_type"] == "FIRE_FOR_EFFECT" for f in fms)


def test_delete_mission_purges_dependent_rows(client) -> None:
    """Regression: `DELETE /missions/{id}` must not 500 on the
    `alerts_mission_id_fkey` (or any sibling) FK violation. Mission-scoped
    rows are cascade-deleted; preserved tables get mission_id NULLed."""
    _, op_tok, op_id = register(client, "OPERATOR")
    _, admin_tok, _ = register(client, "ADMIN")

    m = client.post("/missions", headers=auth(admin_tok), json={"name": "DOOMED"})
    assert m.status_code == 201, m.text
    mid = m.json()["id"]

    # Non-admins are locked to their assigned mission (the X-Mission-ID header is
    # ignored for them), so assign the operator to DOOMED before they create in it.
    assert (
        client.post(
            f"/missions/{mid}/operators",
            headers=auth(admin_tok),
            json={"operator_ids": [op_id]},
        ).status_code
        == 204
    )

    # Create one of each FK-referencing record so the delete used to 500.
    # Alerts are the canonical 500-trigger (alerts_mission_id_fkey).
    h_op = auth(op_tok)
    h_op["X-Mission-ID"] = str(mid)
    a = client.post(
        "/alerts",
        headers=h_op,
        json={"type": "TIC", "latitude": 50.0, "longitude": 4.0},
    )
    assert a.status_code == 201, a.text
    r = client.post(
        "/reports",
        headers=h_op,
        json={"type": "SPOT", "payload": {"size": "SQUAD"}},
    )
    assert r.status_code == 201, r.text
    f = client.post(
        "/fire-missions",
        headers=h_op,
        json={
            "latitude": 50.0,
            "longitude": 4.0,
            "direction": 90.0,
            "mission_type": "ADJUST_FIRE",
            "ammunition": "HE",
        },
    )
    assert f.status_code == 201, f.text

    # The delete used to 500 with ForeignKeyViolation before the purge helper.
    d = client.delete(f"/missions/{mid}", headers=auth(admin_tok))
    assert d.status_code == 204, d.text

    # Mission gone, mission-scoped rows gone.
    assert client.get(f"/missions/{mid}", headers=auth(admin_tok)).status_code == 404
    alerts = client.get("/alerts", headers=auth(admin_tok)).json()
    assert all(x.get("id") != a.json()["id"] for x in alerts)
    reports = client.get("/reports", headers=auth(admin_tok)).json()
    assert all(x.get("id") != r.json()["id"] for x in reports)
    fms = client.get("/fire-missions", headers=auth(admin_tok)).json()
    assert all(x.get("id") != f.json()["id"] for x in fms)


def test_reset_deletes_all_missions(client) -> None:
    """`/admin/map/reset` ends + deletes every mission so they don't accumulate
    across scenario runs. Both PLANNING and ACTIVE missions go away."""
    _, admin_tok, _ = register(client, "ADMIN")
    # Create a mission and start it (so it's ACTIVE).
    m1 = client.post(
        "/missions",
        headers=auth(admin_tok),
        json={"name": "ACTIVE-OP", "description": "in progress"},
    )
    assert m1.status_code == 201, m1.text
    m1_id = m1.json()["id"]
    client.post(f"/missions/{m1_id}/start", headers=auth(admin_tok))

    # Plus a PLANNING one (no start).
    m2 = client.post(
        "/missions",
        headers=auth(admin_tok),
        json={"name": "PLANNED-OP"},
    )
    assert m2.status_code == 201, m2.text

    # Sanity: both missions visible.
    missions_before = client.get("/missions", headers=auth(admin_tok)).json()
    assert {m["name"] for m in missions_before} >= {"ACTIVE-OP", "PLANNED-OP"}

    r = client.post("/admin/map/reset", headers=auth(admin_tok), json={})
    assert r.status_code == 201, r.text

    missions_after = client.get("/missions", headers=auth(admin_tok)).json()
    assert missions_after == [], f"missions survived reset: {missions_after}"


def test_reset_handles_photos_uploaded_by_non_admin(client) -> None:
    """Regression: bulk-deleting non-ADMIN operators must not violate
    `photos.uploaded_by_fkey` / `cop_documents.uploaded_by_fkey`. Both tables
    are preserved by design; their `uploaded_by` is re-pointed to the calling
    admin instead.
    """
    import backend.storage.database as _db
    from backend.storage.models import CopDocument, Operator, Photo

    _, op_tok, op_id = register(client, "OPERATOR")
    _, admin_tok, admin_id = register(client, "ADMIN")

    # Drop a photo + cop_document that point at the non-ADMIN op.
    with _db.SessionLocal() as s:
        s.add(
            Photo(
                filename="x.jpg",
                original_name="x.jpg",
                mime_type="image/jpeg",
                uploaded_by=op_id,
            )
        )
        s.add(
            CopDocument(
                title="t",
                filename="t.txt",
                content_type="TXT",
                file_data=b"",
                uploaded_by=op_id,
            )
        )
        s.commit()

    # The reset would 500 before the fix (FK violation on photos).
    r = client.post("/admin/map/reset", headers=auth(admin_tok), json={})
    assert r.status_code == 201, r.text

    with _db.SessionLocal() as s:
        assert s.query(Operator).filter(Operator.id == op_id).first() is None
        photos = s.query(Photo).all()
        docs = s.query(CopDocument).all()
        assert len(photos) == 1
        assert len(docs) == 1
        # Re-pointed to the calling admin.
        assert photos[0].uploaded_by == admin_id
        assert docs[0].uploaded_by == admin_id


def test_reset_preserves_admins_only(client) -> None:
    """Reset wipes every non-ADMIN operator; ADMINs and audit logs survive."""
    cs_op, op_tok, _ = register(client, "OPERATOR")
    cs_bc, bc_tok, _ = register(client, "BATTLE_CAPTAIN")
    _, admin_tok, _ = register(client, "ADMIN")

    _make_object(client, op_tok, "POI")
    audit_before = len(client.get("/admin/audit", headers=auth(admin_tok)).json())

    before = client.get("/operators", headers=auth(admin_tok)).json()
    admins_before = [o for o in before if o["role"] == "ADMIN"]
    non_adm_before = [o for o in before if o["role"] != "ADMIN"]
    assert cs_op in {o["callsign"] for o in non_adm_before}
    assert cs_bc in {o["callsign"] for o in non_adm_before}

    out = client.post("/admin/map/reset", headers=auth(admin_tok), json={}).json()
    assert out["counts"]["operators"] == len(non_adm_before)

    after = client.get("/operators", headers=auth(admin_tok)).json()
    admins = [o for o in after if o["role"] == "ADMIN"]
    others = [o for o in after if o["role"] != "ADMIN"]
    # Every pre-existing ADMIN survives; every non-ADMIN is gone.
    assert {a["callsign"] for a in admins} == {a["callsign"] for a in admins_before}
    assert others == []
    # Audit log persisted (pre-existing entries are not snapshotted/cleared).
    assert (
        len(client.get("/admin/audit", headers=auth(admin_tok)).json()) >= audit_before
    )


def test_restore_recreates_objects_with_new_ids(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")
    _make_object(client, admin_tok, "POI", notes="orig")
    _make_object(client, admin_tok, "DEF_AREA", rotation=270.0, echelon="PL")

    snap_id = client.post("/admin/map/reset", headers=auth(admin_tok), json={}).json()[
        "id"
    ]
    assert client.get("/tactical-objects", headers=auth(admin_tok)).json() == []

    r = client.post(f"/admin/map/snapshots/{snap_id}/restore", headers=auth(admin_tok))
    assert r.status_code == 201, r.text
    assert r.json()["restored"] == 2

    restored = client.get("/tactical-objects", headers=auth(admin_tok)).json()
    types = sorted(o["type"] for o in restored)
    assert types == ["DEF_AREA", "POI"]
    # New IDs (the originals were deleted in the reset)
    assert all(isinstance(o["id"], int) and o["id"] >= 1 for o in restored)
    da = next(o for o in restored if o["type"] == "DEF_AREA")
    assert da["rotation"] == 270.0
    assert da["echelon"] == "PL"


def test_restore_is_additive_does_not_clear_live_map(client) -> None:
    """Restore re-creates objects on top of what's there — admin can re-reset
    first if they want a clean restore."""
    _, admin_tok, _ = register(client, "ADMIN")
    _make_object(client, admin_tok, "POI", notes="orig")
    snap_id = client.post("/admin/map/reset", headers=auth(admin_tok), json={}).json()[
        "id"
    ]

    # Plant something fresh
    fresh = _make_object(client, admin_tok, "ENEMY", symbol_code="SHGPUCI-----")

    client.post(f"/admin/map/snapshots/{snap_id}/restore", headers=auth(admin_tok))
    listed = client.get("/tactical-objects", headers=auth(admin_tok)).json()
    types = [o["type"] for o in listed]
    assert "POI" in types  # restored
    assert "ENEMY" in types  # fresh, untouched
    assert any(o["id"] == fresh for o in listed)


def test_snapshot_delete_404_when_gone(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")
    _make_object(client, admin_tok, "POI")
    snap_id = client.post("/admin/map/reset", headers=auth(admin_tok), json={}).json()[
        "id"
    ]

    assert (
        client.delete(
            f"/admin/map/snapshots/{snap_id}", headers=auth(admin_tok)
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/admin/map/snapshots/{snap_id}", headers=auth(admin_tok)
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/admin/map/snapshots/{snap_id}", headers=auth(admin_tok)
        ).status_code
        == 404
    )


def test_map_clear_deletes_graphics_but_keeps_accounts(client) -> None:
    cs, op_tok, op_id = register(client, "OPERATOR")
    _, admin_tok, _ = register(client, "ADMIN")

    _make_object(client, op_tok, "ENEMY", notes="hostile")
    _make_object(client, op_tok, "POI", notes="cache")
    # Give the operator a live position.
    assert (
        client.post(
            "/tracking/position",
            headers=auth(op_tok),
            json={"latitude": 50.1, "longitude": 4.2},
        ).status_code
        == 200
    )
    assert client.get("/tracking/live", headers=auth(admin_tok)).json()  # not empty

    r = client.post("/admin/map/clear", headers=auth(admin_tok), json={})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["counts"]["tactical_objects"] == 2
    assert out["id"] >= 1  # a snapshot was saved

    # Map graphics gone, operator dropped off the live map…
    assert client.get("/tactical-objects", headers=auth(admin_tok)).json() == []
    assert client.get("/tracking/live", headers=auth(admin_tok)).json() == []
    # …but the account itself survives and can still authenticate.
    me = client.get("/auth/me", headers=auth(op_tok))
    assert me.status_code == 200 and me.json()["id"] == op_id


def test_reset_defaults_restores_settings(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")

    # Turn a visibility flag off and set a non-default session timeout.
    client.put(
        "/admin/map-visibility",
        headers=auth(admin_tok),
        json={"tactical_objects": False},
    )
    client.put(
        "/admin/session-config",
        headers=auth(admin_tok),
        json={"inactivity_timeout_minutes": 30},
    )

    r = client.post("/admin/reset-defaults", headers=auth(admin_tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["map_visibility"]["tactical_objects"] is True
    assert body["session"]["inactivity_timeout_minutes"] == 0

    # Persisted, not just echoed.
    assert (
        client.get("/admin/map-visibility", headers=auth(admin_tok)).json()[
            "tactical_objects"
        ]
        is True
    )
    assert (
        client.get("/admin/session-config", headers=auth(admin_tok)).json()[
            "inactivity_timeout_minutes"
        ]
        == 0
    )


def test_endpoints_are_admin_only(client) -> None:
    _, op_tok, _ = register(client, "OPERATOR")
    _, bc_tok, _ = register(client, "BATTLE_CAPTAIN")

    for path, method in [
        ("/admin/map/reset", "POST"),
        ("/admin/map/clear", "POST"),
        ("/admin/reset-defaults", "POST"),
        ("/admin/map/snapshots", "GET"),
        ("/admin/map/snapshots/1", "GET"),
        ("/admin/map/snapshots/1", "DELETE"),
        ("/admin/map/snapshots/1/restore", "POST"),
    ]:
        for tok in (op_tok, bc_tok):
            r = client.request(method, path, headers=auth(tok), json={})
            assert (
                r.status_code == 403
            ), f"{method} {path} as non-admin should be 403, got {r.status_code}"
