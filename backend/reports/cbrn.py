"""NATO CBRN message parser (STANAG 2103 / ATP-45 — CBRN 1..6).

Parses the canonical line-item message format used for CBRN reporting:

    MSGID/CBRN 1 OBS/UNIT//
    ALFA/STRIKE SERIAL/A001//
    BRAVO/POSITION OF OBSERVER/LATLON:50.85,4.35//
    ...

The parser is permissive: it splits on `//` segment terminators and `/` field
separators, uppercases the leading line code (ALFA, BRAVO, ...), and pulls out
the values it knows how to interpret. Unknown lines are kept verbatim under
``payload["lines"][<code>]`` so nothing is lost.
"""

from __future__ import annotations

import re
from typing import Any

# Line-code phonetic alphabet → semantic role (ATP-45 / STANAG 2103).
# Different CBRN message types reuse codes for different purposes; we capture
# the common cases and store everything else by code.
_LINE_CODES = {
    "ALFA":     "strike_serial",
    "BRAVO":    "observer_position",
    "CHARLIE":  "direction_observer_to_event",
    "DELTA":    "dtg_event",
    "ECHO":     "illumination",
    "FOXTROT":  "event_position",
    "GOLF":     "delivery",
    "HOTEL":    "agent_type",        # C / B / R / N (and details)
    "INDIA":    "terrain_weather",
    "JULIETT":  "downwind_direction",
    "KILO":     "downwind_speed",
    "LIMA":    "stability_category",
    "MIKE":     "release_height",
    "NOVEMBER": "yield",             # nuclear (kT)
    "OSCAR":    "predicted_zone_i",
    "PAPA":     "predicted_zone_ii",
    "QUEBEC":   "location_of_reading",
    "ROMEO":    "dose_rate",
    "SIERRA":   "dtg_reading",
    "TANGO":    "type_of_attack",
    "UNIFORM":  "actual_contour",
    "VICTOR":   "wind_speed_surface",
    "WHISKEY":  "wind_direction_surface",
    "XRAY":     "remarks",
    "YANKEE":   "downwind_hazard",
    "ZULU":     "weather_actual",
}

_AGENT_TO_CATEGORY = {
    "CHEM": "C", "CHEMICAL": "C",
    "BIO":  "B", "BIOLOGICAL": "B",
    "RAD":  "R", "RADIOLOGICAL": "R",
    "NUC":  "N", "NUCLEAR": "N",
}

_LATLON_RE = re.compile(r"LATLON\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", re.I)
_MGRS_RE   = re.compile(r"MGRS\s*[:=]\s*([0-9]{1,2}[A-Z][A-Z]{2}\s*[0-9]{4,10})", re.I)
_NUM_RE    = re.compile(r"-?\d+(?:\.\d+)?")


class CbrnParseError(ValueError):
    """Raised when a CBRN message cannot be parsed."""


def parse_cbrn(text: str) -> dict[str, Any]:
    """Parse a NATO CBRN 1..6 text message into a structured payload.

    Returns a dict with at least:
        msg_type:   "CBRN_1".."CBRN_6"
        agent_category: "C" | "B" | "R" | "N" | None
        latitude / longitude:  event location (best-effort)
        wind_direction:   ° meteorological (direction the wind is FROM)
        wind_speed:       km/h
        zone_inner_m:     Zone I radius (immediate hazard)
        zone_downwind_m:  Zone II downwind distance
        zone_downwind_angle_deg:  half-angle of the downwind sector
        lines:            { CODE: raw value, ... } — raw fields by line code
        raw:              original text
    """
    if not text or not text.strip():
        raise CbrnParseError("empty CBRN message")

    payload: dict[str, Any] = {"raw": text, "lines": {}}

    # 1) Determine CBRN message number from MSGID/... line if present
    msg_num = _extract_msg_num(text)
    payload["msg_type"] = f"CBRN_{msg_num}" if msg_num else "CBRN_1"

    # 2) Walk all line-coded segments
    # Segments are terminated by `//`. Within a segment the first field is the
    # line code (e.g. ALFA), and the remaining `/`-separated fields are values.
    for raw_seg in text.split("//"):
        seg = raw_seg.strip()
        if not seg:
            continue
        parts = [p.strip() for p in seg.split("/")]
        code = parts[0].upper()
        if code not in _LINE_CODES:
            continue
        value = "/".join(parts[1:]).strip()
        payload["lines"][code] = value

    # 3) Best-effort extraction of structured fields
    # Location: prefer FOXTROT (event), fall back to BRAVO (observer)
    for code in ("FOXTROT", "BRAVO", "QUEBEC"):
        if code in payload["lines"]:
            lat, lon = _extract_latlon(payload["lines"][code])
            if lat is not None:
                payload["latitude"]  = lat
                payload["longitude"] = lon
                break

    # Agent category: C/B/R/N
    hotel = payload["lines"].get("HOTEL", "") + " " + payload["lines"].get("TANGO", "")
    payload["agent_category"] = _agent_category(hotel)
    payload["agent"] = payload["lines"].get("HOTEL", "").strip()

    # Wind / met
    payload["wind_direction"] = _first_number(payload["lines"].get("WHISKEY")
                                              or payload["lines"].get("JULIETT"))
    payload["wind_speed"]     = _first_number(payload["lines"].get("VICTOR")
                                              or payload["lines"].get("KILO"))

    # Zone parameters — explicit if given (OSCAR/PAPA), otherwise sensible defaults
    zone_inner    = _first_number(payload["lines"].get("OSCAR"))
    zone_downwind = _first_number(payload["lines"].get("PAPA")
                                  or payload["lines"].get("YANKEE"))
    payload["zone_inner_m"]    = int(zone_inner * 1000) if (zone_inner and zone_inner < 50) else int(zone_inner or _default_inner(payload))
    payload["zone_downwind_m"] = int(zone_downwind * 1000) if (zone_downwind and zone_downwind < 100) else int(zone_downwind or _default_downwind(payload))
    payload["zone_downwind_angle_deg"] = 30  # ATP-45 simplified: ±30° sector

    # DTG of event
    payload["dtg"] = payload["lines"].get("DELTA") or payload["lines"].get("SIERRA") or ""
    payload["serial"] = payload["lines"].get("ALFA", "")
    payload["delivery"] = payload["lines"].get("GOLF", "")

    return payload


# ─── helpers ────────────────────────────────────────────────────────────

_MSGID_RE = re.compile(r"MSGID\s*/\s*CBRN\s*([1-6])\b", re.I)


def _extract_msg_num(text: str) -> int | None:
    m = _MSGID_RE.search(text)
    return int(m.group(1)) if m else None


def _extract_latlon(s: str) -> tuple[float | None, float | None]:
    m = _LATLON_RE.search(s)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def _agent_category(s: str) -> str | None:
    su = s.upper()
    for kw, cat in _AGENT_TO_CATEGORY.items():
        if kw in su:
            return cat
    # Single-letter hint
    for c in ("C", "B", "R", "N"):
        if re.search(rf"\b{c}\b", su):
            return c
    return None


def _first_number(s: str | None) -> float | None:
    if not s:
        return None
    m = _NUM_RE.search(s)
    return float(m.group(0)) if m else None


def _default_inner(payload: dict) -> int:
    """Default Zone I radius (m) by agent category."""
    return {
        "C": 1000,   # 1 km
        "B": 2000,
        "R": 500,
        "N": 3000,   # severe damage radius — placeholder
    }.get(payload.get("agent_category") or "", 1000)


def _default_downwind(payload: dict) -> int:
    """Default Zone II downwind distance (m) by agent category."""
    return {
        "C": 10000,
        "B": 20000,
        "R": 5000,
        "N": 30000,
    }.get(payload.get("agent_category") or "", 10000)
