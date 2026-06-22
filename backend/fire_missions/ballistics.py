"""L16/L16A1/L16A2 81 mm mortar ballistic solver.

Educational/simulation-grade model. We do not embed the classified Tabular Firing
Tables (TFT). Instead we use the published muzzle velocities and maximum ranges
per charge and a parametric high-angle trajectory model with a drag scale factor
fitted so each charge's predicted maximum range matches the published value.

For each call (solve_l16_81mm) we return:
    charge      : 1..9
    qe_mils     : quadrant elevation (mils)
    defl_mils   : deflection from a reference azimuth (mils)
    tof_s       : time of flight (s)
    mv_ms       : muzzle velocity (m/s)
    range_m     : computed slant range used for the solution

The sheaf builder (build_sheaf) produces impact points for POINT / LINE / ZONE
target patterns and distributes them across 1..4 guns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# ── Charge table ─────────────────────────────────────────────────────────────
# (charge, muzzle velocity m/s, max range m).  Drag scale factor is derived per
# charge so vacuum-projectile max range ≈ published max range.
_CHARGES: list[tuple[int, float, float]] = [
    (1, 73, 520),
    (2, 110, 1200),
    (3, 140, 1900),
    (4, 165, 2700),
    (5, 195, 3400),
    (6, 220, 4100),
    (7, 245, 4700),
    (8, 270, 5300),
    (9, 297, 5650),
]
_GRAVITY = 9.80665
_MILS_PER_RAD = 3200.0 / math.pi  # 6400 mils == 2π rad

# Per-charge drag scale (R_real / R_vacuum_max).  Derived once at import.
_DRAG_SCALE: dict[int, float] = {
    c: r_max / (v * v / _GRAVITY) for c, v, r_max in _CHARGES
}

# Min ranges per charge (rough — high-angle solution at QE≈1480 mils).
# Well below this and you must drop a charge.
_MIN_RANGE: dict[int, float] = {
    1: 80,
    2: 200,
    3: 350,
    4: 500,
    5: 700,
    6: 900,
    7: 1100,
    8: 1300,
    9: 1500,
}

ValidPattern = Literal["POINT", "LINE", "ZONE"]
ValidAmmo = Literal["HE", "ILLUM", "SMOKE", "WP"]


@dataclass(frozen=True)
class FiringSolution:
    charge: int
    qe_mils: int
    defl_mils: int
    tof_s: float
    mv_ms: float
    range_m: float
    azimuth_mils: int
    impact_lat: float
    impact_lon: float
    error: str | None = None


# ── Geo helpers ──────────────────────────────────────────────────────────────


def _bearing_range_m(
    gun_lat: float, gun_lon: float, tgt_lat: float, tgt_lon: float
) -> tuple[float, float]:
    """Return (range_m, azimuth_mils_grid). Flat-earth ≤ ~50 km is fine."""
    dlat = (tgt_lat - gun_lat) * 111_000.0
    dlon = (
        (tgt_lon - gun_lon)
        * 111_000.0
        * math.cos(math.radians((gun_lat + tgt_lat) / 2))
    )
    rng = math.hypot(dlat, dlon)
    az_rad = math.atan2(dlon, dlat)
    if az_rad < 0:
        az_rad += 2 * math.pi
    return rng, az_rad * _MILS_PER_RAD


def _offset_by(
    lat: float, lon: float, az_mils: float, dist_m: float
) -> tuple[float, float]:
    az_rad = az_mils / _MILS_PER_RAD
    dlat = dist_m * math.cos(az_rad) / 111_000.0
    dlon = dist_m * math.sin(az_rad) / (111_000.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


# ── Core solver ──────────────────────────────────────────────────────────────


def _pick_charge(range_m: float, charge_override: int | None = None) -> int | None:
    if charge_override is not None and 1 <= charge_override <= 9:
        return charge_override
    for c, _v, r_max in _CHARGES:
        if range_m <= r_max * 0.95:
            return c
    return None  # out of range


def _solve_qe_high(range_m: float, mv: float, drag: float) -> float | None:
    """High-angle quadrant elevation in mils, or None if unreachable."""
    # R = drag * V² * sin(2θ) / g  →  sin(2θ) = R·g / (drag·V²)
    s = range_m * _GRAVITY / (drag * mv * mv)
    if s > 0.999:  # outside achievable arc
        return None
    two_theta = math.asin(min(1.0, s))
    # High-angle solution: θ = π/2 - two_theta/2  (above 800 mils / 45°)
    theta = math.pi / 2 - two_theta / 2
    return theta * _MILS_PER_RAD


def _site_correction_mils(range_m: float, vi_m: float) -> float:
    """Geometric site correction (ignoring complementary site)."""
    if range_m <= 0:
        return 0.0
    return math.atan2(vi_m, range_m) * _MILS_PER_RAD


def solve_l16_81mm(
    *,
    gun_lat: float,
    gun_lon: float,
    gun_alt_m: float,
    tgt_lat: float,
    tgt_lon: float,
    tgt_alt_m: float,
    reference_az_mils: float = 0.0,
    charge_override: int | None = None,
) -> FiringSolution:
    """Compute a firing solution for one gun on one target point."""
    rng_m, az_mils = _bearing_range_m(gun_lat, gun_lon, tgt_lat, tgt_lon)
    charge = _pick_charge(rng_m, charge_override)
    if charge is None:
        return FiringSolution(
            charge=0,
            qe_mils=0,
            defl_mils=0,
            tof_s=0.0,
            mv_ms=0.0,
            range_m=rng_m,
            azimuth_mils=int(az_mils),
            impact_lat=tgt_lat,
            impact_lon=tgt_lon,
            error=f"target {rng_m:.0f} m exceeds max range (5650 m)",
        )
    if rng_m < _MIN_RANGE.get(charge, 0):
        return FiringSolution(
            charge=charge,
            qe_mils=0,
            defl_mils=0,
            tof_s=0.0,
            mv_ms=0.0,
            range_m=rng_m,
            azimuth_mils=int(az_mils),
            impact_lat=tgt_lat,
            impact_lon=tgt_lon,
            error=f"target {rng_m:.0f} m below charge {charge} minimum "
            f"({_MIN_RANGE[charge]} m) — drop a charge",
        )

    _, mv, _ = _CHARGES[charge - 1]
    drag = _DRAG_SCALE[charge]

    qe = _solve_qe_high(rng_m, mv, drag)
    if qe is None:
        return FiringSolution(
            charge=charge,
            qe_mils=0,
            defl_mils=0,
            tof_s=0.0,
            mv_ms=mv,
            range_m=rng_m,
            azimuth_mils=int(az_mils),
            impact_lat=tgt_lat,
            impact_lon=tgt_lon,
            error=f"unreachable at charge {charge}",
        )

    qe += _site_correction_mils(rng_m, tgt_alt_m - gun_alt_m)

    # TOF (vacuum approximation with the same drag scale)
    theta = qe / _MILS_PER_RAD
    tof = 2.0 * mv * math.sin(theta) / _GRAVITY * math.sqrt(drag)

    # Deflection — relative to the gun's reference azimuth, in mils.
    defl = (az_mils - reference_az_mils) % 6400

    return FiringSolution(
        charge=charge,
        qe_mils=int(round(qe)),
        defl_mils=int(round(defl)),
        tof_s=round(tof, 1),
        mv_ms=mv,
        range_m=round(rng_m, 1),
        azimuth_mils=int(round(az_mils)),
        impact_lat=tgt_lat,
        impact_lon=tgt_lon,
    )


# ── Sheaf / pattern builder ──────────────────────────────────────────────────


def build_sheaf(
    *,
    pattern: ValidPattern,
    target: dict,
    gun_count: int,
    rounds_per_gun: int,
) -> list[tuple[float, float]]:
    """Return a list of impact lat/lon points covering the target shape.

    target keys:
      POINT: {"latitude", "longitude"}
      LINE : {"start": {"latitude", "longitude"},
              "end":   {"latitude", "longitude"}}
      ZONE : {"center": {"latitude", "longitude"},
              "width_m": float, "height_m": float, "rotation_mils": float (optional)}
    """
    gun_count = max(1, min(4, int(gun_count)))
    rounds_per_gun = max(1, int(rounds_per_gun))
    total = gun_count * rounds_per_gun

    if pattern == "POINT":
        return [(float(target["latitude"]), float(target["longitude"]))] * total

    if pattern == "LINE":
        s = target["start"]
        e = target["end"]
        s_lat, s_lon = float(s["latitude"]), float(s["longitude"])
        e_lat, e_lon = float(e["latitude"]), float(e["longitude"])
        impacts: list[tuple[float, float]] = []
        # n+1 stops along the line so endpoints are covered evenly
        for i in range(total):
            if total == 1:
                t = 0.5
            else:
                t = i / (total - 1)
            impacts.append((s_lat + t * (e_lat - s_lat), s_lon + t * (e_lon - s_lon)))
        return impacts

    if pattern == "ZONE":
        c = target["center"]
        clat, clon = float(c["latitude"]), float(c["longitude"])
        w = float(target.get("width_m", 100.0))
        h = float(target.get("height_m", 100.0))
        rot_mils = float(target.get("rotation_mils", 0.0))
        # Build a near-square grid
        cols = max(1, int(math.ceil(math.sqrt(total))))
        rows = max(1, int(math.ceil(total / cols)))
        impacts = []
        for r in range(rows):
            for col in range(cols):
                if len(impacts) >= total:
                    break
                fx = (col + 0.5) / cols - 0.5  # -0.5..+0.5
                fy = (r + 0.5) / rows - 0.5
                # Local ENU offsets in metres
                east_m = fx * w
                north_m = fy * h
                if rot_mils:
                    az = rot_mils / _MILS_PER_RAD
                    e2 = east_m * math.cos(az) + north_m * math.sin(az)
                    n2 = -east_m * math.sin(az) + north_m * math.cos(az)
                    east_m, north_m = e2, n2
                lat = clat + north_m / 111_000.0
                lon = clon + east_m / (111_000.0 * math.cos(math.radians(clat)))
                impacts.append((lat, lon))
        return impacts

    raise ValueError(f"unknown pattern: {pattern}")


# ── Mortar plan solver ───────────────────────────────────────────────────────


def solve_mortar_plan(
    *,
    guns: list[dict],
    pattern: ValidPattern,
    target: dict,
    rounds_per_gun: int = 1,
    target_alt_m: float = 0.0,
    charge_override: int | None = None,
) -> dict:
    """Compute solutions for 1..4 guns over a POINT/LINE/ZONE pattern.

    `guns` is a list of {"latitude","longitude","altitude","reference_az_mils","callsign"}.
    Returns a JSON-friendly dict:
        {
            "guns": [ { gun_idx, callsign, lat, lon, ... solutions: [FiringSolution, ...] } ],
            "impacts": [ {lat, lon} ],
            "summary": { gun_count, rounds_per_gun, total_rounds, pattern, ammo? }
        }
    """
    if not guns or len(guns) > 4:
        raise ValueError("gun_count must be 1..4")
    impacts = build_sheaf(
        pattern=pattern,
        target=target,
        gun_count=len(guns),
        rounds_per_gun=rounds_per_gun,
    )

    out_guns: list[dict] = []
    for gi, g in enumerate(guns):
        glat = float(g["latitude"])
        glon = float(g["longitude"])
        galt = float(g.get("altitude", 0.0))
        ref = float(g.get("reference_az_mils", 0.0))
        callsign = str(g.get("callsign", f"GUN-{gi+1}"))
        # Round-robin: each gun gets every (gi + k * gun_count)-th impact
        my_impacts = impacts[gi :: len(guns)]
        solutions: list[dict] = []
        for tgt in my_impacts:
            sol = solve_l16_81mm(
                gun_lat=glat,
                gun_lon=glon,
                gun_alt_m=galt,
                tgt_lat=tgt[0],
                tgt_lon=tgt[1],
                tgt_alt_m=target_alt_m,
                reference_az_mils=ref,
                charge_override=charge_override,
            )
            solutions.append(
                {
                    "charge": sol.charge,
                    "qe_mils": sol.qe_mils,
                    "defl_mils": sol.defl_mils,
                    "tof_s": sol.tof_s,
                    "mv_ms": sol.mv_ms,
                    "range_m": sol.range_m,
                    "azimuth_mils": sol.azimuth_mils,
                    "impact": {"latitude": tgt[0], "longitude": tgt[1]},
                    "error": sol.error,
                }
            )
        out_guns.append(
            {
                "gun_idx": gi + 1,
                "callsign": callsign,
                "latitude": glat,
                "longitude": glon,
                "altitude": galt,
                "reference_az_mils": ref,
                "solutions": solutions,
            }
        )

    return {
        "guns": out_guns,
        "impacts": [{"latitude": la, "longitude": lo} for la, lo in impacts],
        "summary": {
            "gun_count": len(guns),
            "rounds_per_gun": rounds_per_gun,
            "total_rounds": len(impacts),
            "pattern": pattern,
        },
    }
