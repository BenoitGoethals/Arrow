"""Geographic helpers shared across all scenario modules.

Builders return ready-to-POST dicts for `POST /tactical-objects`. The backend
schema (`backend/api/schemas.py:104`) accepts the keys we set here; everything
else uses its default.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence

# ── SIDC defaults (MIL-STD-2525C, matches web/templates/opord_editor.html) ────

SIDC = {
    "LZ": "GFGPGAY---X",  # Friendly LZ point
    "DZ": "GFGPGAD---X",  # Friendly DZ point
    "PZ": "GFGPGAP---X",  # Friendly Pickup Zone point
    "BEACHHEAD": "GFGPGAB---X",
    "OBJECTIVE": "GFGPGAO---X",
    "CCP": "SFGPIME-----",
    "CP": "GFGPGPP---X",
    "BAS": "SFGPIMH-----",
    "ORP": "GFGPGAA---X",
    "ATK_AXIS": "GFGPOLAA--X",
    "DEF_AREA": "GFGPSAB---X",
    "AMBUSH": "GFGPSLA---X",
    "BOUNDARY": "GFGPLB----X",
    "PHASE_LINE": "GFGPGLP---X",
    "FLOT": "GHGPLF----X",
    # Enemy ground unit (hostile / present / unit)
    "ENEMY_INF": "SHGPUCI------",
    "ENEMY_MECH": "SHGPUCIZ-----",
    "ENEMY_ARMOR": "SHGPUCA------",
    "ENEMY_TECH": "SHGPEVU------",
    "ENEMY_HQ": "SHGPUH-------",
    "ENEMY_ADA": "SHGPUCD------",
    "ENEMY_MORTAR": "SHGPUCFM-----",
    "ENEMY_SNIPER": "SHGPUCISS----",
    "ENEMY_BOAT": "SHSPC--------",
}


# ── WGS-84 offsets ────────────────────────────────────────────────────────────


def offset_m(
    lat: float, lon: float, north_m: float, east_m: float
) -> tuple[float, float]:
    """Shift a point by (north,east) metres."""
    dlat = north_m / 111_000.0
    dlon = east_m / (111_000.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def ring(
    lat: float,
    lon: float,
    radius_m: float,
    n: int = 12,
    rotation_deg: float = 0.0,
) -> list[list[float]]:
    """Return a closed polygon ring centred at (lat,lon)."""
    pts: list[list[float]] = []
    for i in range(n):
        ang = math.radians(rotation_deg + (360.0 * i / n))
        nlat, nlon = offset_m(
            lat, lon, radius_m * math.cos(ang), radius_m * math.sin(ang)
        )
        pts.append([nlat, nlon])
    pts.append(pts[0])
    return pts


# ── Builders ──────────────────────────────────────────────────────────────────


def _common(
    affiliation: str = "FRIENDLY",
    visibility: str = "COMPANY",
    echelon: str = "",
) -> dict:
    return {
        "affiliation": affiliation,
        "visibility": visibility,
        "echelon": echelon,
    }


def poi(
    lat: float,
    lon: float,
    label: str,
    sidc: str = SIDC["CP"],
    *,
    affiliation: str = "FRIENDLY",
    echelon: str = "",
) -> dict:
    return {
        "type": "POI",
        "symbol_code": sidc,
        "latitude": lat,
        "longitude": lon,
        "notes": label,
        **_common(affiliation, echelon=echelon),
    }


def lz(lat: float, lon: float, name: str) -> dict:
    return poi(lat, lon, f"LZ {name}", SIDC["LZ"])


def dz(lat: float, lon: float, name: str) -> dict:
    return poi(lat, lon, f"DZ {name}", SIDC["DZ"])


def pz(lat: float, lon: float, name: str) -> dict:
    return poi(lat, lon, f"PZ {name}", SIDC["PZ"])


def beachhead(lat: float, lon: float, name: str, radius_m: float = 250.0) -> dict:
    return obj_area(lat, lon, f"BEACHHEAD {name}", radius_m, sidc=SIDC["BEACHHEAD"])


def objective(lat: float, lon: float, name: str, radius_m: float = 150.0) -> dict:
    return obj_area(lat, lon, f"OBJ {name}", radius_m, sidc=SIDC["OBJECTIVE"])


def obj_area(
    lat: float,
    lon: float,
    name: str,
    radius_m: float = 150.0,
    sidc: str = SIDC["OBJECTIVE"],
    *,
    affiliation: str = "FRIENDLY",
    echelon: str = "COY",
) -> dict:
    coords = ring(lat, lon, radius_m, n=12)
    return {
        "type": "OBJ_AREA",
        "symbol_code": sidc,
        "latitude": lat,
        "longitude": lon,
        "notes": name,
        "geometry": json.dumps({"type": "polygon", "coords": coords}),
        **_common(affiliation, echelon=echelon),
    }


def enemy(
    lat: float,
    lon: float,
    label: str,
    sidc: str = SIDC["ENEMY_INF"],
    *,
    echelon: str = "SEC",
) -> dict:
    return {
        "type": "ENEMY",
        "symbol_code": sidc,
        "latitude": lat,
        "longitude": lon,
        "notes": label,
        **_common("ENEMY", echelon=echelon),
    }


def line_obj(
    obj_type: str,
    pts: Sequence[Sequence[float]],
    label: str,
    sidc: str,
    *,
    affiliation: str = "FRIENDLY",
    echelon: str = "COY",
) -> dict:
    coords = [[float(p[0]), float(p[1])] for p in pts]
    centre_lat = sum(p[0] for p in coords) / len(coords)
    centre_lon = sum(p[1] for p in coords) / len(coords)
    return {
        "type": obj_type,
        "symbol_code": sidc,
        "latitude": centre_lat,
        "longitude": centre_lon,
        "notes": label,
        "geometry": json.dumps({"type": "line", "coords": coords}),
        **_common(affiliation, echelon=echelon),
    }


def flot(pts: Sequence[Sequence[float]], label: str = "FLOT") -> dict:
    return line_obj("FLOT", pts, label, SIDC["FLOT"], affiliation="ENEMY")


def boundary(pts: Sequence[Sequence[float]], label: str = "BOUNDARY") -> dict:
    return line_obj("BOUNDARY", pts, label, SIDC["BOUNDARY"])


def phase_line(pts: Sequence[Sequence[float]], label: str) -> dict:
    return line_obj("PHASE_LINE", pts, label, SIDC["PHASE_LINE"])


def atk_axis(lat: float, lon: float, label: str, *, rotation_deg: float = 0.0) -> dict:
    return {
        "type": "ATK_AXIS",
        "symbol_code": SIDC["ATK_AXIS"],
        "latitude": lat,
        "longitude": lon,
        "notes": label,
        "rotation": rotation_deg,
        **_common("FRIENDLY", echelon="COY"),
    }


def def_area(lat: float, lon: float, label: str) -> dict:
    return {
        "type": "DEF_AREA",
        "symbol_code": SIDC["DEF_AREA"],
        "latitude": lat,
        "longitude": lon,
        "notes": label,
        **_common("FRIENDLY", echelon="PL"),
    }


def ambush(lat: float, lon: float, label: str) -> dict:
    return {
        "type": "AMBUSH",
        "symbol_code": SIDC["AMBUSH"],
        "latitude": lat,
        "longitude": lon,
        "notes": label,
        **_common("FRIENDLY", echelon="SEC"),
    }
