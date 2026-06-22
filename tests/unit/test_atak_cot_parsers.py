"""Unit tests for the five new ATAK CoT parser functions.

Tests cover:
  - parse_emergency   : b-a-o-opn (active) and b-a-o-can (cancel)
  - parse_spot_report : b-r-f-* (non-MEDEVAC contact reports)
  - parse_fileshare_announcement : b-f-t-a (file transfer announcement)
  - parse_atak_shape  : b-m-r (route), u-d-* (drawing), u-rb-* (area)
  - parse_cot remarks : <detail/remarks> extraction
  - Negative cases    : wrong CoT type returns None
  - Security          : XXE injection blocked in every parser
"""

from __future__ import annotations

import json

import pytest
from lxml import etree

from backend.cot.cot import (
    parse_atak_shape,
    parse_cot,
    parse_emergency,
    parse_fileshare_announcement,
    parse_spot_report,
)

# ── XML builders ─────────────────────────────────────────────────────────────

_TS = "2026-06-13T10:00:00.000000Z"
_ST = "2026-06-13T10:01:30.000000Z"


def _event(
    cot_type: str, uid: str = "TEST-UID", lat: float = 51.5, lon: float = 4.2
) -> etree._Element:
    """Return a bare <event> element with <point>."""
    ev = etree.Element(
        "event",
        version="2.0",
        uid=uid,
        type=cot_type,
        time=_TS,
        start=_TS,
        stale=_ST,
        how="h-g-i-g-o",
    )
    etree.SubElement(
        ev,
        "point",
        lat=str(lat),
        lon=str(lon),
        hae="0.0",
        ce="9999999.0",
        le="9999999.0",
    )
    return ev


def _xml(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _add_detail(ev: etree._Element, **sub_elements) -> etree._Element:
    """Add a <detail> child with named sub-elements (tag → {attribs})."""
    det = etree.SubElement(ev, "detail")
    for tag, attrs in sub_elements.items():
        etree.SubElement(det, tag, **attrs)
    return det


# ── parse_emergency ───────────────────────────────────────────────────────────


class TestParseEmergency:

    def _make(
        self,
        cot_type: str,
        callsign: str = "OPS-1",
        lat: float = 51.5,
        lon: float = 4.2,
        emerg_text: str = "911 Alert",
    ) -> bytes:
        ev = _event(cot_type, uid=f"ATAK.{callsign}", lat=lat, lon=lon)
        det = etree.SubElement(ev, "detail")
        etree.SubElement(det, "contact", callsign=callsign)
        etree.SubElement(det, "emergency", type=emerg_text)
        return _xml(ev)

    def test_active_emergency_parsed(self):
        result = parse_emergency(self._make("b-a-o-opn"))
        assert result is not None
        assert result["active"] is True
        assert result["callsign"] == "OPS-1"
        assert abs(result["lat"] - 51.5) < 1e-5
        assert abs(result["lon"] - 4.2) < 1e-5
        assert result["text"] == "911 Alert"

    def test_cancel_emergency_parsed(self):
        result = parse_emergency(self._make("b-a-o-can", emerg_text="Cancelled"))
        assert result is not None
        assert result["active"] is False

    def test_emergency_subtype_accepted(self):
        # b-a-o-opn-s (soldier panic) should also match
        result = parse_emergency(self._make("b-a-o-opn-s"))
        assert result is not None
        assert result["active"] is True

    def test_fallback_callsign_from_uid(self):
        ev = _event("b-a-o-opn", uid="ATAK.BRAVO-2")
        etree.SubElement(ev, "detail")  # no <contact>
        result = parse_emergency(_xml(ev))
        assert result is not None
        assert result["callsign"] == "ATAK.BRAVO-2"

    def test_non_emergency_returns_none(self):
        assert parse_emergency(self._make("a-f-G-U-C")) is None
        assert parse_emergency(self._make("b-t-f")) is None
        assert parse_emergency(self._make("b-r-f-h-c")) is None

    def test_malformed_xml_returns_none(self):
        assert parse_emergency(b"not xml at all <<<") is None

    def test_string_input_accepted(self):
        xml_str = self._make("b-a-o-opn").decode("utf-8")
        result = parse_emergency(xml_str)
        assert result is not None

    def test_xxe_blocked(self):
        xxe = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<event version="2.0" uid="E" type="b-a-o-opn"
       time="2026-01-01T00:00:00Z" start="2026-01-01T00:00:00Z"
       stale="2026-01-01T00:01:00Z" how="h-g-i-g-o">
  <point lat="51.0" lon="4.0" hae="0" ce="9999999" le="9999999"/>
  <detail><contact callsign="&xxe;"/></detail>
</event>"""
        result = parse_emergency(xxe)
        if result is not None:
            assert "root:" not in result.get("callsign", "")

    def test_locale_comma_decimal(self):
        ev = _event("b-a-o-opn", lat=51.5, lon=4.2)
        # Manually set comma-decimal coords on the point element
        ev.find("point").set("lat", "51,5")
        ev.find("point").set("lon", "4,2")
        etree.SubElement(ev, "detail")
        result = parse_emergency(_xml(ev))
        assert result is not None
        assert abs(result["lat"] - 51.5) < 1e-3


# ── parse_spot_report ─────────────────────────────────────────────────────────


class TestParseSpotReport:

    def _make(
        self,
        cot_type: str = "b-r-f-h-s",
        callsign: str = "RECON-1",
        remarks: str = "Enemy vehicle spotted grid 123456",
        lat: float = 50.9,
        lon: float = 3.7,
    ) -> bytes:
        ev = _event(cot_type, uid=f"SPOT.{callsign}", lat=lat, lon=lon)
        det = etree.SubElement(ev, "detail")
        etree.SubElement(det, "contact", callsign=callsign)
        rem = etree.SubElement(det, "remarks")
        rem.text = remarks
        return _xml(ev)

    def test_spot_report_parsed(self):
        result = parse_spot_report(self._make())
        assert result is not None
        assert result["callsign"] == "RECON-1"
        assert "Enemy vehicle" in result["remarks"]
        assert result["cot_type"] == "b-r-f-h-s"
        assert abs(result["lat"] - 50.9) < 1e-5

    def test_multiple_subtypes(self):
        for t in ("b-r-f-h-s", "b-r-f-h-i", "b-r-f-i", "b-r-f-n"):
            assert parse_spot_report(self._make(t)) is not None

    def test_medevac_excluded(self):
        # b-r-f-h-c is MEDEVAC — must NOT match spot report
        assert parse_spot_report(self._make("b-r-f-h-c")) is None

    def test_non_spot_returns_none(self):
        assert parse_spot_report(self._make("a-f-G-U-C")) is None
        assert parse_spot_report(self._make("b-t-f")) is None

    def test_empty_remarks_accepted(self):
        ev = _event("b-r-f-h-s", uid="SPOT.ALPHA")
        det = etree.SubElement(ev, "detail")
        etree.SubElement(det, "contact", callsign="ALPHA")
        # No <remarks>
        result = parse_spot_report(_xml(ev))
        assert result is not None
        assert result["remarks"] == ""

    def test_malformed_returns_none(self):
        assert parse_spot_report(b"<bad>") is None

    def test_xxe_blocked(self):
        xxe = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<event version="2.0" uid="S" type="b-r-f-h-s"
       time="2026-01-01T00:00:00Z" start="2026-01-01T00:00:00Z"
       stale="2026-01-01T00:01:00Z" how="h-g-i-g-o">
  <point lat="51.0" lon="4.0" hae="0" ce="9999999" le="9999999"/>
  <detail><remarks>&xxe;</remarks></detail>
</event>"""
        result = parse_spot_report(xxe)
        if result is not None:
            assert "root:" not in result.get("remarks", "")


# ── parse_fileshare_announcement ──────────────────────────────────────────────


class TestParseFileshare:

    def _make(
        self,
        filename: str = "photo.jpg",
        sender: str = "OPS-2",
        url: str = "http://192.168.0.1:8080/Attachment/photo.jpg",
    ) -> bytes:
        ev = _event("b-f-t-a", uid=f"FS.{sender}")
        det = etree.SubElement(ev, "detail")
        etree.SubElement(
            det,
            "fileshare",
            filename=filename,
            name=filename,
            senderCallsign=sender,
            sizeInBytes="12345",
            sha256hash="abc123",
        )
        etree.SubElement(
            det, "ackrequest", uid=f"ACK.{sender}", tag=filename, endpoint=url
        )
        return _xml(ev)

    def test_basic_fileshare_parsed(self):
        result = parse_fileshare_announcement(self._make())
        assert result is not None
        assert result["filename"] == "photo.jpg"
        assert result["sender_callsign"] == "OPS-2"
        assert result["url"] == "http://192.168.0.1:8080/Attachment/photo.jpg"
        assert result["mime"] == "image/jpeg"

    def test_mime_inference_jpg(self):
        r = parse_fileshare_announcement(self._make("snap.jpg"))
        assert r["mime"] == "image/jpeg"

    def test_mime_inference_png(self):
        r = parse_fileshare_announcement(self._make("map.png"))
        assert r["mime"] == "image/png"

    def test_mime_inference_mp4(self):
        r = parse_fileshare_announcement(self._make("clip.mp4"))
        assert r["mime"] == "video/mp4"

    def test_mime_inference_unknown_falls_back(self):
        r = parse_fileshare_announcement(
            self._make("data.xyz", url="http://192.168.0.1:8080/Attachment/data.xyz")
        )
        assert r is not None
        assert "octet" in r["mime"]

    def test_no_ackrequest_returns_none(self):
        ev = _event("b-f-t-a")
        det = etree.SubElement(ev, "detail")
        etree.SubElement(
            det, "fileshare", filename="x.jpg", senderCallsign="OPS", sizeInBytes="1"
        )
        # No <ackrequest> → no URL → must return None
        assert parse_fileshare_announcement(_xml(ev)) is None

    def test_no_fileshare_element_returns_none(self):
        ev = _event("b-f-t-a")
        etree.SubElement(ev, "detail")
        assert parse_fileshare_announcement(_xml(ev)) is None

    def test_wrong_type_returns_none(self):
        assert (
            parse_fileshare_announcement(
                self._make("x.jpg").replace(b"b-f-t-a", b"b-t-f")
            )
            is None
        )

    def test_malformed_returns_none(self):
        assert parse_fileshare_announcement(b"<<<bad>>>") is None


# ── parse_atak_shape ──────────────────────────────────────────────────────────


class TestParseAtakShape:

    # ── Route (b-m-r) ────────────────────────────────────────────────────────

    def _route_xml(
        self,
        waypoints: list[tuple[float, float]],
        uid: str = "ROUTE-001",
        callsign: str = "BC-1",
        title: str = "Main Supply Route",
    ) -> bytes:
        ev = _event("b-m-r", uid=uid)
        det = etree.SubElement(ev, "detail")
        etree.SubElement(det, "contact", callsign=callsign)
        rem = etree.SubElement(det, "remarks")
        rem.text = title
        for lat, lon in waypoints:
            etree.SubElement(
                det, "link", lat=str(lat), lon=str(lon), type="b-m-p-w", uid=f"WP-{lat}"
            )
        return _xml(ev)

    def test_route_parsed_as_linestring(self):
        pts = [(51.5, 4.2), (51.6, 4.3), (51.7, 4.4)]
        result = parse_atak_shape(self._route_xml(pts))
        assert result is not None
        assert result["shape_type"] == "ROUTE"
        assert result["callsign"] == "BC-1"
        assert result["title"] == "Main Supply Route"
        geo = json.loads(result["geometry_json"])
        assert geo["type"] == "LineString"
        assert len(geo["coordinates"]) == 3
        # GeoJSON is [lon, lat]
        assert abs(geo["coordinates"][0][0] - 4.2) < 1e-5
        assert abs(geo["coordinates"][0][1] - 51.5) < 1e-5

    def test_route_requires_at_least_2_waypoints(self):
        # Only 1 waypoint — shape cannot be a line, must return None
        result = parse_atak_shape(self._route_xml([(51.5, 4.2)]))
        assert result is None

    def test_route_uid_preserved(self):
        pts = [(51.5, 4.2), (51.6, 4.3)]
        result = parse_atak_shape(self._route_xml(pts, uid="MY-ROUTE-99"))
        assert result["uid"] == "MY-ROUTE-99"

    def test_u_rb_subtype_parsed_as_route(self):
        ev = _event("u-rb-a", uid="RB-ROUTE")
        det = etree.SubElement(ev, "detail")
        for lat, lon in [(50.0, 4.0), (50.1, 4.1), (50.2, 4.2)]:
            etree.SubElement(det, "link", lat=str(lat), lon=str(lon))
        result = parse_atak_shape(_xml(ev))
        assert result is not None
        assert result["shape_type"] == "ROUTE"

    # ── Drawing (u-d-*) with <shape><polyline> ───────────────────────────────

    def _polyline_xml(
        self, pts: list[tuple[float, float]], closed: bool = False
    ) -> bytes:
        ev = _event("u-d-f", uid="DRAW-001")
        det = etree.SubElement(ev, "detail")
        etree.SubElement(det, "contact", callsign="SNIPER-1")
        shape_el = etree.SubElement(det, "shape")
        tag = "polygon" if closed else "polyline"
        poly = etree.SubElement(shape_el, tag)
        for lat, lon in pts:
            etree.SubElement(poly, "vertex", lat=str(lat), lon=str(lon))
        return _xml(ev)

    def test_polyline_drawing_parsed(self):
        pts = [(52.0, 5.0), (52.1, 5.1), (52.2, 5.0)]
        result = parse_atak_shape(self._polyline_xml(pts))
        assert result is not None
        assert result["shape_type"] == "LINE"
        geo = json.loads(result["geometry_json"])
        assert geo["type"] == "LineString"
        assert len(geo["coordinates"]) == 3

    def test_polygon_drawing_parsed(self):
        pts = [(52.0, 5.0), (52.1, 5.0), (52.1, 5.1), (52.0, 5.1)]
        result = parse_atak_shape(self._polyline_xml(pts, closed=True))
        assert result is not None
        assert result["shape_type"] == "AREA"
        geo = json.loads(result["geometry_json"])
        assert geo["type"] == "Polygon"
        # Polygon ring should be closed (first == last)
        ring = geo["coordinates"][0]
        assert ring[0] == ring[-1]

    def test_polygon_ring_auto_closed(self):
        """If the ring isn't closed in the CoT, it should be closed in GeoJSON."""
        pts = [(52.0, 5.0), (52.1, 5.0), (52.1, 5.1)]
        result = parse_atak_shape(self._polyline_xml(pts, closed=True))
        assert result is not None
        geo = json.loads(result["geometry_json"])
        ring = geo["coordinates"][0]
        assert ring[0] == ring[-1], "Ring must be closed for valid GeoJSON"

    def test_non_shape_type_returns_none(self):
        assert (
            parse_atak_shape(
                self._route_xml([(51.0, 4.0), (51.1, 4.1)]).replace(
                    b"b-m-r", b"a-f-G-U-C"
                )
            )
            is None
        )

    def test_b_t_f_returns_none(self):
        ev = _event("b-t-f")
        etree.SubElement(ev, "detail")
        assert parse_atak_shape(_xml(ev)) is None

    def test_malformed_returns_none(self):
        assert parse_atak_shape(b"not xml") is None

    def test_string_input_accepted(self):
        pts = [(51.0, 4.0), (51.1, 4.1)]
        xml_str = self._route_xml(pts).decode("utf-8")
        assert parse_atak_shape(xml_str) is not None

    def test_xxe_blocked(self):
        xxe = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<event version="2.0" uid="SHP" type="b-m-r"
       time="2026-01-01T00:00:00Z" start="2026-01-01T00:00:00Z"
       stale="2026-01-01T00:01:00Z" how="h-g-i-g-o">
  <point lat="51.0" lon="4.0" hae="0" ce="9999999" le="9999999"/>
  <detail>
    <link lat="51.0" lon="4.0" type="b-m-p-w" uid="W1"/>
    <link lat="&xxe;" lon="4.1" type="b-m-p-w" uid="W2"/>
  </detail>
</event>"""
        # Must either return None or not leak /etc/passwd content
        result = parse_atak_shape(xxe)
        if result is not None:
            assert "root:" not in result.get("geometry_json", "")


# ── parse_cot — remarks extraction ───────────────────────────────────────────


class TestParseCotRemarks:

    def test_remarks_extracted(self):
        from backend.cot.cot import CotEvent

        ev = CotEvent(
            uid="ARROW.X", cot_type="a-f-G-U-C", lat=50.0, lon=4.0, callsign="X"
        )
        xml = ev.to_xml()
        # Inject <remarks> into the XML
        root = etree.fromstring(xml)
        rem = etree.SubElement(root.find("detail"), "remarks")
        rem.text = "Contact NW grid 5544"
        enriched = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
        parsed = parse_cot(enriched)
        assert parsed.remarks == "Contact NW grid 5544"

    def test_no_remarks_gives_empty_string(self):
        from backend.cot.cot import CotEvent

        ev = CotEvent(
            uid="ARROW.Y", cot_type="a-f-G-U-C", lat=50.0, lon=4.0, callsign="Y"
        )
        parsed = parse_cot(ev.to_xml())
        assert parsed.remarks == ""


# ── Cross-parser negative: each parser rejects the others' types ──────────────


class TestParserMutualExclusion:

    _TYPES = [
        ("b-a-o-opn", parse_emergency, True),
        ("b-r-f-h-s", parse_spot_report, True),
        ("b-f-t-a", parse_fileshare_announcement, True),  # needs ackrequest
        ("b-m-r", parse_atak_shape, True),
    ]

    @pytest.mark.parametrize("cot_type,fn,_", _TYPES)
    def test_position_type_rejected_by_specialised_parser(self, cot_type, fn, _):
        ev = _event("a-f-G-U-C")
        etree.SubElement(ev, "detail")
        assert fn(_xml(ev)) is None

    def test_emergency_not_parsed_as_spot(self):
        ev = _event("b-a-o-opn")
        etree.SubElement(ev, "detail")
        assert parse_spot_report(_xml(ev)) is None

    def test_spot_not_parsed_as_emergency(self):
        ev = _event("b-r-f-h-s")
        etree.SubElement(ev, "detail")
        assert parse_emergency(_xml(ev)) is None
