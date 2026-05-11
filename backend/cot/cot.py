"""Cursor-on-Target (CoT) XML serialisation / deserialisation.

CoT is TAK's wire format for tactical events.  Every entity that moves through
the Arrow network is expressed as a CoT event so that ATAK clients can display
it natively and the backend can relay it to any TAK-compatible consumer.

CoT type hierarchy used here
  a-f-G-U-C          friendly  ground unit  combat
  a-f-G-U-C-O        friendly  ground unit  combat officer (BC/admin)
  a-h-G-U-C-I        hostile   ground unit  infantry
  a-h-G-U-C-A        hostile   ground unit  armour
  a-h-G-U-C-I-Z      hostile   ground unit  mechanised infantry
  a-h-G-U-C-F        hostile   ground unit  field artillery
  a-h-G-U-C-D        hostile   ground unit  air defence
  a-h-G-U-C-R        hostile   ground unit  recon
  a-h-G-E-V          hostile   ground equip vehicle (unspecified)
  a-h-G-U-C-I-S      hostile   ground unit  sniper
  a-u-G              unknown   ground
  a-n-G-I-N          neutral   ground infra point of interest

MIL-STD-2525C SIDC ↔ CoT type mapping is symmetrical (see tables below).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from lxml import etree

# ── SIDC → CoT type ──────────────────────────────────────────────────────────

SIDC_TO_COT: dict[str, str] = {
    # Friendly ground
    "SFGPUC------": "a-f-G-U-C",      # friendly ground combat (generic)
    "SFGPUCI-----": "a-f-G-U-C-I",    # friendly infantry
    "SFGPUCI----E": "a-f-G-U-C-O",    # friendly infantry / commander
    "SFGPUCA-----": "a-f-G-U-C-A",    # friendly armour
    "SFGPUCR-----": "a-f-G-U-C-R",    # friendly recon
    # Friendly air
    "SFAPMH------": "a-f-A-M-H",      # friendly helicopter
    "SFAPMFF-----": "a-f-A-M-F",      # friendly fixed-wing
    # Hostile ground
    "SHGPUCI-----": "a-h-G-U-C-I",    # hostile infantry
    "SHGPUCA-----": "a-h-G-U-C-A",    # hostile armour
    "SHGPUCIZ----": "a-h-G-U-C-I-Z",  # hostile mechanised
    "SHGPUCF-----": "a-h-G-U-C-F",    # hostile artillery
    "SHGPUCD-----": "a-h-G-U-C-D",    # hostile air-defence
    "SHGPUCR-----": "a-h-G-U-C-R",    # hostile recon
    "SHGPEV------": "a-h-G-E-V",      # hostile vehicle
    "SHGPUCIS----": "a-h-G-U-C-I-S",  # hostile sniper
    # Unknown / neutral
    "SUGPU-------": "a-u-G",           # unknown ground
    "SNGPI-------": "a-n-G-I-N",      # neutral POI
}

COT_TO_SIDC: dict[str, str] = {v: k for k, v in SIDC_TO_COT.items()}

# CoT type for a friendly operator by role
ROLE_TO_COT: dict[str, str] = {
    "OPERATOR":       "a-f-G-U-C",
    "BATTLE_CAPTAIN": "a-f-G-U-C-O",
    "ADMIN":          "a-f-G-U-C-O",
}

# Stale seconds per entity class
STALE_SECONDS = {
    "friendly": 90,
    "hostile":  300,
    "neutral":  600,
}


def role_to_cot_type(role: str) -> str:
    return ROLE_TO_COT.get(role, "a-f-G-U-C")


def sidc_to_cot_type(sidc: str) -> str:
    return SIDC_TO_COT.get(sidc.upper(), "a-u-G")


def cot_type_to_sidc(cot_type: str) -> str:
    """Convert a CoT type to MIL-STD-2525C SIDC.

    Falls back to a generic affiliation/dimension symbol when no exact match
    exists in the table (e.g. "a-h-G-U-C-I-Z" → "SHGPUCIZ----" is in the
    table, but "a-h-G-U-C-X" would fall back to "SHGPU-------").
    """
    if cot_type in COT_TO_SIDC:
        return COT_TO_SIDC[cot_type]
    parts  = cot_type.split("-")
    aff    = (parts[1] if len(parts) > 1 else "u").upper()
    dim    = (parts[2] if len(parts) > 2 else "G").upper()
    sidc_aff = {"F": "F", "H": "H", "U": "U", "N": "N"}.get(aff, "U")
    if dim == "A":
        return f"S{sidc_aff}APMF------"
    return f"S{sidc_aff}GPU-------"


# ── CotEvent dataclass ────────────────────────────────────────────────────────

@dataclass(slots=True)
class CotEvent:
    uid: str
    cot_type: str           # e.g. "a-f-G-U-C"
    lat: float
    lon: float
    hae: float = 0.0        # height above ellipsoid (metres)
    ce: float = 9999999.0   # circular error (metres)
    le: float = 9999999.0   # linear error (metres)
    callsign: str = ""
    role: str = ""
    speed: float = 0.0      # m/s
    course: float = 0.0     # degrees true north
    team: str = ""
    platform: str = "ARROW"
    time: datetime | None = None

    @property
    def affiliation(self) -> str:
        parts = self.cot_type.split("-")
        return parts[1] if len(parts) > 1 else "u"

    @property
    def stale_seconds(self) -> int:
        a = self.affiliation
        if a == "f":
            return STALE_SECONDS["friendly"]
        if a == "h":
            return STALE_SECONDS["hostile"]
        return STALE_SECONDS["neutral"]

    def to_xml(self) -> bytes:
        now   = self.time or datetime.now(timezone.utc)
        stale = now + timedelta(seconds=self.stale_seconds)
        ts    = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        ss    = stale.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

        event = etree.Element(
            "event",
            version="2.0",
            uid=self.uid,
            type=self.cot_type,
            time=ts,
            start=ts,
            stale=ss,
            how="m-g",
        )
        etree.SubElement(
            event, "point",
            lat=f"{self.lat:.7f}",
            lon=f"{self.lon:.7f}",
            hae=f"{self.hae:.1f}",
            ce=f"{self.ce:.1f}",
            le=f"{self.le:.1f}",
        )
        detail = etree.SubElement(event, "detail")
        if self.callsign:
            etree.SubElement(detail, "uid",     Droid=self.callsign)
            etree.SubElement(detail, "contact", callsign=self.callsign)
        if self.speed or self.course:
            etree.SubElement(detail, "track",
                             speed=f"{self.speed:.2f}",
                             course=f"{self.course:.1f}")
        if self.team:
            etree.SubElement(detail, "__group", role=self.role or "Team Member",
                             name=self.team)
        etree.SubElement(detail, "takv",
                         os="0", version="1.0.0",
                         device="", platform=self.platform)
        return etree.tostring(event, xml_declaration=True, encoding="UTF-8")

    def to_xml_str(self) -> str:
        return self.to_xml().decode("utf-8")


_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def parse_cot(xml: bytes | str) -> CotEvent:
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    root    = etree.fromstring(xml, _SAFE_PARSER)
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

    # Some CoT producers (notably ATAK builds in European locales) emit "51,2345"
    # instead of "51.2345". Normalise comma → dot before float() to keep parsing
    # locale-independent.
    def _f(s: str | None, default: str = "0") -> float:
        return float((s or default).replace(",", "."))

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
        platform = takv.get("platform", "ARROW") if takv is not None else "ARROW",
    )
