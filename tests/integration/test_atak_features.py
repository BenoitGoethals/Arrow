"""Integration tests for the five ATAK CoT feature pipelines.

Tests the full stack from CoT XML → DB row → WebSocket broadcast:

  Feature 1 — Emergency / panic button
  Feature 2 — SA marker remarks stored on CotTrack
  Feature 3 — ATAK shapes: GET /cot/shapes endpoint + DB persistence
  Feature 4 — Spot / contact reports
  Feature 5 — File-share: photo stored, chat message broadcast

Handler functions are called directly (bypassing the TCP socket) so the tests
remain fast and deterministic.  Each test gets a fresh in-memory SQLite DB via
the shared `client` fixture.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from lxml import etree

from contextlib import contextmanager

from backend.cot.cot import CotEvent
from tests.conftest import auth, register


@contextmanager
def _tcp_db():
    """Redirect tcp_server.SessionLocal to the current test DB.

    tcp_server.py binds SessionLocal at import time so FastAPI's dependency-
    override doesn't reach it.  Patching the module attribute here makes the
    handlers write into the same in-memory SQLite instance the test uses.
    """
    import backend.storage.database as _dbmod
    with patch("backend.cot.tcp_server.SessionLocal", _dbmod.SessionLocal):
        yield

# ── XML builders ──────────────────────────────────────────────────────────────

_TS = "2026-06-13T10:00:00.000000Z"
_ST = "2026-06-13T10:30:00.000000Z"


def _ev(cot_type: str, uid: str = "TEST", lat: float = 51.5, lon: float = 4.2) -> bytes:
    root = etree.Element(
        "event", version="2.0", uid=uid, type=cot_type,
        time=_TS, start=_TS, stale=_ST, how="h-g-i-g-o",
    )
    etree.SubElement(root, "point",
                     lat=str(lat), lon=str(lon),
                     hae="0.0", ce="9999999.0", le="9999999.0")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _emergency_xml(callsign: str = "OPS-1", active: bool = True,
                   lat: float = 51.5, lon: float = 4.2) -> bytes:
    cot_type = "b-a-o-opn" if active else "b-a-o-can"
    root = etree.Element(
        "event", version="2.0", uid=f"ATAK.{callsign}",
        type=cot_type, time=_TS, start=_TS, stale=_ST, how="h-g-i-g-o",
    )
    etree.SubElement(root, "point",
                     lat=str(lat), lon=str(lon),
                     hae="0.0", ce="9999999.0", le="9999999.0")
    det = etree.SubElement(root, "detail")
    etree.SubElement(det, "contact", callsign=callsign)
    etree.SubElement(det, "emergency", type="911 Alert" if active else "Cancelled")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _spot_xml(callsign: str = "RECON-1",
              remarks: str = "Enemy vehicle spotted",
              cot_type: str = "b-r-f-h-s") -> bytes:
    root = etree.Element(
        "event", version="2.0", uid=f"SPOT.{callsign}",
        type=cot_type, time=_TS, start=_TS, stale=_ST, how="h-g-i-g-o",
    )
    etree.SubElement(root, "point",
                     lat="50.9", lon="3.7",
                     hae="0.0", ce="9999999.0", le="9999999.0")
    det = etree.SubElement(root, "detail")
    etree.SubElement(det, "contact", callsign=callsign)
    rem = etree.SubElement(det, "remarks")
    rem.text = remarks
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _route_xml(uid: str = "ROUTE-001",
               callsign: str = "BC-1",
               pts: list[tuple[float, float]] | None = None) -> bytes:
    pts = pts or [(51.5, 4.2), (51.6, 4.3), (51.7, 4.4)]
    root = etree.Element(
        "event", version="2.0", uid=uid,
        type="b-m-r", time=_TS, start=_TS, stale=_ST, how="h-g-i-g-o",
    )
    etree.SubElement(root, "point",
                     lat="51.5", lon="4.2",
                     hae="0.0", ce="9999999.0", le="9999999.0")
    det = etree.SubElement(root, "detail")
    etree.SubElement(det, "contact", callsign=callsign)
    rem = etree.SubElement(det, "remarks")
    rem.text = "Supply Route Alpha"
    for lat, lon in pts:
        etree.SubElement(det, "link", lat=str(lat), lon=str(lon),
                         type="b-m-p-w", uid=f"WP-{lat}")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _fileshare_xml(filename: str = "recon.jpg",
                   sender: str = "OPS-2",
                   url: str = "http://192.168.0.1:8080/Attachment/recon.jpg") -> bytes:
    root = etree.Element(
        "event", version="2.0", uid=f"FS.{sender}",
        type="b-f-t-a", time=_TS, start=_TS, stale=_ST, how="h-g-i-g-o",
    )
    etree.SubElement(root, "point",
                     lat="0.0", lon="0.0",
                     hae="0.0", ce="9999999.0", le="9999999.0")
    det = etree.SubElement(root, "detail")
    etree.SubElement(det, "fileshare",
                     filename=filename, name=filename,
                     senderCallsign=sender,
                     sizeInBytes="4096", sha256hash="deadbeef")
    etree.SubElement(det, "ackrequest",
                     uid=f"ACK.{sender}", tag=filename, endpoint=url)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


# ── helpers ───────────────────────────────────────────────────────────────────

def _recv_channel(ws, channel: str, max_msgs: int = 20) -> dict:
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("channel") == channel:
            return msg
    raise AssertionError(f"No message on channel '{channel}' in {max_msgs} WS messages")


def _run(coro):
    """Run a coroutine synchronously (used to call async handlers in tests)."""
    return asyncio.run(coro)


# ── Feature 1: Emergency / panic button ──────────────────────────────────────

class TestEmergencyAlert:

    def test_active_emergency_creates_alert_and_broadcasts(self, client):
        """_handle_emergency() with active=True creates an ATAK_EMERGENCY alert."""
        callsign, token, op_id = register(client, role="OPERATOR")

        from backend.cot.cot import parse_emergency
        from backend.cot.tcp_server import _handle_emergency

        emerg = parse_emergency(_emergency_xml(callsign, active=True))
        assert emerg is not None

        broadcasts = []
        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock(side_effect=lambda d: broadcasts.append(d))
            _run(_handle_emergency(emerg))

        assert len(broadcasts) == 1
        msg = broadcasts[0]
        assert msg["channel"] == "alert"
        assert msg["event"]   == "triggered"
        assert msg["data"]["type"] == "ATAK_EMERGENCY"
        assert msg["data"]["status"] == "ACTIVE"

    def test_emergency_persisted_in_db(self, client):
        """Active emergency creates an Alert row with type=ATAK_EMERGENCY."""
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_emergency
        from backend.cot.tcp_server import _handle_emergency
        from backend.storage.database import SessionLocal
        from backend.storage.models import Alert

        emerg = parse_emergency(_emergency_xml(callsign, active=True))
        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            _run(_handle_emergency(emerg))

        with SessionLocal() as db:
            a = db.query(Alert).filter(
                Alert.type == "ATAK_EMERGENCY"
            ).first()
        assert a is not None
        assert a.status == "ACTIVE"

    def test_cancel_resolves_active_emergency(self, client):
        """Cancel CoT (b-a-o-can) sets existing ATAK_EMERGENCY to RESOLVED."""
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_emergency
        from backend.cot.tcp_server import _handle_emergency
        from backend.storage.database import SessionLocal
        from backend.storage.models import Alert

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            _run(_handle_emergency(
                parse_emergency(_emergency_xml(callsign, active=True))
            ))
            _run(_handle_emergency(
                parse_emergency(_emergency_xml(callsign, active=False))
            ))

        with SessionLocal() as db:
            a = db.query(Alert).filter(Alert.type == "ATAK_EMERGENCY").first()
        assert a.status == "RESOLVED"

    def test_cancel_broadcasts_ack_event(self, client):
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_emergency
        from backend.cot.tcp_server import _handle_emergency

        broadcasts = []
        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock(side_effect=lambda d: broadcasts.append(d))
            _run(_handle_emergency(
                parse_emergency(_emergency_xml(callsign, active=True))
            ))
            _run(_handle_emergency(
                parse_emergency(_emergency_xml(callsign, active=False))
            ))

        events = [b["event"] for b in broadcasts]
        assert "triggered" in events
        assert "ack" in events

    def test_emergency_visible_via_alerts_api(self, client):
        """After handler runs, GET /alerts returns the ATAK_EMERGENCY entry."""
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_emergency
        from backend.cot.tcp_server import _handle_emergency

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            _run(_handle_emergency(
                parse_emergency(_emergency_xml(callsign, active=True))
            ))

        r = client.get("/alerts", headers=auth(token))
        assert r.status_code == 200
        types = [a["type"] for a in r.json()]
        assert "ATAK_EMERGENCY" in types


# ── Feature 2: SA marker remarks stored on CotTrack ──────────────────────────

class TestCotTrackRemarks:

    def test_remarks_stored_on_foreign_track(self, client):
        """CoT position event with <remarks> stores the text on the CotTrack row."""
        _, token, _ = register(client)

        # Build a foreign CoT (uid != ARROW.*) with remarks
        uid = "SIM.CONTACT-1"
        root = etree.fromstring(
            CotEvent(uid=uid, cot_type="a-h-G-U-C-I",
                     lat=50.5, lon=3.9, callsign="CONTACT-1").to_xml()
        )
        rem = etree.SubElement(root.find("detail"), "remarks")
        rem.text = "Observed in tree-line, 4 dismounts"
        xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8")

        r = client.post("/cot", content=xml,
                        headers={**auth(token), "Content-Type": "application/xml"})
        assert r.status_code == 200

        from backend.storage.database import SessionLocal
        from backend.storage.models import CotTrack
        with SessionLocal() as db:
            track = db.query(CotTrack).filter(CotTrack.cot_uid == uid).first()
        assert track is not None
        assert track.remarks == "Observed in tree-line, 4 dismounts"

    def test_remarks_included_in_cot_tracks_response(self, client):
        """GET /cot/tracks includes the remarks field."""
        _, token, _ = register(client)

        uid = "SIM.RECON-99"
        root = etree.fromstring(
            CotEvent(uid=uid, cot_type="a-h-G-U-C-R",
                     lat=51.0, lon=4.0, callsign="RECON-99").to_xml()
        )
        rem = etree.SubElement(root.find("detail"), "remarks")
        rem.text = "Vehicle headed NW"
        xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
        client.post("/cot", content=xml,
                    headers={**auth(token), "Content-Type": "application/xml"})

        r = client.get("/cot/tracks", headers=auth(token))
        assert r.status_code == 200
        tracks = r.json()
        t = next((t for t in tracks if t["cot_uid"] == uid), None)
        assert t is not None
        assert t.get("remarks") == "Vehicle headed NW"

    def test_no_remarks_field_is_none_or_empty(self, client):
        """Track without <remarks> has remarks=None or '' — not missing from response."""
        _, token, _ = register(client)
        uid = "SIM.BARE-TRACK"
        xml = CotEvent(uid=uid, cot_type="a-h-G-U-C-I",
                       lat=50.0, lon=4.0, callsign="BARE").to_xml()
        client.post("/cot", content=xml,
                    headers={**auth(token), "Content-Type": "application/xml"})

        r = client.get("/cot/tracks", headers=auth(token))
        tracks = r.json()
        t = next((t for t in tracks if t["cot_uid"] == uid), None)
        assert t is not None
        assert t.get("remarks") in (None, "")


# ── Feature 3: ATAK shapes ────────────────────────────────────────────────────

class TestAtakShapes:

    def test_shape_persisted_via_handler(self, client):
        """_handle_atak_shape() creates an AtakShape row in the DB."""
        from backend.cot.cot import parse_atak_shape
        from backend.cot.tcp_server import _handle_atak_shape
        from backend.storage.database import SessionLocal
        from backend.storage.models import AtakShape

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            shape = parse_atak_shape(_route_xml())
            assert shape is not None
            _run(_handle_atak_shape(shape))

        with SessionLocal() as db:
            s = db.query(AtakShape).filter(AtakShape.uid == "ROUTE-001").first()
        assert s is not None
        assert s.shape_type == "ROUTE"
        assert s.callsign   == "BC-1"
        geo = json.loads(s.geometry_json)
        assert geo["type"] == "LineString"
        assert len(geo["coordinates"]) == 3

    def test_shape_upserted_on_repeat(self, client):
        """Sending the same uid twice updates rather than duplicating."""
        from backend.cot.cot import parse_atak_shape
        from backend.cot.tcp_server import _handle_atak_shape
        from backend.storage.database import SessionLocal
        from backend.storage.models import AtakShape

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            _run(_handle_atak_shape(parse_atak_shape(_route_xml(
                pts=[(51.5, 4.2), (51.6, 4.3)]
            ))))
            _run(_handle_atak_shape(parse_atak_shape(_route_xml(
                pts=[(51.5, 4.2), (51.6, 4.3), (51.7, 4.4)]
            ))))

        with SessionLocal() as db:
            count  = db.query(AtakShape).filter(AtakShape.uid == "ROUTE-001").count()
            latest = db.query(AtakShape).filter(AtakShape.uid == "ROUTE-001").first()
        assert count == 1
        assert len(json.loads(latest.geometry_json)["coordinates"]) == 3

    def test_shape_broadcasts_on_atak_shape_channel(self, client):
        from backend.cot.cot import parse_atak_shape
        from backend.cot.tcp_server import _handle_atak_shape

        broadcasts = []
        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock(side_effect=lambda d: broadcasts.append(d))
            _run(_handle_atak_shape(parse_atak_shape(_route_xml(uid="BCAST-ROUTE"))))

        assert any(b["channel"] == "atak-shape" for b in broadcasts)
        msg = next(b for b in broadcasts if b["channel"] == "atak-shape")
        assert msg["event"] == "upsert"
        assert msg["data"]["uid"] == "BCAST-ROUTE"

    def test_get_cot_shapes_requires_auth(self, client):
        r = client.get("/cot/shapes")
        assert r.status_code == 401

    def test_get_cot_shapes_empty_initially(self, client):
        _, token, _ = register(client)
        r = client.get("/cot/shapes", headers=auth(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_get_cot_shapes_returns_persisted(self, client):
        _, token, _ = register(client)

        from backend.cot.cot import parse_atak_shape
        from backend.cot.tcp_server import _handle_atak_shape

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            _run(_handle_atak_shape(parse_atak_shape(
                _route_xml(uid="API-ROUTE", callsign="BC-1",
                           pts=[(51.5, 4.2), (51.6, 4.3)])
            )))

        r = client.get("/cot/shapes", headers=auth(token))
        assert r.status_code == 200
        shapes = r.json()
        assert len(shapes) == 1
        s = shapes[0]
        assert s["uid"]        == "API-ROUTE"
        assert s["shape_type"] == "ROUTE"
        assert s["callsign"]   == "BC-1"
        assert "geometry_json" in s
        geo = json.loads(s["geometry_json"])
        assert geo["type"] == "LineString"

    def test_get_cot_shapes_multiple(self, client):
        _, token, _ = register(client)

        from backend.cot.cot import parse_atak_shape
        from backend.cot.tcp_server import _handle_atak_shape

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            for uid in ("SHAPE-A", "SHAPE-B", "SHAPE-C"):
                _run(_handle_atak_shape(parse_atak_shape(
                    _route_xml(uid=uid, pts=[(51.0, 4.0), (51.1, 4.1)])
                )))

        r = client.get("/cot/shapes", headers=auth(token))
        assert len(r.json()) == 3


# ── Feature 4: Spot / contact reports ────────────────────────────────────────

class TestSpotReport:

    def test_spot_report_creates_report_row(self, client):
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_spot_report
        from backend.cot.tcp_server import _handle_spot_report
        from backend.storage.database import SessionLocal
        from backend.storage.models import Report

        spot = parse_spot_report(_spot_xml(callsign, remarks="4 BTR seen at crossroads"))
        assert spot is not None

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            _run(_handle_spot_report(spot))

        with SessionLocal() as db:
            rep = db.query(Report).filter(Report.type == "CONTACT_REPORT").first()
        assert rep is not None
        payload = json.loads(rep.payload)
        assert "BTR" in payload.get("remarks", "")

    def test_spot_report_broadcasts_on_report_channel(self, client):
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_spot_report
        from backend.cot.tcp_server import _handle_spot_report

        broadcasts = []
        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock(side_effect=lambda d: broadcasts.append(d))
            _run(_handle_spot_report(
                parse_spot_report(_spot_xml(callsign))
            ))

        assert any(b["channel"] == "report" for b in broadcasts)
        msg = next(b for b in broadcasts if b["channel"] == "report")
        assert msg["data"]["type"]   == "CONTACT_REPORT"
        assert msg["data"]["source"] == "ATAK"

    def test_spot_report_visible_via_api(self, client):
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_spot_report
        from backend.cot.tcp_server import _handle_spot_report

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            _run(_handle_spot_report(
                parse_spot_report(_spot_xml(callsign, remarks="Contact report"))
            ))

        r = client.get("/reports", headers=auth(token))
        assert r.status_code == 200
        types = [rep["type"] for rep in r.json()]
        assert "CONTACT_REPORT" in types

    def test_multiple_spot_types_all_persisted(self, client):
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_spot_report
        from backend.cot.tcp_server import _handle_spot_report
        from backend.storage.database import SessionLocal
        from backend.storage.models import Report

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            for cot_type in ("b-r-f-h-s", "b-r-f-h-i", "b-r-f-n"):
                _run(_handle_spot_report(
                    parse_spot_report(_spot_xml(callsign, cot_type=cot_type))
                ))

        with SessionLocal() as db:
            count = db.query(Report).filter(
                Report.type == "CONTACT_REPORT"
            ).count()
        assert count == 3


# ── Feature 5: File share / photo ─────────────────────────────────────────────

class TestFileshare:

    FAKE_JPEG = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\xff\xd9"
    )

    def _run_fileshare(self, callsign: str, fake_bytes: bytes = None):
        """Run _handle_fileshare_announcement with mocked HTTP download."""
        from backend.cot.cot import parse_fileshare_announcement
        from backend.cot.tcp_server import _handle_fileshare_announcement
        import io

        fs = parse_fileshare_announcement(
            _fileshare_xml(sender=callsign,
                           url="http://192.168.0.1:8080/Attachment/recon.jpg")
        )
        assert fs is not None

        raw_bytes = fake_bytes or self.FAKE_JPEG

        broadcasts = []

        # Patch urlopen so run_in_executor returns our fake bytes
        class _FakeResponse:
            def read(self): return raw_bytes
            def __enter__(self): return self
            def __exit__(self, *_): pass

        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock(side_effect=lambda d: broadcasts.append(d))
            with patch("urllib.request.urlopen", return_value=_FakeResponse()):
                _run(_handle_fileshare_announcement(fs, "192.168.0.1"))

        return broadcasts

    def test_fileshare_creates_photo_row(self, client):
        callsign, token, op_id = register(client)

        from backend.storage.database import SessionLocal
        from backend.storage.models import Photo

        self._run_fileshare(callsign)

        with SessionLocal() as db:
            photo = db.query(Photo).first()
        assert photo is not None
        assert photo.original_name == "recon.jpg"
        assert photo.mime_type     == "image/jpeg"

    def test_fileshare_creates_message_with_photo_id(self, client):
        callsign, token, op_id = register(client)

        from backend.storage.database import SessionLocal
        from backend.storage.models import Message, Photo

        self._run_fileshare(callsign)

        with SessionLocal() as db:
            photo = db.query(Photo).first()
            msg   = db.query(Message).filter(
                Message.photo_id == photo.id
            ).first()
        assert msg is not None
        assert msg.message_type == "BROADCAST"
        assert callsign in msg.content or "ATAK" in msg.content

    def test_fileshare_broadcasts_on_chat_channel(self, client):
        callsign, token, op_id = register(client)

        broadcasts = self._run_fileshare(callsign)
        assert any(b.get("channel") == "chat" for b in broadcasts)
        msg = next(b for b in broadcasts if b.get("channel") == "chat")
        assert msg["data"]["photo_id"] is not None
        assert msg["data"]["source"]   == "ATAK"

    def test_fileshare_message_visible_via_api(self, client):
        callsign, token, op_id = register(client)

        self._run_fileshare(callsign)

        r = client.get("/messages", headers=auth(token))
        assert r.status_code == 200
        msgs = r.json()
        assert any(m.get("photo_id") is not None for m in msgs)

    def test_fileshare_missing_url_skipped(self, client):
        """parse_fileshare_announcement returns None when no URL → handler not called."""
        from backend.cot.cot import parse_fileshare_announcement

        ev = etree.Element(
            "event", version="2.0", uid="FS.NOURL",
            type="b-f-t-a", time=_TS, start=_TS, stale=_ST, how="h-g-i-g-o",
        )
        etree.SubElement(ev, "point",
                         lat="0.0", lon="0.0",
                         hae="0.0", ce="9999999.0", le="9999999.0")
        det = etree.SubElement(ev, "detail")
        etree.SubElement(det, "fileshare", filename="x.jpg",
                         senderCallsign="OPS", sizeInBytes="1")
        xml = etree.tostring(ev, xml_declaration=True, encoding="UTF-8")
        assert parse_fileshare_announcement(xml) is None

    def test_fileshare_download_failure_does_not_crash(self, client):
        """If the HTTP download fails, the handler logs a warning and returns."""
        callsign, token, op_id = register(client)

        from backend.cot.cot import parse_fileshare_announcement
        from backend.cot.tcp_server import _handle_fileshare_announcement
        from backend.storage.database import SessionLocal
        from backend.storage.models import Photo

        fs = parse_fileshare_announcement(
            _fileshare_xml(sender=callsign,
                           url="http://192.168.0.1:8080/Attachment/recon.jpg")
        )

        import urllib.error
        with _tcp_db(), patch("backend.cot.tcp_server.broadcaster") as mock_bc:
            mock_bc.broadcast = AsyncMock()
            with patch("urllib.request.urlopen",
                       side_effect=urllib.error.URLError("connection refused")):
                # Must complete without raising
                _run(_handle_fileshare_announcement(fs, "192.168.0.1"))

        with SessionLocal() as db:
            assert db.query(Photo).count() == 0


# ── Startup: DB schema migration ──────────────────────────────────────────────

class TestDbMigrations:

    def test_atak_shapes_table_exists(self, client):
        """The atak_shapes table was created by the migration."""
        from backend.storage.database import SessionLocal
        from backend.storage.models import AtakShape
        with SessionLocal() as db:
            count = db.query(AtakShape).count()
        assert count == 0  # empty but accessible

    def test_cot_track_remarks_column_exists(self, client):
        """The cot_tracks.remarks column was added by the migration."""
        from backend.storage.database import SessionLocal
        from backend.storage.models import CotTrack
        with SessionLocal() as db:
            # Create a row with remarks
            t = CotTrack(cot_uid="TEST-REMARKS", cot_type="a-h-G-U-C-I",
                         callsign="X", latitude=0.0, longitude=0.0,
                         remarks="test note")
            db.add(t)
            db.commit()
            db.refresh(t)
            assert t.remarks == "test note"
