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

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from lxml import etree

# ── SIDC → CoT type ──────────────────────────────────────────────────────────

SIDC_TO_COT: dict[str, str] = {
    # Friendly ground
    "SFGPUC------": "a-f-G-U-C",  # friendly ground combat (generic)
    "SFGPUCI-----": "a-f-G-U-C-I",  # friendly infantry
    "SFGPUCI----E": "a-f-G-U-C-O",  # friendly infantry / commander
    "SFGPUCA-----": "a-f-G-U-C-A",  # friendly armour
    "SFGPUCR-----": "a-f-G-U-C-R",  # friendly recon
    "SFGPUCIS----": "a-f-G-U-C-S",  # friendly sniper
    # Friendly ground equipment / support
    "SFGPEW------": "a-f-G-E-W",  # friendly electronic warfare
    # Friendly air
    "SFAPMH------": "a-f-A-M-H",  # friendly helicopter
    "SFAPMFF-----": "a-f-A-M-F",  # friendly fixed-wing
    "SFAPMFQ-----": "a-f-A-M-F-Q",  # friendly UAS fixed-wing (drone)
    "SFAPMHQ-----": "a-f-A-M-H-Q",  # friendly UAS rotary-wing (drone)
    # Hostile ground
    "SHGPUCI-----": "a-h-G-U-C-I",  # hostile infantry
    "SHGPUCA-----": "a-h-G-U-C-A",  # hostile armour
    "SHGPUCIZ----": "a-h-G-U-C-I-Z",  # hostile mechanised
    "SHGPUCF-----": "a-h-G-U-C-F",  # hostile artillery
    "SHGPUCD-----": "a-h-G-U-C-D",  # hostile air-defence
    "SHGPUCR-----": "a-h-G-U-C-R",  # hostile recon
    "SHGPEV------": "a-h-G-E-V",  # hostile vehicle
    "SHGPUCIS----": "a-h-G-U-C-I-S",  # hostile sniper
    # Unknown / neutral
    "SUGPU-------": "a-u-G",  # unknown ground
    "SNGPI-------": "a-n-G-I-N",  # neutral POI
}

COT_TO_SIDC: dict[str, str] = {v: k for k, v in SIDC_TO_COT.items()}

# CoT type for a friendly operator by role
ROLE_TO_COT: dict[str, str] = {
    "OPERATOR": "a-f-G-U-C",
    "BATTLE_CAPTAIN": "a-f-G-U-C-O",
    "ADMIN": "a-f-G-U-C-O",
}

# Stale seconds per entity class
STALE_SECONDS = {
    "friendly": 90,
    "hostile": 300,
    "neutral": 600,
}


def role_to_cot_type(role: str) -> str:
    return ROLE_TO_COT.get(role, "a-f-G-U-C")


def sidc_to_cot_type(sidc: str) -> str:
    """Map a MIL-STD-2525 SIDC to a CoT type.

    Falls back to an affiliation-correct generic ground type derived from the
    SIDC's affiliation char (index 1: S/F/H/N/U/A) instead of always 'a-u-G'.
    Without this, any SIDC missing from the exact table (e.g. with an echelon
    suffix like 'SHGPUCI----E') went out as unknown → yellow in ATAK rather than
    its real affiliation (hostile → red).
    """
    s = (sidc or "").upper()
    if s in SIDC_TO_COT:
        return SIDC_TO_COT[s]
    aff = {"F": "f", "H": "h", "N": "n", "U": "u", "A": "f"}.get(
        s[1] if len(s) > 1 else "U", "u"
    )
    dim = s[2] if len(s) > 2 else "G"
    return f"a-{aff}-A" if dim == "A" else f"a-{aff}-G"


def cot_type_to_sidc(cot_type: str) -> str:
    """Convert a CoT type to MIL-STD-2525C SIDC.

    Falls back to a generic affiliation/dimension symbol when no exact match
    exists in the table (e.g. "a-h-G-U-C-I-Z" → "SHGPUCIZ----" is in the
    table, but "a-h-G-U-C-X" would fall back to "SHGPU-------").
    """
    if cot_type in COT_TO_SIDC:
        return COT_TO_SIDC[cot_type]
    parts = cot_type.split("-")
    aff = (parts[1] if len(parts) > 1 else "u").upper()
    dim = (parts[2] if len(parts) > 2 else "G").upper()
    sidc_aff = {"F": "F", "H": "H", "U": "U", "N": "N"}.get(aff, "U")
    if dim == "A":
        return f"S{sidc_aff}APMF------"
    return f"S{sidc_aff}GPU-------"


# ── CotEvent dataclass ────────────────────────────────────────────────────────


@dataclass(slots=True)
class CotEvent:
    uid: str
    cot_type: str  # e.g. "a-f-G-U-C"
    lat: float
    lon: float
    hae: float = 0.0  # height above ellipsoid (metres)
    ce: float = 9999999.0  # circular error (metres)
    le: float = 9999999.0  # linear error (metres)
    callsign: str = ""
    role: str = ""
    speed: float = 0.0  # m/s
    course: float = 0.0  # degrees true north
    team: str = ""
    platform: str = "ARROW"
    remarks: str = ""
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
        now = self.time or datetime.now(timezone.utc)
        stale = now + timedelta(seconds=self.stale_seconds)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        ss = stale.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

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
            event,
            "point",
            lat=f"{self.lat:.7f}",
            lon=f"{self.lon:.7f}",
            hae=f"{self.hae:.1f}",
            ce=f"{self.ce:.1f}",
            le=f"{self.le:.1f}",
        )
        detail = etree.SubElement(event, "detail")
        if self.callsign:
            etree.SubElement(detail, "uid", Droid=self.callsign)
            etree.SubElement(detail, "contact", callsign=self.callsign)
        if self.speed or self.course:
            etree.SubElement(
                detail, "track", speed=f"{self.speed:.2f}", course=f"{self.course:.1f}"
            )
        if self.team:
            etree.SubElement(
                detail, "__group", role=self.role or "Team Member", name=self.team
            )
        etree.SubElement(
            detail, "takv", os="0", version="1.0.0", device="", platform=self.platform
        )
        return etree.tostring(event, xml_declaration=True, encoding="UTF-8")

    def to_xml_str(self) -> str:
        return self.to_xml().decode("utf-8")


_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def parse_cot(xml: bytes | str) -> CotEvent:
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    root = etree.fromstring(xml, _SAFE_PARSER)
    point = root.find("point")
    contact = root.find("detail/contact")
    uid_el = root.find("detail/uid")
    track = root.find("detail/track")
    group = root.find("detail/__group")
    takv = root.find("detail/takv")
    remarks_el = root.find("detail/remarks")

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

    remarks = (remarks_el.text or "").strip() if remarks_el is not None else ""

    return CotEvent(
        uid=root.get("uid", ""),
        cot_type=root.get("type", "a-u-G"),
        lat=_f(point.get("lat")) if point is not None else 0.0,
        lon=_f(point.get("lon")) if point is not None else 0.0,
        hae=_f(point.get("hae")) if point is not None else 0.0,
        ce=_f(point.get("ce"), "9999999") if point is not None else 9999999.0,
        le=_f(point.get("le"), "9999999") if point is not None else 9999999.0,
        callsign=callsign,
        speed=_f(track.get("speed")) if track is not None else 0.0,
        course=_f(track.get("course")) if track is not None else 0.0,
        team=group.get("name", "") if group is not None else "",
        role=group.get("role", "") if group is not None else "",
        platform=takv.get("platform", "ARROW") if takv is not None else "ARROW",
        remarks=remarks,
    )


# ── ATAK 9-line MEDEVAC / CASEVAC ──────────────────────────────────────────────
# ATAK's MEDEVAC plugin emits a CoT event of type "b-r-f-h-c" carrying a
# <detail><_medevac_ .../></detail> element whose attributes hold the 9-line.
# We normalise it into the same line_1..line_9 payload shape the MEDCOP view and
# the report list already render.

_MEDEVAC_SECURITY = {
    "0": "No enemy troops in area",
    "1": "Possible enemy troops in area (caution)",
    "2": "Enemy troops in area (approach with caution)",
    "3": "Enemy troops in area (armed escort required)",
}
_MEDEVAC_MARK = {
    "0": "None",
    "1": "Panels",
    "2": "Pyrotechnic signal",
    "3": "Smoke signal",
    "4": "None/other",
    "5": "Other",
}


def _med_truthy(v: object) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"} if v is not None else False


def _med_count(v: object) -> int:
    try:
        return int(float(str(v)))
    except TypeError, ValueError:
        return 0


def parse_medevac(xml: bytes | str) -> dict | None:
    """Parse an ATAK 9-line MEDEVAC/CASEVAC CoT.

    Returns a normalised payload dict (``line_1..line_9`` + ``latitude`` /
    ``longitude`` + ``callsign`` + ``type``) ready to persist as a Report, or
    ``None`` if the frame is not a MEDEVAC request.
    """
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml, _SAFE_PARSER)
    except Exception:
        return None

    med = root.find("detail/_medevac_")
    cot_type = root.get("type", "")
    if med is None and not cot_type.startswith("b-r-f-h-c"):
        return None
    attrs = dict(med.attrib) if med is not None else {}

    point = root.find("point")

    def _f(s: str | None) -> float:
        return float((s or "0").replace(",", "."))

    lat = _f(point.get("lat")) if point is not None else 0.0
    lon = _f(point.get("lon")) if point is not None else 0.0

    contact = root.find("detail/contact")
    callsign = (
        (contact.get("callsign") if contact is not None else None)
        or attrs.get("title")
        or root.get("uid", "ATAK")
    )

    is_casevac = _med_truthy(attrs.get("casevac"))

    # Line 3 — precedence (patient counts)
    prec = [
        f"{lbl}: {_med_count(attrs.get(k))}"
        for k, lbl in (
            ("urgent", "Urgent"),
            ("urgent_surgical", "Urgent-Surgical"),
            ("priority", "Priority"),
            ("routine", "Routine"),
            ("convenience", "Convenience"),
        )
        if _med_count(attrs.get(k)) > 0
    ]
    # Line 4 — special equipment
    equip = [
        lbl
        for k, lbl in (
            ("equipment_none", "None"),
            ("equipment_hoist", "Hoist"),
            ("equipment_extraction", "Extraction equipment"),
            ("equipment_ventilator", "Ventilator"),
        )
        if _med_truthy(attrs.get(k))
    ]
    for extra in ("equipment_other", "equipment_detail"):
        if attrs.get(extra):
            equip.append(str(attrs[extra]))
    # Line 5 — patients by type
    l5 = []
    if _med_count(attrs.get("litter")):
        l5.append(f"{_med_count(attrs['litter'])} litter")
    if _med_count(attrs.get("ambulatory")):
        l5.append(f"{_med_count(attrs['ambulatory'])} ambulatory")
    # Line 6 — security at PZ
    sec = _MEDEVAC_SECURITY.get(
        str(attrs.get("security", "")).strip(), attrs.get("security", "")
    )
    # Line 7 — marking method
    mark = (
        attrs.get("hlz_marking")
        or attrs.get("marked_by")
        or attrs.get("markedby")
        or ""
    )
    mark = _MEDEVAC_MARK.get(str(mark).strip(), mark)
    # Line 8 — patient nationality / status
    nat = [
        lbl
        for k, lbl in (
            ("us_military", "US Military"),
            ("us_civilian", "US Civilian"),
            ("nonus_military", "Non-US Military"),
            ("nonus_civilian", "Non-US Civilian"),
            ("epw", "EPW"),
            ("child", "Child"),
        )
        if str(attrs.get(k, "")).strip() not in ("", "0", "false", "False")
    ]
    # Line 9 — terrain / NBC / obstacles
    terr = [
        lbl
        for k, lbl in (
            ("terrain_slope", "Slope"),
            ("terrain_loose", "Loose debris"),
            ("terrain_rough", "Rough terrain"),
        )
        if _med_truthy(attrs.get(k))
    ]
    for extra in ("terrain_other_detail", "obstacles"):
        if attrs.get(extra):
            terr.append(str(attrs[extra]))

    freq = attrs.get("freq") or attrs.get("frequency") or ""
    title = attrs.get("title") or ""

    return {
        "latitude": lat,
        "longitude": lon,
        "source": "ATAK",
        "callsign": callsign,
        # Arrow records every ATAK 9-liner — CASEVAC or MEDEVAC — as a MEDEVAC
        # report. The original ATAK form is preserved in `atak_form`.
        "type": "MEDEVAC",
        "atak_form": "CASEVAC" if is_casevac else "MEDEVAC",
        "line_1": f"{lat:.5f}, {lon:.5f}",
        "label_1": "Location (PZ)",
        "line_2": " / ".join(x for x in (freq, callsign) if x),
        "label_2": "Radio / Call sign",
        "line_3": ", ".join(prec),
        "label_3": "Precedence",
        "line_4": ", ".join(equip),
        "label_4": "Special equipment",
        "line_5": ", ".join(l5),
        "label_5": "Patients",
        "line_6": sec,
        "label_6": "Security at PZ",
        "line_7": mark,
        "label_7": "Marking method",
        "line_8": ", ".join(nat),
        "label_8": "Patient nationality",
        "line_9": ", ".join(terr),
        "label_9": "Terrain / NBC",
        "notes": title,
        "raw": attrs,
    }


# ── ATAK GeoChat ──────────────────────────────────────────────────────────────
# ATAK chat rides on a CoT event of type "b-t-f" carrying a <detail><__chat>
# element + a <remarks> element holding the message text. The shared broadcast
# room is "All Chat Rooms"; direct messages use the recipient's callsign as room.

ALL_CHAT_ROOMS = "All Chat Rooms"
# Arrow-originated GeoChat is tagged so we never re-ingest our own echo.
_GEOCHAT_SOURCE = "Arrow"
_GEOCHAT_UID_PREFIX = "GeoChat.ARROW."


def parse_geochat(xml: bytes | str) -> dict | None:
    """Parse an ATAK GeoChat CoT into ``{sender_callsign, text, chatroom, ...}``.

    Returns ``None`` if the frame is not a GeoChat message or carries no text.
    """
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml, _SAFE_PARSER)
    except Exception:
        return None

    chat = root.find("detail/__chat")
    cot_type = root.get("type", "")
    if chat is None and not cot_type.startswith("b-t-f"):
        return None

    remarks = root.find("detail/remarks")
    text = (remarks.text or "").strip() if remarks is not None else ""
    if not text:
        return None

    chatgrp = root.find("detail/__chat/chatgrp")
    sender_uid = (chatgrp.get("uid0", "") if chatgrp is not None else "") or root.get(
        "uid", ""
    )
    sender_cs = (
        (chat.get("senderCallsign", "") if chat is not None else "")
        or sender_uid
        or "ATAK"
    )
    chatroom = (chat.get("chatroom", "") if chat is not None else "") or ALL_CHAT_ROOMS
    room_id = (chat.get("id", "") if chat is not None else "") or chatroom
    source = remarks.get("source", "") if remarks is not None else ""

    # chatgrp lists participants as uid0, uid1, … — collect them all.
    members: list[str] = []
    if chatgrp is not None:
        for k in sorted(k for k in chatgrp.keys() if k.startswith("uid")):
            v = chatgrp.get(k)
            if v:
                members.append(v)

    return {
        "sender_callsign": sender_cs,
        "sender_uid": sender_uid,
        "text": text,
        "chatroom": chatroom,
        "room_id": room_id,
        "members": members,
        "source": source,
        "uid": root.get("uid", ""),
    }


def is_arrow_geochat(chat: dict) -> bool:
    """True if a parsed GeoChat originated from Arrow (our own echo)."""
    return str(chat.get("source", "")).startswith(_GEOCHAT_SOURCE) or str(
        chat.get("uid", "")
    ).startswith(_GEOCHAT_UID_PREFIX)


def parse_emergency(xml: bytes | str) -> dict | None:
    """Parse ATAK emergency button CoT (b-a-o-opn = active, b-a-o-can = cancel).
    Returns {uid, callsign, lat, lon, active, text} or None if not emergency.
    """
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml, _SAFE_PARSER)
    except Exception:
        return None
    cot_type = root.get("type", "")
    if not (cot_type.startswith("b-a-o-opn") or cot_type.startswith("b-a-o-can")):
        return None
    point = root.find("point")
    contact = root.find("detail/contact")
    emerg = root.find("detail/emergency")
    callsign = (contact.get("callsign", "") if contact is not None else "") or root.get(
        "uid", "ATAK"
    )
    text = (emerg.get("type", "") if emerg is not None else "") or (
        "911 Alert" if "opn" in cot_type else "Cancelled"
    )

    def _f(s):
        return float((s or "0").replace(",", "."))

    return {
        "uid": root.get("uid", ""),
        "callsign": callsign,
        "lat": _f(point.get("lat")) if point is not None else 0.0,
        "lon": _f(point.get("lon")) if point is not None else 0.0,
        "active": "opn" in cot_type,
        "text": text,
    }


def parse_spot_report(xml: bytes | str) -> dict | None:
    """Parse ATAK contact/spot reports (b-r-f-* except b-r-f-h-c MEDEVAC).
    Returns {callsign, lat, lon, cot_type, remarks, title} or None.
    """
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml, _SAFE_PARSER)
    except Exception:
        return None
    cot_type = root.get("type", "")
    if not cot_type.startswith("b-r-f-") or cot_type.startswith("b-r-f-h-c"):
        return None
    point = root.find("point")
    contact = root.find("detail/contact")
    remarks = root.find("detail/remarks")
    callsign = (contact.get("callsign", "") if contact is not None else "") or root.get(
        "uid", "ATAK"
    )
    text = (remarks.text or "").strip() if remarks is not None else ""

    def _f(s):
        return float((s or "0").replace(",", "."))

    return {
        "callsign": callsign,
        "lat": _f(point.get("lat")) if point is not None else 0.0,
        "lon": _f(point.get("lon")) if point is not None else 0.0,
        "cot_type": cot_type,
        "remarks": text,
        "title": callsign,
    }


def parse_fileshare_announcement(xml: bytes | str) -> dict | None:
    """Parse ATAK file transfer announcement (b-f-t-a).
    Returns {filename, sender_callsign, url, mime} or None.
    """
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml, _SAFE_PARSER)
    except Exception:
        return None
    if root.get("type", "") != "b-f-t-a":
        return None
    fs = root.find("detail/fileshare")
    ack = root.find("detail/ackrequest")
    if fs is None:
        return None
    filename = fs.get("filename", "") or fs.get("name", "")
    sender = fs.get("senderCallsign", "") or root.get("uid", "ATAK")
    url = ack.get("endpoint", "") if ack is not None else ""
    if not url:
        return None
    # Infer mime type from extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    MIME = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "pdf": "application/pdf",
    }
    mime = MIME.get(ext, "application/octet-stream")
    return {"filename": filename, "sender_callsign": sender, "url": url, "mime": mime}


def parse_atak_shape(xml: bytes | str) -> dict | None:
    """Parse ATAK drawn shapes: routes (b-m-r), drawings (u-d-*), areas.
    Returns {uid, cot_type, title, callsign, geometry_json} or None.
    """
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml, _SAFE_PARSER)
    except Exception:
        return None
    cot_type = root.get("type", "")
    # Match route and drawing types
    if not (
        cot_type.startswith("b-m-r")
        or cot_type.startswith("u-d-")
        or cot_type.startswith("u-rb-")
    ):
        return None
    uid = root.get("uid", "")
    contact = root.find("detail/contact")
    remarks = root.find("detail/remarks")
    callsign = (contact.get("callsign", "") if contact is not None else "") or uid
    title = (remarks.text or "").strip() if remarks is not None else callsign

    def _f(s):
        return float((s or "0").replace(",", "."))

    coords = []

    # Route: waypoints as <link lat="..." lon="..."/>
    if cot_type.startswith("b-m-r") or cot_type.startswith("u-rb-"):
        for lnk in root.findall("detail/link"):
            lat = (
                lnk.get("lat") or lnk.get("point", "").split(",")[0]
                if "," in (lnk.get("point", ""))
                else lnk.get("lat")
            )
            lon = lnk.get("lon") or (
                lnk.get("point", "").split(",")[1]
                if "," in (lnk.get("point", ""))
                else lnk.get("lon")
            )
            if lat and lon:
                coords.append([_f(lon), _f(lat)])
        if len(coords) < 2:
            return None
        geometry_json = json.dumps({"type": "LineString", "coordinates": coords})
        shape_type = "ROUTE"

    # Drawing/area: <shape><polyline/> or <shape><polygon/>
    else:
        shape_el = root.find("detail/shape")
        if shape_el is not None:
            _pl = shape_el.find("polyline")
            poly = _pl if _pl is not None else shape_el.find("polygon")
            if poly is not None:
                for v in poly.findall("vertex"):
                    lat = v.get("lat")
                    lon = v.get("lon")
                    if lat and lon:
                        coords.append([_f(lon), _f(lat)])
        # Fallback: link elements
        if not coords:
            for lnk in root.findall("detail/link"):
                lat = lnk.get("lat")
                lon = lnk.get("lon")
                if lat and lon:
                    coords.append([_f(lon), _f(lat)])
        if len(coords) < 2:
            return None
        closed = (
            shape_el is not None and shape_el.find("polygon") is not None
        ) or cot_type.startswith("u-d-r")
        if closed and coords[0] != coords[-1]:
            coords.append(coords[0])
        if closed:
            geometry_json = json.dumps({"type": "Polygon", "coordinates": [coords]})
            shape_type = "AREA"
        else:
            geometry_json = json.dumps({"type": "LineString", "coordinates": coords})
            shape_type = "LINE"

    return {
        "uid": uid,
        "cot_type": cot_type,
        "title": title or callsign,
        "callsign": callsign,
        "shape_type": shape_type,
        "geometry_json": geometry_json,
    }


def build_geochat(
    *,
    sender_callsign: str,
    text: str,
    room: str = ALL_CHAT_ROOMS,
    recipient_uid: str | None = None,
    member_uids: list[str] | None = None,
    time: datetime | None = None,
    image_url: str | None = None,
) -> bytes:
    """Build an ATAK GeoChat CoT for an Arrow chat message.

    For a multi-member room, pass ``member_uids`` (e.g. ``ARROW.<callsign>`` per
    member) — they are listed in ``<chatgrp>`` as uid1, uid2, … alongside the
    sender (uid0). For a 1:1 message pass ``recipient_uid`` instead.
    """
    now = time or datetime.now(timezone.utc)
    stale = now + timedelta(seconds=STALE_SECONDS["neutral"])
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    ss = stale.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    msg_id = str(uuid.uuid4())
    sender_uid = f"ARROW.{sender_callsign}"
    room_id = room
    uid = f"{_GEOCHAT_UID_PREFIX}{sender_callsign}.{room_id}.{msg_id}"

    event = etree.Element(
        "event",
        version="2.0",
        uid=uid,
        type="b-t-f",
        how="h-g-i-g-o",
        time=ts,
        start=ts,
        stale=ss,
    )
    etree.SubElement(
        event, "point", lat="0.0", lon="0.0", hae="0.0", ce="9999999.0", le="9999999.0"
    )
    detail = etree.SubElement(event, "detail")
    chat = etree.SubElement(
        detail,
        "__chat",
        parent="RootContactGroup",
        groupOwner="false",
        messageId=msg_id,
        chatroom=room,
        id=room_id,
        senderCallsign=sender_callsign,
    )
    chatgrp = etree.SubElement(chat, "chatgrp", uid0=sender_uid, id=room_id)
    others = [u for u in (member_uids or []) if u and u != sender_uid]
    if others:
        for i, uid_v in enumerate(others, start=1):
            chatgrp.set(f"uid{i}", uid_v)
    else:
        chatgrp.set("uid1", recipient_uid or room_id)
    etree.SubElement(detail, "link", uid=sender_uid, type="a-f-G-U-C", relation="p-p")
    rem = etree.SubElement(
        detail,
        "remarks",
        source=f"{_GEOCHAT_SOURCE}.{sender_callsign}",
        to=room_id,
        time=ts,
    )
    if image_url:
        rem.text = f"{text}\n[photo: {image_url}]"
    else:
        rem.text = text
    etree.SubElement(detail, "__serverdestination", destinations="")
    return etree.tostring(event, xml_declaration=True, encoding="UTF-8")


# ── Photo attachments (geo-pinned images) ─────────────────────────────────────
# A photo pinned to a location travels as a point CoT carrying a base64
# <detail><image> element. ATAK renders the image on the marker; Arrow stores it
# as a Photo + a POI tactical object at the same grid.

_PHOTO_UID_PREFIX = "ARROW.PHOTO."
# Cap the embedded image so a single CoT frame stays parseable by ATAK.
PHOTO_COT_MAX_BYTES = 512 * 1024


def parse_cot_image(xml: bytes | str) -> dict | None:
    """Parse a point CoT with an embedded base64 ``<image>`` attachment.

    Returns ``{lat, lon, callsign, mime, image_bytes, caption, uid}`` or ``None``.
    """
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml, _SAFE_PARSER)
    except Exception:
        return None

    image = root.find("detail/image")
    b64 = (image.text or "").strip() if image is not None else ""
    if not b64:
        return None
    try:
        data = base64.b64decode(b64)
    except Exception:
        return None
    if not data:
        return None

    point = root.find("point")
    contact = root.find("detail/contact")
    remarks = root.find("detail/remarks")

    def _f(s: str | None) -> float:
        return float((s or "0").replace(",", "."))

    callsign = (contact.get("callsign") if contact is not None else None) or root.get(
        "uid", "ATAK"
    )
    return {
        "lat": _f(point.get("lat")) if point is not None else 0.0,
        "lon": _f(point.get("lon")) if point is not None else 0.0,
        "callsign": callsign,
        "mime": image.get("mime") or image.get("type") or "image/jpeg",
        "image_bytes": data,
        "caption": (remarks.text or "").strip() if remarks is not None else "",
        "uid": root.get("uid", ""),
    }


def is_arrow_photo(img: dict) -> bool:
    """True if a parsed image CoT originated from Arrow (our own echo)."""
    return str(img.get("uid", "")).startswith(_PHOTO_UID_PREFIX)


def build_image_cot(
    *,
    lat: float,
    lon: float,
    callsign: str,
    image_bytes: bytes,
    mime: str = "image/jpeg",
    caption: str = "",
    cot_type: str = "b-m-p-s-p-i",  # sensor point of interest (image marker)
    time: datetime | None = None,
) -> bytes:
    """Build a point CoT with an embedded base64 ``<image>`` for ATAK."""
    now = time or datetime.now(timezone.utc)
    stale = now + timedelta(seconds=STALE_SECONDS["neutral"])
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    ss = stale.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    uid = f"{_PHOTO_UID_PREFIX}{callsign}.{uuid.uuid4().hex[:8]}"

    event = etree.Element(
        "event",
        version="2.0",
        uid=uid,
        type=cot_type,
        how="h-e",
        time=ts,
        start=ts,
        stale=ss,
    )
    etree.SubElement(
        event,
        "point",
        lat=f"{lat:.7f}",
        lon=f"{lon:.7f}",
        hae="0.0",
        ce="9999999.0",
        le="9999999.0",
    )
    detail = etree.SubElement(event, "detail")
    etree.SubElement(detail, "contact", callsign=callsign)
    img = etree.SubElement(detail, "image", type=mime, mime=mime)
    img.text = base64.b64encode(image_bytes).decode("ascii")
    if caption:
        etree.SubElement(detail, "remarks").text = caption
    return etree.tostring(event, xml_declaration=True, encoding="UTF-8")


# ── TAK file-share (binary attachment transfer) ───────────────────────────────
# ATAK transfers files as binary over HTTP and announces them with a `b-f-t-r`
# CoT carrying a <fileshare> detail. The receiver downloads `senderUrl` (a
# /Marti/sync/content?hash=… URL) and stores the binary — no base64 on the wire.

_FILESHARE_UID_PREFIX = "ARROW.FSHARE."


def build_fileshare(
    *,
    filename: str,
    sha256: str,
    size_bytes: int,
    url: str,
    sender_callsign: str,
    lat: float = 0.0,
    lon: float = 0.0,
    caption: str = "",
    time: datetime | None = None,
) -> bytes:
    """Build a TAK `b-f-t-r` file-transfer CoT pointing at a binary download URL."""
    now = time or datetime.now(timezone.utc)
    stale = now + timedelta(seconds=STALE_SECONDS["neutral"])
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    ss = stale.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    uid = f"{_FILESHARE_UID_PREFIX}{sha256[:16]}"

    event = etree.Element(
        "event",
        version="2.0",
        uid=uid,
        type="b-f-t-r",
        how="h-e",
        time=ts,
        start=ts,
        stale=ss,
    )
    etree.SubElement(
        event,
        "point",
        lat=f"{lat:.7f}",
        lon=f"{lon:.7f}",
        hae="0.0",
        ce="9999999.0",
        le="9999999.0",
    )
    detail = etree.SubElement(event, "detail")
    etree.SubElement(
        detail,
        "fileshare",
        filename=filename,
        name=filename,
        senderUrl=url,
        sizeInBytes=str(size_bytes),
        sha256=sha256,
        senderUid=f"ARROW.{sender_callsign}",
        senderCallsign=sender_callsign,
    )
    etree.SubElement(detail, "ackrequest", uid=uid, ackrequested="true", tag=filename)
    if caption:
        etree.SubElement(detail, "remarks").text = caption
    return etree.tostring(event, xml_declaration=True, encoding="UTF-8")


def is_arrow_fileshare(fs: dict) -> bool:
    return str(fs.get("uid", "")).startswith(_FILESHARE_UID_PREFIX)


def parse_fileshare(xml: bytes | str) -> dict | None:
    """Parse a TAK `b-f-t-r` file-share CoT. Returns the file metadata or None."""
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        root = etree.fromstring(xml, _SAFE_PARSER)
    except Exception:
        return None
    fs = root.find("detail/fileshare")
    cot_type = root.get("type", "")
    if fs is None and not cot_type.startswith("b-f-t-r"):
        return None
    if fs is None:
        return None

    point = root.find("point")

    def _f(s: str | None) -> float:
        return float((s or "0").replace(",", "."))

    try:
        size = int(fs.get("sizeInBytes") or "0")
    except ValueError:
        size = 0
    return {
        "uid": root.get("uid", ""),
        "filename": fs.get("filename") or fs.get("name") or "file",
        "sha256": fs.get("sha256", ""),
        "size_bytes": size,
        "url": fs.get("senderUrl", ""),
        "sender_callsign": fs.get("senderCallsign", "") or "ATAK",
        "lat": _f(point.get("lat")) if point is not None else 0.0,
        "lon": _f(point.get("lon")) if point is not None else 0.0,
    }
