"""ATAK device connect-and-sync integration tests.

Simulates an ATAK-Android device going through the full lifecycle:
  1. Authenticate with the backend (JWT)
  2. Send own-position CoT → position stored + ack CoT returned
  3. Position becomes visible to other operators via /tracking/live and /cot/{uid}
  4. Send a foreign hostile CoT → appears in /cot/tracks
  5. Real-time WebSocket sync: position propagates to WS subscribers
  6. Cross-device: two ATAK devices, each sees the other's position update on WS
  7. European locale CoT (comma decimal separators) is accepted
"""

from __future__ import annotations

import uuid
from lxml import etree

from backend.cot.cot import CotEvent, parse_cot
from tests.conftest import auth, register

# ── CoT XML builder that mimics an ATAK-Android device ───────────────────────


def _atak_cot(
    callsign: str,
    *,
    uid: str | None = None,
    cot_type: str = "a-f-G-U-C",
    lat: float = 50.85,
    lon: float = 4.35,
    hae: float = 120.0,
    speed: float = 1.5,
    course: float = 45.0,
    team: str = "Blue",
    role: str = "Team Member",
) -> bytes:
    ev = CotEvent(
        uid=uid or f"ARROW.{callsign}",
        cot_type=cot_type,
        lat=lat,
        lon=lon,
        hae=hae,
        callsign=callsign,
        speed=speed,
        course=course,
        team=team,
        role=role,
        platform="ATAK-Android",
    )
    return ev.to_xml()


def _recv_on_channel(ws, channel: str, max_msgs: int = 15) -> dict:
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("channel") == channel:
            return msg
    raise AssertionError(f"No message on channel '{channel}' after {max_msgs} attempts")


# ── 1. Authentication ─────────────────────────────────────────────────────────


class TestAtakAuthentication:

    def test_atak_device_can_login_with_jwt(self, client):
        """An ATAK device obtains a JWT via /auth/login and can use it."""
        callsign, token, _ = register(client)
        assert token, "Expected a JWT token"
        me = client.get("/auth/me", headers=auth(token)).json()
        assert me["callsign"] == callsign

    def test_unauthenticated_cot_post_is_rejected(self, client):
        """CoT without JWT returns 401 — device must authenticate first."""
        r = client.post(
            "/cot",
            content=_atak_cot("GHOST"),
            headers={"Content-Type": "application/xml"},
        )
        assert r.status_code == 401


# ── 2. Own-position CoT ───────────────────────────────────────────────────────


class TestAtakOwnPosition:

    def test_own_position_cot_returns_ack_xml(self, client):
        """POST /cot with uid==ARROW.{callsign} returns a CoT XML acknowledgement."""
        callsign, token, _ = register(client)

        r = client.post(
            "/cot",
            content=_atak_cot(callsign, lat=51.0, lon=4.5, hae=150.0),
            headers={**auth(token), "Content-Type": "application/xml"},
        )

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/xml")
        root = etree.fromstring(r.content)
        assert root.tag == "event"
        assert f"ARROW.{callsign}" in root.get("uid", "")

    def test_own_position_stored_in_db(self, client):
        """After POST /cot the operator's coordinates are persisted."""
        callsign, token, _ = register(client)

        client.post(
            "/cot",
            content=_atak_cot(callsign, lat=48.8566, lon=2.3522, hae=35.0),
            headers={**auth(token), "Content-Type": "application/xml"},
        )

        ops = client.get("/tracking/live", headers=auth(token)).json()
        me = next((o for o in ops if o["callsign"] == callsign), None)
        assert me is not None, "Operator not found in /tracking/live"
        assert abs(me["latitude"] - 48.8566) < 1e-4
        assert abs(me["longitude"] - 2.3522) < 1e-4
        assert me["status"] == "ONLINE"

    def test_own_position_snapshot_retrievable_as_cot_xml(self, client):
        """GET /cot/{uid} returns the latest position as valid CoT XML."""
        callsign, token, _ = register(client)

        client.post(
            "/cot",
            content=_atak_cot(callsign, lat=52.37, lon=4.9),
            headers={**auth(token), "Content-Type": "application/xml"},
        )

        r = client.get(f"/cot/ARROW.{callsign}", headers=auth(token))
        assert r.status_code == 200
        root = etree.fromstring(r.content)
        point = root.find("point")
        assert point is not None
        assert abs(float(point.get("lat")) - 52.37) < 1e-4
        assert abs(float(point.get("lon")) - 4.9) < 1e-4

    def test_position_not_available_before_first_cot(self, client):
        """GET /cot/{uid} returns 404 until the device sends its first position."""
        callsign, token, _ = register(client)
        r = client.get(f"/cot/ARROW.{callsign}", headers=auth(token))
        assert r.status_code == 404


# ── 3. Cross-device position visibility ──────────────────────────────────────


class TestAtakCrossDeviceVisibility:

    def test_device_a_position_visible_to_device_b(self, client):
        """Device A's position appears in /tracking/live for device B."""
        callsign_a, token_a, _ = register(client)
        _, token_b, _ = register(client)

        client.post(
            "/cot",
            content=_atak_cot(callsign_a, lat=51.5, lon=0.12),
            headers={**auth(token_a), "Content-Type": "application/xml"},
        )

        live = client.get("/tracking/live", headers=auth(token_b)).json()
        device_a = next((o for o in live if o["callsign"] == callsign_a), None)
        assert device_a is not None
        assert abs(device_a["latitude"] - 51.5) < 1e-4
        assert abs(device_a["longitude"] - 0.12) < 1e-4

    def test_multiple_position_updates_reflect_latest(self, client):
        """Consecutive CoT posts update the stored position (not accumulate)."""
        callsign, token, _ = register(client)

        for lat in [48.0, 49.0, 50.0]:
            client.post(
                "/cot",
                content=_atak_cot(callsign, lat=lat, lon=3.0),
                headers={**auth(token), "Content-Type": "application/xml"},
            )

        ops = client.get("/tracking/live", headers=auth(token)).json()
        me = next(o for o in ops if o["callsign"] == callsign)
        assert abs(me["latitude"] - 50.0) < 1e-4  # only the last update


# ── 4. Foreign-entity (hostile/unknown) CoT tracks ───────────────────────────


class TestAtakForeignTracks:

    def _hostile_uid(self) -> str:
        return f"HOSTILE-{uuid.uuid4().hex[:8].upper()}"

    def test_atak_reports_hostile_track(self, client):
        """ATAK sends a hostile CoT (non-ARROW uid) → stored in /cot/tracks."""
        _, token, _ = register(client)
        uid = self._hostile_uid()

        r = client.post(
            "/cot",
            content=_atak_cot(
                "ENEMY-ALPHA",
                uid=uid,
                cot_type="a-h-G-U-C-I",
                lat=50.0,
                lon=5.0,
                team="Red",
            ),
            headers={**auth(token), "Content-Type": "application/xml"},
        )
        assert r.status_code == 200

        tracks = client.get("/cot/tracks", headers=auth(token)).json()
        match = next((t for t in tracks if t["cot_uid"] == uid), None)
        assert match is not None, f"Hostile track {uid} not found in /cot/tracks"
        assert match["cot_type"] == "a-h-G-U-C-I"
        assert abs(match["latitude"] - 50.0) < 1e-4
        assert abs(match["longitude"] - 5.0) < 1e-4

    def test_foreign_track_sidc_is_populated(self, client):
        """GET /cot/tracks includes SIDC for each foreign track."""
        _, token, _ = register(client)
        uid = self._hostile_uid()

        client.post(
            "/cot",
            content=_atak_cot("ENEMY-1", uid=uid, cot_type="a-h-G-U-C-A"),
            headers={**auth(token), "Content-Type": "application/xml"},
        )

        tracks = client.get("/cot/tracks", headers=auth(token)).json()
        match = next(t for t in tracks if t["cot_uid"] == uid)
        assert match.get("sidc"), "SIDC must be populated for map rendering"

    def test_multiple_foreign_tracks_from_one_device(self, client):
        """ATAK reports three distinct hostile contacts; all appear in /cot/tracks."""
        _, token, _ = register(client)
        uids = [self._hostile_uid() for _ in range(3)]

        for i, uid in enumerate(uids):
            client.post(
                "/cot",
                content=_atak_cot(
                    f"ENEMY-{i}",
                    uid=uid,
                    cot_type="a-h-G-U-C-I",
                    lat=50.0 + i * 0.01,
                    lon=5.0,
                ),
                headers={**auth(token), "Content-Type": "application/xml"},
            )

        tracks = client.get("/cot/tracks", headers=auth(token)).json()
        found_uids = {t["cot_uid"] for t in tracks}
        for uid in uids:
            assert uid in found_uids

    def test_foreign_track_update_overwrites_position(self, client):
        """Repeated CoT for the same foreign uid updates position in place."""
        _, token, _ = register(client)
        uid = self._hostile_uid()

        for lat in [49.0, 49.5]:
            client.post(
                "/cot",
                content=_atak_cot(
                    "ROAMER", uid=uid, cot_type="a-h-G-U-C-I", lat=lat, lon=4.0
                ),
                headers={**auth(token), "Content-Type": "application/xml"},
            )

        tracks = client.get("/cot/tracks", headers=auth(token)).json()
        matches = [t for t in tracks if t["cot_uid"] == uid]
        assert len(matches) == 1, "Same uid should produce a single track row"
        assert abs(matches[0]["latitude"] - 49.5) < 1e-4

    def test_admin_can_delete_foreign_track(self, client):
        """DELETE /cot/tracks/{id} removes a hostile track from the map."""
        _, token, _ = register(client)

        uid = self._hostile_uid()
        client.post(
            "/cot",
            content=_atak_cot("DEAD-TARGET", uid=uid, cot_type="a-h-G-U-C-I"),
            headers={**auth(token), "Content-Type": "application/xml"},
        )

        from tests.conftest import admin_token, auth as _auth

        admin_tok = admin_token(client)
        tracks = client.get("/cot/tracks", headers=_auth(admin_tok)).json()
        match = next(t for t in tracks if t["cot_uid"] == uid)
        track_id = match["id"]

        r = client.delete(f"/cot/tracks/{track_id}", headers=_auth(admin_tok))
        assert r.status_code == 204

        tracks_after = client.get("/cot/tracks", headers=_auth(admin_tok)).json()
        assert not any(t["id"] == track_id for t in tracks_after)


# ── 5. Real-time WebSocket sync ───────────────────────────────────────────────


class TestAtakWebSocketSync:

    def test_own_position_broadcast_received_on_ws(self, client):
        """POST /cot triggers a 'tracking'/'position' event on WS subscribers."""
        callsign, token, _ = register(client)

        with client.websocket_connect(f"/ws?token={token}") as ws:
            client.post(
                "/cot",
                content=_atak_cot(callsign, lat=53.0, lon=6.0),
                headers={**auth(token), "Content-Type": "application/xml"},
            )
            msg = _recv_on_channel(ws, "tracking")

        assert msg["event"] == "position"
        assert msg["data"]["callsign"] == callsign
        assert abs(msg["data"]["latitude"] - 53.0) < 1e-4
        assert abs(msg["data"]["longitude"] - 6.0) < 1e-4
        assert "cot_xml" in msg
        assert "cot_type" in msg["data"]

    def test_ws_message_contains_cot_xml(self, client):
        """The cot_xml field in the WS message is parseable CoT XML."""
        callsign, token, _ = register(client)

        with client.websocket_connect(f"/ws?token={token}") as ws:
            client.post(
                "/cot",
                content=_atak_cot(callsign, lat=50.0, lon=3.0),
                headers={**auth(token), "Content-Type": "application/xml"},
            )
            msg = _recv_on_channel(ws, "tracking")

        parsed = parse_cot(msg["cot_xml"])
        assert f"ARROW.{callsign}" == parsed.uid

    def test_device_b_receives_device_a_position_update_via_ws(self, client):
        """Device B's WS receives a tracking event when device A updates position."""
        callsign_a, token_a, _ = register(client)
        _, token_b, _ = register(client)

        with client.websocket_connect(f"/ws?token={token_b}") as ws:
            client.post(
                "/cot",
                content=_atak_cot(callsign_a, lat=47.0, lon=8.0),
                headers={**auth(token_a), "Content-Type": "application/xml"},
            )
            msg = _recv_on_channel(ws, "tracking")

        assert msg["data"]["callsign"] == callsign_a

    def test_foreign_track_broadcast_received_on_ws(self, client):
        """A foreign/hostile CoT triggers a 'cot-track' event on WS subscribers."""
        _, token, _ = register(client)
        uid = f"HOSTILE-{uuid.uuid4().hex[:8].upper()}"

        with client.websocket_connect(f"/ws?token={token}") as ws:
            client.post(
                "/cot",
                content=_atak_cot(
                    "ENEMY-BRAVO", uid=uid, cot_type="a-h-G-U-C-I", lat=49.0, lon=2.0
                ),
                headers={**auth(token), "Content-Type": "application/xml"},
            )
            msg = _recv_on_channel(ws, "cot-track")

        assert msg["event"] == "update"
        assert msg["data"]["cot_uid"] == uid
        assert msg["data"]["cot_type"] == "a-h-G-U-C-I"
        assert "sidc" in msg["data"]


# ── 6. ATAK locale robustness ─────────────────────────────────────────────────


class TestAtakLocaleRobustness:

    def _european_locale_cot(self, callsign: str) -> bytes:
        """Manually craft CoT XML with European comma decimal separators."""
        return (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<event version="2.0" uid="ARROW.' + callsign.encode() + b'"'
            b' type="a-f-G-U-C"'
            b' time="2024-06-01T12:00:00.000000Z"'
            b' start="2024-06-01T12:00:00.000000Z"'
            b' stale="2024-06-01T12:01:30.000000Z"'
            b' how="m-g">'
            b'<point lat="51,2345" lon="4,4567" hae="100,0" ce="9999999,0" le="9999999,0"/>'
            b"<detail>"
            b'  <uid Droid="' + callsign.encode() + b'"/>'
            b'  <contact callsign="' + callsign.encode() + b'"/>'
            b'  <takv os="30" version="4.8.0" device="Samsung Galaxy" platform="ATAK-Android"/>'
            b"</detail>"
            b"</event>"
        )

    def test_comma_decimal_position_accepted(self, client):
        """CoT with comma decimal coordinates (European ATAK locale) is parsed correctly."""
        callsign, token, _ = register(client)

        r = client.post(
            "/cot",
            content=self._european_locale_cot(callsign),
            headers={**auth(token), "Content-Type": "application/xml"},
        )
        assert r.status_code == 200

        ops = client.get("/tracking/live", headers=auth(token)).json()
        me = next((o for o in ops if o["callsign"] == callsign), None)
        assert me is not None
        assert abs(me["latitude"] - 51.2345) < 1e-4
        assert abs(me["longitude"] - 4.4567) < 1e-4
