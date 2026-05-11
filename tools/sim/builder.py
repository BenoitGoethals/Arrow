"""CoT XML Builder — assembles a TAK-compatible CoT XML string from a CotEntry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lxml import etree

from .domain import CotEntry, STALE


class CotXmlBuilder:
    """Builds a TAK-compatible CoT XML string from a ``CotEntry`` (Builder pattern).

    Stateless — safe to share across threads.
    """

    def build(self, entry: CotEntry) -> str:
        stale_secs = STALE.get(entry.affiliation, 120)
        now   = datetime.now(timezone.utc)
        stale = now + timedelta(seconds=stale_secs)

        def _fmt(d: datetime) -> str:
            return d.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

        evt = etree.Element(
            "event", version="2.0",
            uid=entry.uid, type=entry.cot_type,
            time=_fmt(now), start=_fmt(now), stale=_fmt(stale),
            how="m-g",
        )
        etree.SubElement(
            evt, "point",
            lat=f"{entry.lat:.7f}", lon=f"{entry.lon:.7f}",
            hae=f"{entry.hae:.1f}", ce="9999999.0", le="9999999.0",
        )
        detail = etree.SubElement(evt, "detail")
        if entry.callsign:
            etree.SubElement(detail, "uid",     Droid=entry.callsign)
            etree.SubElement(detail, "contact", callsign=entry.callsign)
        if entry.speed or entry.course:
            etree.SubElement(detail, "track",
                             speed=f"{entry.speed:.2f}",
                             course=f"{entry.course:.1f}")
        if entry.team:
            etree.SubElement(detail, "__group",
                             role=entry.role or "Team Member",
                             name=entry.team)
        etree.SubElement(detail, "takv",
                         os="0", version="1.0.0", device="", platform="SIM")
        return etree.tostring(evt, xml_declaration=True,
                              encoding="UTF-8", pretty_print=True).decode()
