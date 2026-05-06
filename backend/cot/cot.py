"""Minimal Cursor-on-Target (CoT) XML serialisation.

CoT messages are TAK's wire format for tactical events. This is a lean encoder/decoder
sufficient for interoperability with ATAK clients.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from lxml import etree


@dataclass(slots=True)
class CotEvent:
    uid: str
    type: str  # e.g. "a-f-G-U-C" (friendly ground unit combat)
    lat: float
    lon: float
    hae: float = 0.0  # height above ellipsoid
    ce: float = 9999999.0  # circular error
    le: float = 9999999.0  # linear error
    callsign: str = ""
    stale_seconds: int = 60
    time: datetime | None = None

    def to_xml(self) -> bytes:
        now = self.time or datetime.now(timezone.utc)
        stale = now + timedelta(seconds=self.stale_seconds)

        event = etree.Element(
            "event",
            version="2.0",
            uid=self.uid,
            type=self.type,
            time=now.isoformat(),
            start=now.isoformat(),
            stale=stale.isoformat(),
            how="m-g",
        )
        etree.SubElement(
            event,
            "point",
            lat=f"{self.lat:.7f}",
            lon=f"{self.lon:.7f}",
            hae=f"{self.hae}",
            ce=f"{self.ce}",
            le=f"{self.le}",
        )
        if self.callsign:
            detail = etree.SubElement(event, "detail")
            etree.SubElement(detail, "contact", callsign=self.callsign)

        return etree.tostring(event, xml_declaration=True, encoding="UTF-8")


def parse_cot(xml: bytes) -> CotEvent:
    root = etree.fromstring(xml)
    point = root.find("point")
    contact = root.find("detail/contact")
    return CotEvent(
        uid=root.get("uid", ""),
        type=root.get("type", ""),
        lat=float(point.get("lat", "0")) if point is not None else 0.0,
        lon=float(point.get("lon", "0")) if point is not None else 0.0,
        hae=float(point.get("hae", "0")) if point is not None else 0.0,
        callsign=contact.get("callsign", "") if contact is not None else "",
    )
