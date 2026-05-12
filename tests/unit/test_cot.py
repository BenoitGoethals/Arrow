"""CoT (Cursor-on-Target) tests — unit + HTTP endpoint + security + WebSocket.

Coverage:
  - XML roundtrip for all CoT affiliations and field types
  - Role → CoT type mapping
  - SIDC ↔ CoT type bidirectional mapping
  - Stale-time calculation per affiliation
  - POST /cot: updates position, returns ack XML, broadcasts to WS
  - GET /cot/{uid}: returns snapshot XML
  - Security: XXE injection blocked, malformed XML returns 422 (no detail leak)
  - Auth: unauthenticated POST /cot returns 401
"""

from __future__ import annotations

import pytest
from lxml import etree

from backend.cot.cot import (
    COT_TO_SIDC,
    ROLE_TO_COT,
    SIDC_TO_COT,
    STALE_SECONDS,
    CotEvent,
    cot_type_to_sidc,
    parse_cot,
    role_to_cot_type,
    sidc_to_cot_type,
)
from tests.conftest import auth, register


def _recv_on_channel(ws, channel: str, max_msgs: int = 10) -> dict:
    """Drain WS messages until one matches the expected channel."""
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("channel") == channel:
            return msg
    raise AssertionError(f"No message on channel '{channel}' after {max_msgs} attempts")


# ── Unit: CotEvent.to_xml / parse_cot roundtrip ───────────────────────────────

class TestCotRoundtrip:
    def test_basic_fields(self):
        ev = CotEvent(uid="ARROW.ALPHA-1", cot_type="a-f-G-U-C",
                      lat=50.85, lon=4.35, hae=120.5, callsign="ALPHA-1")
        parsed = parse_cot(ev.to_xml())
        assert parsed.uid == "ARROW.ALPHA-1"
        assert parsed.cot_type == "a-f-G-U-C"
        assert abs(parsed.lat - 50.85) < 1e-6
        assert abs(parsed.lon - 4.35)  < 1e-6
        assert abs(parsed.hae - 120.5) < 1e-3
        assert parsed.callsign == "ALPHA-1"

    def test_track_data_preserved(self):
        ev = CotEvent(uid="ARROW.BC-1", cot_type="a-f-G-U-C-O",
                      lat=51.0, lon=5.0, speed=12.5, course=270.0)
        parsed = parse_cot(ev.to_xml())
        assert abs(parsed.speed - 12.5) < 0.01
        assert abs(parsed.course - 270.0) < 0.01

    def test_team_and_role_preserved(self):
        ev = CotEvent(uid="ARROW.OP-2", cot_type="a-f-G-U-C",
                      lat=50.0, lon=4.0, team="Alpha", role="Team Member")
        parsed = parse_cot(ev.to_xml())
        assert parsed.team == "Alpha"
        assert parsed.role == "Team Member"

    def test_hostile_type(self):
        ev = CotEvent(uid="HOSTILE-1", cot_type="a-h-G-U-C-I",
                      lat=49.0, lon=3.0)
        parsed = parse_cot(ev.to_xml())
        assert parsed.cot_type == "a-h-G-U-C-I"

    def test_neutral_poi(self):
        ev = CotEvent(uid="POI-1", cot_type="a-n-G-I-N", lat=48.5, lon=2.3)
        parsed = parse_cot(ev.to_xml())
        assert parsed.cot_type == "a-n-G-I-N"

    def test_bytes_and_str_input(self):
        ev = CotEvent(uid="X", cot_type="a-f-G-U-C", lat=0.0, lon=0.0)
        xml_bytes = ev.to_xml()
        xml_str   = ev.to_xml_str()
        assert parse_cot(xml_bytes).uid == "X"
        assert parse_cot(xml_str).uid   == "X"

    def test_output_is_valid_xml(self):
        ev = CotEvent(uid="VALID", cot_type="a-f-G-U-C", lat=1.0, lon=2.0)
        root = etree.fromstring(ev.to_xml())
        assert root.tag == "event"
        assert root.get("uid") == "VALID"
        assert root.find("point") is not None
        assert root.find("detail") is not None


# ── Unit: type mappings ───────────────────────────────────────────────────────

class TestTypeMappings:
    def test_role_to_cot_all_roles(self):
        assert role_to_cot_type("OPERATOR")       == "a-f-G-U-C"
        assert role_to_cot_type("BATTLE_CAPTAIN") == "a-f-G-U-C-O"
        assert role_to_cot_type("ADMIN")          == "a-f-G-U-C-O"
        assert role_to_cot_type("UNKNOWN")        == "a-f-G-U-C"  # default

    def test_sidc_to_cot_all_entries(self):
        for sidc, expected in SIDC_TO_COT.items():
            assert sidc_to_cot_type(sidc) == expected

    def test_sidc_to_cot_uppercase_normalisation(self):
        sidc = "shgpuci-----"
        assert sidc_to_cot_type(sidc) == sidc_to_cot_type(sidc.upper())

    def test_sidc_unknown_falls_back(self):
        assert sidc_to_cot_type("XXXXXXXX----") == "a-u-G"

    def test_cot_to_sidc_all_entries(self):
        for cot_type, expected_sidc in COT_TO_SIDC.items():
            assert cot_type_to_sidc(cot_type) == expected_sidc

    def test_cot_to_sidc_unknown_falls_back(self):
        assert cot_type_to_sidc("a-z-X-X") == "SUGPU-------"

    def test_bidirectional_consistency(self):
        """Every SIDC maps to a CoT type that maps back to the same SIDC."""
        for sidc, cot in SIDC_TO_COT.items():
            assert cot_type_to_sidc(cot) == sidc

    def test_role_cot_constants(self):
        assert "OPERATOR" in ROLE_TO_COT
        assert "BATTLE_CAPTAIN" in ROLE_TO_COT
        assert "ADMIN" in ROLE_TO_COT


# ── Unit: stale-time calculation ──────────────────────────────────────────────

class TestStaleTimes:
    def test_friendly_stale(self):
        ev = CotEvent(uid="F", cot_type="a-f-G-U-C", lat=0, lon=0)
        assert ev.stale_seconds == STALE_SECONDS["friendly"]

    def test_hostile_stale(self):
        ev = CotEvent(uid="H", cot_type="a-h-G-U-C-I", lat=0, lon=0)
        assert ev.stale_seconds == STALE_SECONDS["hostile"]

    def test_neutral_stale(self):
        ev = CotEvent(uid="N", cot_type="a-n-G-I-N", lat=0, lon=0)
        assert ev.stale_seconds == STALE_SECONDS["neutral"]

    def test_stale_timestamp_in_future(self):
        from datetime import datetime, timezone
        ev = CotEvent(uid="S", cot_type="a-f-G-U-C", lat=0, lon=0)
        root = etree.fromstring(ev.to_xml())
        stale_str = root.get("stale", "")
        stale_dt = datetime.fromisoformat(stale_str.replace("Z", "+00:00"))
        assert stale_dt > datetime.now(timezone.utc)


# ── HTTP endpoint: POST /cot ──────────────────────────────────────────────────

class TestCotEndpoint:

    def _cot_xml(self, callsign: str, lat: float = 50.85, lon: float = 4.35) -> bytes:
        ev = CotEvent(uid=f"ARROW.{callsign}", cot_type="a-f-G-U-C",
                      lat=lat, lon=lon, hae=100.0, callsign=callsign,
                      speed=5.0, course=90.0, team="Alpha", role="Team Member")
        return ev.to_xml()

    def test_post_cot_requires_auth(self, client):
        r = client.post("/cot", content=self._cot_xml("GHOST"),
                        headers={"Content-Type": "application/xml"})
        assert r.status_code == 401

    def test_post_cot_updates_position(self, client):
        _, token, _ = register(client)
        me = client.get("/auth/me", headers=auth(token)).json()
        callsign = me["callsign"]

        r = client.post(
            "/cot",
            content=self._cot_xml(callsign, lat=51.0, lon=4.5),
            headers={**auth(token), "Content-Type": "application/xml"},
        )
        assert r.status_code == 200
        assert b"</event>" in r.content      # returns ack CoT XML
        assert r.headers["content-type"].startswith("application/xml")

        # Position is now stored on the operator
        ops = client.get("/tracking/live", headers=auth(token)).json()
        me_op = next((o for o in ops if o["callsign"] == callsign), None)
        assert me_op is not None
        assert abs(me_op["latitude"]  - 51.0) < 1e-5
        assert abs(me_op["longitude"] - 4.5)  < 1e-5
        assert me_op["status"] == "ONLINE"

    def test_post_cot_ack_xml_valid(self, client):
        _, token, _ = register(client)
        callsign = client.get("/auth/me", headers=auth(token)).json()["callsign"]
        r = client.post(
            "/cot",
            content=self._cot_xml(callsign),
            headers={**auth(token), "Content-Type": "application/xml"},
        )
        root = etree.fromstring(r.content)
        assert root.tag == "event"
        assert f"ARROW.{callsign}" in root.get("uid", "")

    def test_post_cot_empty_body_rejected(self, client):
        _, token, _ = register(client)
        r = client.post("/cot", content=b"",
                        headers={**auth(token), "Content-Type": "application/xml"})
        assert r.status_code == 400

    def test_post_cot_malformed_xml_returns_422_no_detail_leak(self, client):
        _, token, _ = register(client)
        r = client.post(
            "/cot",
            content=b"<not valid xml<<<",
            headers={**auth(token), "Content-Type": "application/xml"},
        )
        assert r.status_code == 422
        body = r.json()
        # Error must be generic — must NOT expose lxml exception internals
        assert "Invalid CoT XML" == body.get("detail"), \
            f"Error leaked internal details: {body}"

    def test_post_cot_xxe_blocked(self, client):
        """XXE injection must be silently rejected, not parsed."""
        _, token, _ = register(client)
        xxe_payload = b"""<?xml version="1.0"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<event version="2.0" uid="ARROW.TEST" type="a-f-G-U-C"
       time="2024-01-01T00:00:00Z" start="2024-01-01T00:00:00Z"
       stale="2024-12-31T00:00:00Z" how="m-g">
  <point lat="50.0" lon="4.0" hae="0" ce="9999999" le="9999999"/>
  <detail>&xxe;</detail>
</event>"""
        r = client.post(
            "/cot",
            content=xxe_payload,
            headers={**auth(token), "Content-Type": "application/xml"},
        )
        # Must not succeed (either 422 or the entity is ignored and succeeds
        # without leaking file contents — either is acceptable)
        if r.status_code == 200:
            # If it processed, the response must NOT contain /etc/passwd content
            assert b"root:" not in r.content
            assert b"/bin/" not in r.content
        else:
            assert r.status_code in (400, 422)

    def test_post_cot_updates_last_seen(self, client):
        from datetime import datetime, timezone
        _, token, _ = register(client)
        callsign = client.get("/auth/me", headers=auth(token)).json()["callsign"]
        before = datetime.now(timezone.utc)

        client.post(
            "/cot",
            content=self._cot_xml(callsign),
            headers={**auth(token), "Content-Type": "application/xml"},
        )
        ops = client.get("/operators", headers=auth(token)).json()
        me_op = next(o for o in ops if o["callsign"] == callsign)
        raw = me_op["last_seen"]
        # SQLite may return naive ISO string; strip timezone and compare as naive UTC
        last_seen = datetime.fromisoformat(raw.replace("Z", "").split("+")[0])
        before_naive = before.replace(tzinfo=None)
        assert last_seen >= before_naive


# ── HTTP endpoint: GET /cot/{uid} ─────────────────────────────────────────────

class TestCotSnapshot:

    def test_get_snapshot_requires_auth(self, client):
        r = client.get("/cot/ARROW.GHOST")
        assert r.status_code == 401

    def test_get_snapshot_not_found_without_position(self, client):
        _, token, _ = register(client)
        callsign = client.get("/auth/me", headers=auth(token)).json()["callsign"]
        r = client.get(f"/cot/ARROW.{callsign}", headers=auth(token))
        assert r.status_code == 404

    def test_get_snapshot_after_position_update(self, client):
        _, token, _ = register(client)
        callsign = client.get("/auth/me", headers=auth(token)).json()["callsign"]
        ev = CotEvent(uid=f"ARROW.{callsign}", cot_type="a-f-G-U-C",
                      lat=52.0, lon=5.0, callsign=callsign)
        client.post("/cot", content=ev.to_xml(),
                    headers={**auth(token), "Content-Type": "application/xml"})

        r = client.get(f"/cot/ARROW.{callsign}", headers=auth(token))
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/xml")
        root = etree.fromstring(r.content)
        point = root.find("point")
        assert point is not None
        assert abs(float(point.get("lat")) - 52.0) < 1e-5
        assert abs(float(point.get("lon")) - 5.0)  < 1e-5


# ── WebSocket: CoT position broadcast ────────────────────────────────────────

class TestCotWebSocket:

    def test_cot_position_broadcast_over_ws(self, client):
        """POST /cot should broadcast a 'tracking' event on the WS channel."""
        _, token, _ = register(client)
        callsign = client.get("/auth/me", headers=auth(token)).json()["callsign"]

        with client.websocket_connect(f"/ws?token={token}") as ws:
            ev = CotEvent(uid=f"ARROW.{callsign}", cot_type="a-f-G-U-C",
                          lat=53.0, lon=6.0, callsign=callsign)
            client.post("/cot", content=ev.to_xml(),
                        headers={**auth(token), "Content-Type": "application/xml"})

            msg = _recv_on_channel(ws, "tracking")
            assert msg["event"]   == "position"
            data = msg["data"]
            assert data["callsign"] == callsign
            assert abs(data["latitude"]  - 53.0) < 1e-5
            assert abs(data["longitude"] - 6.0)  < 1e-5
            assert "cot_xml" in msg
            assert "cot_type" in data

    def test_ws_rejects_invalid_token(self, client):
        with pytest.raises(Exception):
            with client.websocket_connect("/ws?token=invalid.token.here") as ws:
                ws.receive_text()

    def test_tracking_position_also_broadcasts(self, client):
        """JSON /tracking/position also broadcasts on the tracking channel."""
        _, token, _ = register(client)
        callsign = client.get("/auth/me", headers=auth(token)).json()["callsign"]

        with client.websocket_connect(f"/ws?token={token}") as ws:
            client.post("/tracking/position", headers=auth(token),
                        json={"latitude": 48.0, "longitude": 2.3, "altitude": 50.0})
            msg = _recv_on_channel(ws, "tracking")
            assert msg["data"]["callsign"] == callsign
