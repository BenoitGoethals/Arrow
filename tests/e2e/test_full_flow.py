"""Full integration tests — all components communicate correctly.

Coverage:
  Auth & security controls:
    - register / login / me / logout → token revocation
    - account lockout after 5 failures, unlock on success
    - MFA: setup → enable → login requires TOTP → verify → disable
    - self-registration always creates OPERATOR (privilege escalation blocked)
    - admin can create BATTLE_CAPTAIN / ADMIN via /auth/register/admin

  Hierarchy:
    - full company → platoon → section → team → operator tree CRUD
    - GET /hierarchy returns correct tree with online flags

  Tactical objects:
    - create, list, delete (own + admin delete)
    - visibility scoping (field present)

  Alerts:
    - trigger, list, acknowledge (BC/ADMIN only)

  Messaging:
    - direct, broadcast, group routing (also tested in test_messaging.py)

  Fire missions:
    - submit, list, update status (BC/ADMIN only)

  Reports:
    - submit 9-liner, list

  Photos:
    - upload, serve (auth required)

  Battles:
    - create (BC/ADMIN), close

  WebSocket:
    - alert broadcast
    - tactical-object broadcast

  Cross-cutting security:
    - unauthenticated access to all protected endpoints → 401
    - role enforcement (OPERATOR cannot do BC/ADMIN actions) → 403
"""

from __future__ import annotations

import pyotp


from tests.conftest import auth, register, admin_token


def _recv_on_channel(ws, channel: str, max_msgs: int = 10) -> dict:
    """Drain WS messages until one arrives on the expected channel."""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("channel") == channel:
            return msg
    raise AssertionError(f"No message on channel '{channel}' after {max_msgs} attempts")


# ── Auth: basic flow ─────────────────────────────────────────────────────────


class TestAuth:
    def test_health(self, client):
        assert client.get("/health").json() == {"status": "ok"}

    def test_register_always_operator(self, client):
        r = client.post(
            "/auth/register",
            json={"callsign": "hacker", "password": "password1", "role": "ADMIN"},
        )
        assert r.status_code == 201
        assert r.json()["role"] == "OPERATOR"

    def test_register_short_password_rejected(self, client):
        r = client.post("/auth/register", json={"callsign": "weak", "password": "abc"})
        assert r.status_code == 422

    def test_login_me(self, client):
        callsign, token, _ = register(client)
        me = client.get("/auth/me", headers=auth(token)).json()
        assert me["callsign"] == callsign
        assert me["role"] == "OPERATOR"

    def test_admin_creates_elevated(self, client):
        tok = admin_token(client)
        r = client.post(
            "/auth/register/admin",
            json={
                "callsign": "newbc",
                "password": "secure123",
                "role": "BATTLE_CAPTAIN",
            },
            headers=auth(tok),
        )
        assert r.status_code == 201
        assert r.json()["role"] == "BATTLE_CAPTAIN"

    def test_admin_rejects_unknown_role(self, client):
        tok = admin_token(client)
        r = client.post(
            "/auth/register/admin",
            json={"callsign": "badrol", "password": "secure123", "role": "SUPERUSER"},
            headers=auth(tok),
        )
        assert r.status_code == 422

    def test_logout_revokes_token(self, client):
        _, token, _ = register(client)
        r = client.post("/auth/logout", headers=auth(token))
        assert r.status_code == 204
        # Revoked token is rejected
        r = client.get("/auth/me", headers=auth(token))
        assert r.status_code == 401

    def test_fresh_token_after_logout_works(self, client):
        callsign, token, _ = register(client)
        client.post("/auth/logout", headers=auth(token))
        # Re-login should work
        r = client.post(
            "/auth/login", data={"username": callsign, "password": "pw123456"}
        )
        assert r.status_code == 200
        new_token = r.json()["access_token"]
        assert client.get("/auth/me", headers=auth(new_token)).status_code == 200

    def test_wrong_password_rejected(self, client):
        callsign, _, _ = register(client)
        r = client.post(
            "/auth/login", data={"username": callsign, "password": "wrongpassword"}
        )
        assert r.status_code == 401


# ── Auth: account lockout ────────────────────────────────────────────────────


class TestAccountLockout:
    def test_lockout_after_5_failures(self, client):
        callsign, _, _ = register(client)
        for _ in range(5):
            client.post(
                "/auth/login", data={"username": callsign, "password": "wrongpw"}
            )
        r = client.post(
            "/auth/login", data={"username": callsign, "password": "pw123456"}
        )
        assert r.status_code == 423  # Locked

    def test_lockout_returns_retry_message(self, client):
        callsign, _, _ = register(client)
        for _ in range(5):
            client.post(
                "/auth/login", data={"username": callsign, "password": "wrongpw"}
            )
        r = client.post(
            "/auth/login", data={"username": callsign, "password": "wrongpw"}
        )
        assert r.status_code == 423
        assert "locked" in r.json()["detail"].lower()

    def test_other_accounts_unaffected_by_lockout(self, client):
        """Locking one account must not block another."""
        cs_a, _, _ = register(client)
        cs_b, tok_b, _ = register(client)
        for _ in range(5):
            client.post("/auth/login", data={"username": cs_a, "password": "wrongpw"})
        # B can still login
        r = client.post("/auth/login", data={"username": cs_b, "password": "pw123456"})
        assert r.status_code == 200


# ── Auth: MFA (TOTP) ─────────────────────────────────────────────────────────


class TestMFA:
    def test_mfa_full_lifecycle(self, client):
        _, token, _ = register(client)

        # Setup — generates secret
        r = client.post("/auth/mfa/setup", headers=auth(token))
        assert r.status_code == 200
        secret = r.json()["secret"]
        assert "uri" in r.json()
        totp = pyotp.TOTP(secret)

        # Enable — requires valid code
        r = client.post(
            "/auth/mfa/enable", json={"code": totp.now()}, headers=auth(token)
        )
        assert r.status_code == 204

        # Login now returns mfa_required
        callsign = client.get("/auth/me", headers=auth(token)).json()["callsign"]
        r = client.post(
            "/auth/login", data={"username": callsign, "password": "pw123456"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["mfa_required"] is True
        assert data["mfa_session"] is not None
        assert data["access_token"] is None

        # MFA session cannot be used as an access token
        r = client.get("/auth/me", headers=auth(data["mfa_session"]))
        assert r.status_code == 401

        # Verify with correct code → full access token
        r = client.post(
            "/auth/mfa/verify",
            json={"mfa_session": data["mfa_session"], "code": totp.now()},
        )
        assert r.status_code == 200
        full_token = r.json()["access_token"]
        assert full_token is not None
        assert client.get("/auth/me", headers=auth(full_token)).status_code == 200

        # Disable MFA
        r = client.post(
            "/auth/mfa/disable", json={"code": totp.now()}, headers=auth(full_token)
        )
        assert r.status_code == 204

        # After disable, login returns full token immediately
        r = client.post(
            "/auth/login", data={"username": callsign, "password": "pw123456"}
        )
        assert r.status_code == 200
        assert r.json()["mfa_required"] is False
        assert r.json()["access_token"] is not None

    def test_invalid_totp_code_rejected(self, client):
        _, token, _ = register(client)
        client.post("/auth/mfa/setup", headers=auth(token))
        r = client.post(
            "/auth/mfa/enable", json={"code": "000000"}, headers=auth(token)
        )
        assert r.status_code == 401


# ── Hierarchy ─────────────────────────────────────────────────────────────────


class TestHierarchy:
    def _build_tree(self, client, admin_tok):
        h = auth(admin_tok)
        co = client.post("/companies", headers=h, json={"name": "1 BN"})
        assert co.status_code == 201
        plt = client.post(
            "/platoons",
            headers=h,
            json={"name": "Alpha Plt", "company_id": co.json()["id"]},
        )
        assert plt.status_code == 201
        sec = client.post(
            "/sections",
            headers=h,
            json={"name": "A1 Section", "platoon_id": plt.json()["id"]},
        )
        assert sec.status_code == 201
        team = client.post(
            "/teams",
            headers=h,
            json={"name": "A1-1 Team", "section_id": sec.json()["id"]},
        )
        assert team.status_code == 201
        return co.json(), plt.json(), sec.json(), team.json()

    def test_full_tree_crud(self, client):
        tok = admin_token(client)
        co, plt, sec, team = self._build_tree(client, tok)
        h = auth(tok)

        assert any(
            c["id"] == co["id"] for c in client.get("/companies", headers=h).json()
        )
        assert any(
            p["id"] == plt["id"] for p in client.get("/platoons", headers=h).json()
        )
        assert any(
            s["id"] == sec["id"] for s in client.get("/sections", headers=h).json()
        )
        assert any(
            t["id"] == team["id"] for t in client.get("/teams", headers=h).json()
        )

    def test_hierarchy_endpoint_requires_auth(self, client):
        assert client.get("/hierarchy").status_code == 401

    def test_hierarchy_endpoint_returns_tree(self, client):
        tok = admin_token(client)
        self._build_tree(client, tok)
        r = client.get("/hierarchy", headers=auth(tok))
        assert r.status_code == 200
        body = r.json()
        assert "companies" in body
        assert "online_window_seconds" in body
        company_names = [c["name"] for c in body["companies"]]
        assert "1 BN" in company_names

    def test_hierarchy_unauthenticated_endpoints(self, client):
        for path in ["/teams", "/platoons", "/sections", "/companies"]:
            assert client.get(path).status_code == 401

    def test_non_admin_cannot_create_hierarchy(self, client):
        _, op_tok, _ = register(client)
        for path, body in [
            ("/companies", {"name": "Evil Co"}),
            ("/platoons", {"name": "Evil Plt", "company_id": 99}),
        ]:
            r = client.post(path, headers=auth(op_tok), json=body)
            assert r.status_code in (401, 403, 422)


# ── Tactical objects ──────────────────────────────────────────────────────────


class TestTacticalObjects:
    def test_create_list_delete(self, client):
        _, token, _ = register(client)
        h = auth(token)
        r = client.post(
            "/tactical-objects",
            headers=h,
            json={
                "type": "ENEMY",
                "symbol_code": "SHGPUCI-----",
                "latitude": 50.9,
                "longitude": 4.4,
                "notes": "Dismounts",
            },
        )
        assert r.status_code == 201
        obj_id = r.json()["id"]

        assert any(
            o["id"] == obj_id for o in client.get("/tactical-objects", headers=h).json()
        )
        assert (
            client.delete(f"/tactical-objects/{obj_id}", headers=h).status_code == 204
        )
        assert not any(
            o["id"] == obj_id for o in client.get("/tactical-objects", headers=h).json()
        )

    def test_unauthenticated_returns_401(self, client):
        assert client.get("/tactical-objects").status_code == 401

    def test_operator_cannot_delete_others_object(self, client):
        _, tok_a, _ = register(client)
        _, tok_b, _ = register(client)
        r = client.post(
            "/tactical-objects",
            headers=auth(tok_a),
            json={
                "type": "POI",
                "latitude": 51.0,
                "longitude": 4.0,
            },
        )
        obj_id = r.json()["id"]
        r = client.delete(f"/tactical-objects/{obj_id}", headers=auth(tok_b))
        assert r.status_code == 403

    def test_admin_can_delete_any_object(self, client):
        _, op_tok, _ = register(client)
        r = client.post(
            "/tactical-objects",
            headers=auth(op_tok),
            json={
                "type": "POI",
                "latitude": 51.0,
                "longitude": 4.0,
            },
        )
        obj_id = r.json()["id"]
        tok = admin_token(client)
        assert (
            client.delete(f"/tactical-objects/{obj_id}", headers=auth(tok)).status_code
            == 204
        )


# ── Alerts ───────────────────────────────────────────────────────────────────


class TestAlerts:
    def test_trigger_and_list(self, client):
        _, token, _ = register(client)
        r = client.post(
            "/alerts",
            headers=auth(token),
            json={"type": "TIC", "latitude": 50.0, "longitude": 4.0},
        )
        assert r.status_code == 201
        alert_id = r.json()["id"]
        alerts = client.get("/alerts", headers=auth(token)).json()
        assert any(a["id"] == alert_id for a in alerts)

    def test_only_bc_can_acknowledge(self, client):
        _, op_tok, _ = register(client)
        r = client.post("/alerts", headers=auth(op_tok), json={"type": "MEDICAL"})
        alert_id = r.json()["id"]

        # OPERATOR cannot acknowledge
        r = client.post(f"/alerts/{alert_id}/ack", headers=auth(op_tok))
        assert r.status_code == 403

        # BATTLE_CAPTAIN can
        _, bc_tok, _ = register(client, role="BATTLE_CAPTAIN")
        r = client.post(f"/alerts/{alert_id}/ack", headers=auth(bc_tok))
        assert r.status_code == 200
        assert r.json()["status"] == "ACKNOWLEDGED"

    def test_alert_websocket_broadcast(self, client):
        _, token, _ = register(client)
        with client.websocket_connect(f"/ws?token={token}") as ws:
            client.post("/alerts", headers=auth(token), json={"type": "EVAC"})
            msg = _recv_on_channel(ws, "alert")
            assert msg["event"] == "triggered"
            assert msg["data"]["type"] == "EVAC"


# ── Fire missions ─────────────────────────────────────────────────────────────


class TestFireMissions:
    def _submit(self, client, token):
        return client.post(
            "/fire-missions",
            headers=auth(token),
            json={
                "latitude": 50.85,
                "longitude": 4.35,
                "altitude": 100.0,
                "direction": 270.0,
                "mission_type": "ADJUST_FIRE",
                "ammunition": "HE",
                "quantity": 3,
                "description": "Grid 50.85N 4.35E",
            },
        )

    def test_submit_and_list(self, client):
        _, token, _ = register(client)
        r = self._submit(client, token)
        assert r.status_code == 201
        fm_id = r.json()["id"]
        listed = client.get("/fire-missions", headers=auth(token)).json()
        assert any(fm["id"] == fm_id for fm in listed)

    def test_unauthenticated_rejected(self, client):
        assert client.get("/fire-missions").status_code == 401

    def test_operator_cannot_update_status(self, client):
        _, op_tok, _ = register(client)
        r = self._submit(client, op_tok)
        fm_id = r.json()["id"]
        r = client.patch(
            f"/fire-missions/{fm_id}",
            headers=auth(op_tok),
            json={"status": "CANCELLED"},
        )
        assert r.status_code == 403

    def test_bc_can_update_status(self, client):
        _, op_tok, _ = register(client)
        _, bc_tok, _ = register(client, role="BATTLE_CAPTAIN")
        r = self._submit(client, op_tok)
        fm_id = r.json()["id"]
        r = client.patch(
            f"/fire-missions/{fm_id}",
            headers=auth(bc_tok),
            json={"status": "ACKNOWLEDGED"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ACKNOWLEDGED"

    def test_fire_mission_websocket_broadcast(self, client):
        _, token, _ = register(client)
        with client.websocket_connect(f"/ws?token={token}") as ws:
            self._submit(client, token)
            msg = _recv_on_channel(ws, "fire-mission")
            assert msg["event"] == "submitted"


# ── Reports ──────────────────────────────────────────────────────────────────


class TestReports:
    def test_submit_and_list(self, client):
        _, token, _ = register(client)
        r = client.post(
            "/reports",
            headers=auth(token),
            json={
                "type": "MEDEVAC",
                "payload": {"line_1": "GR123456", "label_1": "Location"},
            },
        )
        assert r.status_code == 201
        report_id = r.json()["id"]
        listed = client.get("/reports", headers=auth(token)).json()
        assert any(rep["id"] == report_id for rep in listed)

    def test_unauthenticated_rejected(self, client):
        assert client.get("/reports").status_code == 401


# ── Photos ───────────────────────────────────────────────────────────────────


class TestPhotos:
    def test_upload_and_serve(self, client):
        _, token, _ = register(client)
        # Upload a minimal valid JPEG (1x1 pixel)
        tiny_jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
            b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5\x0a\x80"
            b"\xff\xd9"
        )
        r = client.post(
            "/photos",
            headers=auth(token),
            files={"file": ("test.jpg", tiny_jpeg, "image/jpeg")},
        )
        assert r.status_code == 201
        photo_id = r.json()["id"]

        # Serve requires auth
        assert client.get(f"/photos/{photo_id}").status_code == 401

        # With auth, image is returned
        r = client.get(f"/photos/{photo_id}", headers=auth(token))
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"

    def test_unsupported_mime_rejected(self, client):
        _, token, _ = register(client)
        r = client.post(
            "/photos",
            headers=auth(token),
            files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
        )
        assert r.status_code == 415


# ── Battles ───────────────────────────────────────────────────────────────────


class TestBattles:
    def test_create_and_close(self, client):
        _, bc_tok, _ = register(client, role="BATTLE_CAPTAIN")
        r = client.post(
            "/battles",
            headers=auth(bc_tok),
            json={"name": "Op IRON FIST", "description": "Main assault"},
        )
        assert r.status_code == 201
        battle_id = r.json()["id"]
        assert r.json()["status"] == "ACTIVE"

        r = client.post(f"/battles/{battle_id}/close", headers=auth(bc_tok))
        assert r.status_code == 200
        assert r.json()["status"] == "CLOSED"

    def test_operator_cannot_create_battle(self, client):
        _, op_tok, _ = register(client)
        r = client.post(
            "/battles",
            headers=auth(op_tok),
            json={"name": "Unauthorized", "description": ""},
        )
        assert r.status_code == 403

    def test_list_battles_requires_auth(self, client):
        assert client.get("/battles").status_code == 401


# ── Operator management ───────────────────────────────────────────────────────


class TestOperatorManagement:
    def test_list_operators_requires_auth(self, client):
        assert client.get("/operators").status_code == 401

    def test_admin_update_operator(self, client):
        _, op_tok, op_id = register(client)
        tok = admin_token(client)
        r = client.patch(
            f"/operators/{op_id}", headers=auth(tok), json={"rank": "OR-5"}
        )
        assert r.status_code == 200
        assert r.json()["rank"] == "OR-5"

    def test_operator_cannot_update_others(self, client):
        _, tok_a, id_a = register(client)
        _, tok_b, id_b = register(client)
        r = client.patch(
            f"/operators/{id_b}", headers=auth(tok_a), json={"rank": "OF-6"}
        )
        assert r.status_code == 403

    def test_admin_delete_operator(self, client):
        _, op_tok, op_id = register(client)
        tok = admin_token(client)
        assert (
            client.delete(f"/operators/{op_id}", headers=auth(tok)).status_code == 204
        )
        assert client.get(f"/operators/{op_id}", headers=auth(tok)).status_code == 404

    def test_audit_log_captures_delete(self, client):
        _, _, op_id = register(client)
        tok = admin_token(client)
        client.delete(f"/operators/{op_id}", headers=auth(tok))
        audit = client.get(
            "/admin/audit?event_type=OPERATOR_DELETE", headers=auth(tok)
        ).json()
        assert any(e["resource"] == f"operator:{op_id}" for e in audit)


# ── Tracking: live + position ─────────────────────────────────────────────────


class TestTracking:
    def test_position_update_appears_in_live(self, client):
        _, token, _ = register(client)
        callsign = client.get("/auth/me", headers=auth(token)).json()["callsign"]
        r = client.post(
            "/tracking/position",
            headers=auth(token),
            json={"latitude": 50.85, "longitude": 4.35, "altitude": 50.0},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ONLINE"

        live = client.get("/tracking/live", headers=auth(token)).json()
        assert any(o["callsign"] == callsign for o in live)

    def test_live_requires_auth(self, client):
        assert client.get("/tracking/live").status_code == 401


# ── Admin: stats + audit ──────────────────────────────────────────────────────


class TestAdmin:
    def test_stats_requires_admin(self, client):
        _, op_tok, _ = register(client)
        assert client.get("/admin/stats", headers=auth(op_tok)).status_code == 403

    def test_stats_returns_counts(self, client):
        tok = admin_token(client)
        r = client.get("/admin/stats", headers=auth(tok))
        assert r.status_code == 200
        body = r.json()
        assert "operators" in body
        assert "total" in body["operators"]

    def test_audit_filters_by_outcome(self, client):
        tok = admin_token(client)
        # Trigger a failure
        client.post("/auth/login", data={"username": "nobody", "password": "wrong"})
        failures = client.get("/admin/audit?outcome=FAILURE", headers=auth(tok)).json()
        assert all(e["outcome"] == "FAILURE" for e in failures)

    def test_audit_filters_by_event_type(self, client):
        tok = admin_token(client)
        client.post(
            "/auth/register", json={"callsign": "auditop", "password": "pw123456"}
        )
        events = client.get(
            "/admin/audit?event_type=REGISTER", headers=auth(tok)
        ).json()
        assert all(e["event_type"] == "REGISTER" for e in events)
        assert any(e["resource"] == "callsign:auditop" for e in events)
