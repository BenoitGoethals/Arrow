"""Admin map-visibility config — singleton row, role-gated PUT, WS-broadcast."""

from __future__ import annotations

from tests.conftest import auth, register


def test_default_all_categories_visible(client) -> None:
    _, op_tok, _ = register(client, "OPERATOR")
    r = client.get("/admin/map-visibility", headers=auth(op_tok))
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        # Map axis
        "tactical_objects", "operators", "fire_missions", "alerts",
        "reports", "cot_tracks", "kml_layers", "overlays",
        # Notification axis
        "notif_chat", "notif_fire_missions", "notif_alerts", "notif_streams",
    ):
        assert body[key] is True, f"{key} should default to True"


def test_map_and_notif_are_independent(client) -> None:
    """Muting notif_alerts must NOT hide alert markers on the map, and
    vice versa — the two axes are decoupled."""
    _, admin_tok, _ = register(client, "ADMIN")
    # Mute the alert toast but leave alerts on the map.
    r = client.put("/admin/map-visibility", headers=auth(admin_tok),
                   json={"notif_alerts": False})
    body = r.json()
    assert body["notif_alerts"] is False
    assert body["alerts"]       is True
    # Inverse: hide alerts on the map but keep toasts.
    r = client.put("/admin/map-visibility", headers=auth(admin_tok),
                   json={"alerts": False, "notif_alerts": True})
    body = r.json()
    assert body["alerts"]       is False
    assert body["notif_alerts"] is True


def test_chat_toast_toggle_persists(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")
    r = client.put("/admin/map-visibility", headers=auth(admin_tok),
                   json={"notif_chat": False})
    assert r.json()["notif_chat"] is False
    fresh = client.get("/admin/map-visibility", headers=auth(admin_tok)).json()
    assert fresh["notif_chat"] is False


def test_admin_can_toggle(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")
    r = client.put("/admin/map-visibility", headers=auth(admin_tok), json={
        "fire_missions": False, "alerts": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fire_missions"] is False
    assert body["alerts"]        is False
    # Untouched fields remain on.
    assert body["tactical_objects"] is True
    assert body["operators"]        is True
    # Round-trip via GET.
    fresh = client.get("/admin/map-visibility", headers=auth(admin_tok)).json()
    assert fresh["fire_missions"] is False
    assert fresh["alerts"]        is False


def test_partial_patch_keeps_other_fields(client) -> None:
    _, admin_tok, _ = register(client, "ADMIN")
    client.put("/admin/map-visibility", headers=auth(admin_tok),
               json={"tactical_objects": False, "operators": False})
    # Now flip just alerts; tactical/operators must stay False.
    r = client.put("/admin/map-visibility", headers=auth(admin_tok),
                   json={"alerts": False})
    body = r.json()
    assert body["tactical_objects"] is False
    assert body["operators"]        is False
    assert body["alerts"]           is False
    assert body["reports"]          is True


def test_any_operator_can_toggle_defaults(client) -> None:
    """Per-operator prefs live client-side now; the server-side singleton is
    just the default a fresh device pulls in. Every authenticated operator
    can adjust those defaults."""
    _, op_tok, _ = register(client, "OPERATOR")
    _, bc_tok, _ = register(client, "BATTLE_CAPTAIN")
    for tok in (op_tok, bc_tok):
        r = client.put("/admin/map-visibility", headers=auth(tok),
                       json={"alerts": False})
        assert r.status_code == 200, r.text
        assert r.json()["alerts"] is False
        # Reset for the next iteration.
        client.put("/admin/map-visibility", headers=auth(tok),
                   json={"alerts": True})


def test_unknown_field_ignored(client) -> None:
    """Pydantic strict-ish — extra fields are dropped rather than 422."""
    _, admin_tok, _ = register(client, "ADMIN")
    r = client.put("/admin/map-visibility", headers=auth(admin_tok),
                   json={"bogus_category": False, "alerts": False})
    assert r.status_code == 200
    assert "bogus_category" not in r.json()


def test_persists_across_reset(client) -> None:
    """``/admin/map/reset`` does NOT touch the visibility config — it's a
    user preference, not operational state."""
    _, admin_tok, _ = register(client, "ADMIN")
    client.put("/admin/map-visibility", headers=auth(admin_tok),
               json={"cot_tracks": False})
    client.post("/admin/map/reset", headers=auth(admin_tok), json={})
    body = client.get("/admin/map-visibility", headers=auth(admin_tok)).json()
    assert body["cot_tracks"] is False
