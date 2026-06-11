"""CoT XML stream utilities — framing, parsing, and building CoT events for TCP.

TAK uses raw XML over TCP with no length prefix.  We split on ``</event>`` to
find message boundaries and keep a per-connection byte buffer for partial reads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from lxml import etree

log = logging.getLogger("tak_bridge.cot")

_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)
_END_TAG     = b"</event>"


# ── CoT event dataclass (standalone — mirrors backend.cot.cot.CotEvent) ──────

@dataclass
class CotEvent:
    uid:      str
    cot_type: str
    lat:      float
    lon:      float
    hae:      float  = 0.0
    ce:       float  = 9999999.0
    le:       float  = 9999999.0
    callsign: str    = ""
    role:     str    = ""
    team:     str    = ""
    speed:    float  = 0.0
    course:   float  = 0.0
    platform: str    = "ARROW-BRIDGE"
    stale_s:  int    = 90

    # Parsed extras (not serialised)
    raw_xml:  bytes  = field(default=b"", repr=False)

    @property
    def affiliation(self) -> str:
        parts = self.cot_type.split("-")
        return parts[1] if len(parts) > 1 else "u"

    def to_xml(self) -> bytes:
        now   = datetime.now(timezone.utc)
        stale = now + timedelta(seconds=self.stale_s)
        ts    = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        ss    = stale.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

        ev = etree.Element(
            "event", version="2.0", uid=self.uid,
            type=self.cot_type, time=ts, start=ts, stale=ss, how="m-g",
        )
        etree.SubElement(
            ev, "point",
            lat=f"{self.lat:.7f}", lon=f"{self.lon:.7f}",
            hae=f"{self.hae:.1f}", ce=f"{self.ce:.1f}", le=f"{self.le:.1f}",
        )
        det = etree.SubElement(ev, "detail")
        if self.callsign:
            etree.SubElement(det, "uid",     Droid=self.callsign)
            etree.SubElement(det, "contact", callsign=self.callsign)
        if self.speed or self.course:
            etree.SubElement(det, "track",
                             speed=f"{self.speed:.2f}",
                             course=f"{self.course:.1f}")
        if self.team:
            etree.SubElement(det, "__group",
                             role=self.role or "Team Member", name=self.team)
        etree.SubElement(det, "takv", os="0", version="4.10",
                         device="", platform=self.platform)
        return etree.tostring(ev, xml_declaration=True, encoding="UTF-8")


def _f(val: str | None, default: str = "0") -> float:
    return float((val or default).replace(",", "."))


def parse_cot(xml_bytes: bytes) -> CotEvent | None:
    """Parse a single CoT XML event.  Returns None on any parse error."""
    try:
        root    = etree.fromstring(xml_bytes, _SAFE_PARSER)
        point   = root.find("point")
        contact = root.find("detail/contact")
        uid_el  = root.find("detail/uid")
        track   = root.find("detail/track")
        group   = root.find("detail/__group")
        takv    = root.find("detail/takv")

        callsign = ""
        if contact is not None:
            callsign = contact.get("callsign", "")
        elif uid_el is not None:
            callsign = uid_el.get("Droid", "")

        return CotEvent(
            uid      = root.get("uid", ""),
            cot_type = root.get("type", "a-u-G"),
            lat      = _f(point.get("lat")) if point is not None else 0.0,
            lon      = _f(point.get("lon")) if point is not None else 0.0,
            hae      = _f(point.get("hae")) if point is not None else 0.0,
            ce       = _f(point.get("ce"),  "9999999") if point is not None else 9999999.0,
            le       = _f(point.get("le"),  "9999999") if point is not None else 9999999.0,
            callsign = callsign,
            speed    = _f(track.get("speed"))  if track is not None else 0.0,
            course   = _f(track.get("course")) if track is not None else 0.0,
            team     = group.get("name",  "") if group is not None else "",
            role     = group.get("role",  "") if group is not None else "",
            platform = takv.get("platform", "ATAK") if takv is not None else "ATAK",
            stale_s  = 90 if (root.get("type", "").startswith("a-f")) else 300,
            raw_xml  = xml_bytes,
        )
    except Exception as exc:
        log.debug("CoT parse error: %s — xml=%s…", exc, xml_bytes[:80])
        return None


class CotFrameBuffer:
    """Per-connection byte buffer that yields complete CoT XML messages."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        """Append raw bytes and return a list of complete CoT XML frames."""
        self._buf += data
        frames: list[bytes] = []
        while True:
            idx = self._buf.find(_END_TAG)
            if idx == -1:
                break
            end  = idx + len(_END_TAG)
            raw  = bytes(self._buf[:end])
            self._buf = self._buf[end:]
            # Strip leading garbage before the XML declaration / <event tag
            start = raw.find(b"<event")
            if start == -1:
                start = raw.find(b"<?xml")
            if start > 0:
                raw = raw[start:]
            if raw:
                frames.append(raw)
        return frames


def operator_to_cot(op: dict) -> CotEvent:
    """Convert an Arrow /hierarchy operator dict to a CotEvent."""
    role_map = {
        "BATTLE_CAPTAIN": "a-f-G-U-C-O",
        "ADMIN":          "a-f-G-U-C-O",
        "FO":             "a-f-G-F-C",
        "MED":            "a-f-G-U-M",
        "INTEL":          "a-f-G-U-C-I",
        "OPS":            "a-f-G-U-C",
    }
    cot_type = role_map.get(op.get("role", ""), "a-f-G-U-C")
    return CotEvent(
        uid      = f"ARROW.{op['callsign']}",
        cot_type = cot_type,
        lat      = op.get("latitude")  or 0.0,
        lon      = op.get("longitude") or 0.0,
        callsign = op["callsign"],
        role     = op.get("role", ""),
        stale_s  = 120,
        platform = "ARROW",
    )


def tacobj_to_cot(obj: dict) -> CotEvent | None:
    """Convert an Arrow tactical object to a CotEvent."""
    sidc = obj.get("symbol_code", "")
    affil = obj.get("affiliation", "FRIENDLY").upper()

    # Map affiliation to CoT type
    aff_map = {"FRIENDLY": "f", "ENEMY": "h", "NEUTRAL": "n", "UNKNOWN": "u"}
    aff = aff_map.get(affil, "u")

    # Simple SIDC → CoT type mapping
    sidc_cot: dict[str, str] = {
        "SHGPUCI-----": "a-h-G-U-C-I",
        "SHGPUCA-----": "a-h-G-U-C-A",
        "SHGPUCIZ----": "a-h-G-U-C-I-Z",
        "SHGPEVAT----": "a-h-G-E-V",
        "SHGPUCFW----": "a-h-G-U-C-F",
        "SHGPUCDS----": "a-h-G-U-C-D",
        "SHGPUCRVO---": "a-h-G-U-C-R",
        "SFGPUCEV----": "a-f-G-E-V",
        "SFGPUCV-----": "a-f-G-E-V",
        "SFGPMFF-----": "a-f-A-M-H",
        "SFGPIME-----": "a-f-G-U-M",
    }
    cot_type = sidc_cot.get(sidc[:12].upper() if sidc else "",
                            f"a-{aff}-G")

    lat = obj.get("latitude")
    lon = obj.get("longitude")
    if not lat or not lon:
        return None

    uid = f"ARROW.tacobj.{obj['id']}"
    return CotEvent(
        uid      = uid,
        cot_type = cot_type,
        lat      = float(lat),
        lon      = float(lon),
        callsign = obj.get("notes", uid)[:40],
        stale_s  = 600,
        platform = "ARROW",
    )
