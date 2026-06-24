"""Coordinaten: MGRS ↔ UTM ↔ Lat/Lon.

Alle interne berekeningen gebeuren in UTM (meters, zone-lokaal). MGRS wordt
gebruikt voor invoer/uitvoer naar de gebruiker en voor uitwisseling met FO.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import mgrs
import pyproj


class MGRSError(ValueError):
    """Een MGRS-string is structureel ongeldig of niet converteerbaar."""


# Geldige MGRS-letters. Latitude-banden lopen C–X (geen A, B, I, O, Y, Z).
# 100 km-vierkantletters gebruiken A–Z behalve I en O.
_LAT_BANDS = "CDEFGHJKLMNPQRSTUVWX"
_SQUARE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_MGRS_RE = re.compile(
    r"^(?P<zone>[0-9]{1,2})(?P<band>[A-Z])(?P<square>[A-Z]{2})(?P<digits>[0-9]*)$"
)


def normalize_mgrs(s: str) -> str:
    """Canoniek formaat: spaties weg, upper-case, gestript."""
    return s.replace(" ", "").strip().upper()


def validate_mgrs(s: str) -> str:
    """Valideer een MGRS-string structureel en geef de genormaliseerde vorm terug.

    Raises MGRSError met een leesbare boodschap bij elk soort fout (leeg, fout
    formaat, ongeldige zone/band/vierkantletter, oneven aantal cijfers, te veel
    cijfers). Dit vangt de meeste tikfouten vóór de mgrs-bibliotheek.
    """
    raw = normalize_mgrs(s)
    if not raw:
        raise MGRSError("Enter an MGRS grid reference, e.g. 31UDS1234567890.")
    m = _MGRS_RE.match(raw)
    if not m:
        raise MGRSError(
            f"'{s.strip()}' is not a valid MGRS reference. "
            "Expected zone + band + 2-letter square + digits, e.g. 31UDS1234567890."
        )
    zone = int(m.group("zone"))
    if not 1 <= zone <= 60:
        raise MGRSError(f"UTM zone must be between 1 and 60 (got {zone}).")
    band = m.group("band")
    if band not in _LAT_BANDS:
        raise MGRSError(
            f"Invalid latitude band '{band}'. Bands run C–X (letters I and O are not used)."
        )
    for ch in m.group("square"):
        if ch not in _SQUARE_LETTERS:
            raise MGRSError(
                f"Invalid 100 km square letter '{ch}' (letters I and O are not used)."
            )
    digits = m.group("digits")
    if len(digits) % 2 != 0:
        raise MGRSError(
            "Grid digits must come in equal easting/northing pairs "
            f"(got {len(digits)} digit(s)). Use 4, 6, 8 or 10 digits."
        )
    if len(digits) > 10:
        raise MGRSError("Too many grid digits (maximum 10 = 1 m precision).")
    return raw


@dataclass(frozen=True)
class Position:
    """Een punt op de grond, intern UTM (meters)."""
    easting: float
    northing: float
    zone: int            # UTM zone-nummer (1-60)
    hemisphere: str      # 'N' of 'S'
    altitude_m: float = 0.0

    def to_mgrs(self, precision: int = 5) -> str:
        return utm_to_mgrs(self, precision=precision)

    def __str__(self) -> str:
        return f"{self.to_mgrs()} @ {self.altitude_m:.0f}m"


@lru_cache(maxsize=1)
def _mgrs() -> mgrs.MGRS:
    return mgrs.MGRS()


def mgrs_to_utm(mgrs_str: str, altitude_m: float = 0.0) -> Position:
    """Parse een MGRS-string (bv. '31UDS1234567890') naar UTM Position.

    Valideert eerst structureel (heldere foutmeldingen); converteert daarna via
    de mgrs-bibliotheek. Beide fasen gooien MGRSError bij ongeldige invoer.
    """
    raw = validate_mgrs(mgrs_str)
    try:
        zone, hemisphere, easting, northing = _mgrs().MGRSToUTM(raw)
    except Exception as e:
        raise MGRSError(
            f"'{mgrs_str.strip()}' is not a valid MGRS reference "
            "(the grid square does not exist in this zone)."
        ) from e
    return Position(
        easting=float(easting),
        northing=float(northing),
        zone=int(zone),
        hemisphere=hemisphere,
        altitude_m=altitude_m,
    )


def utm_to_mgrs(pos: Position, precision: int = 5) -> str:
    """UTM Position → MGRS-string. precision=5 → 1 m (10-cijferig grid)."""
    return _mgrs().UTMToMGRS(
        pos.zone, pos.hemisphere, pos.easting, pos.northing, MGRSPrecision=precision
    )


def utm_to_latlon(pos: Position) -> tuple[float, float]:
    """UTM Position → (lat, lon) in WGS84 graden."""
    transformer = pyproj.Transformer.from_crs(
        f"+proj=utm +zone={pos.zone} +{'south' if pos.hemisphere == 'S' else 'north'} +ellps=WGS84",
        "EPSG:4326",
        always_xy=True,
    )
    lon, lat = transformer.transform(pos.easting, pos.northing)
    return lat, lon


def latlon_to_utm(lat: float, lon: float, altitude_m: float = 0.0) -> Position:
    """WGS84 lat/lon (graden) → UTM Position in de juiste zone."""
    zone = int((lon + 180) / 6) + 1
    hemisphere = "N" if lat >= 0 else "S"
    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326",
        f"+proj=utm +zone={zone} +{'south' if hemisphere == 'S' else 'north'} +ellps=WGS84",
        always_xy=True,
    )
    east, north = transformer.transform(lon, lat)
    return Position(easting=east, northing=north, zone=zone, hemisphere=hemisphere, altitude_m=altitude_m)
