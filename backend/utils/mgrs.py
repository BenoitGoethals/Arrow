"""MGRS coordinate encoder — WGS-84 / DMATM 8358.1."""

from __future__ import annotations

import math

_SET_COLS = ["ABCDEFGH", "JKLMNPQR", "STUVWXYZ"]
_ROW_ODD = "ABCDEFGHJKLMNPQRSTUV"
_ROW_EVEN = "FGHJKLMNPQRSTUVABCDE"
_BANDS = "CDEFGHJKLMNPQRSTUVWX"


def _utm_zone(lat: float, lon: float) -> int:
    if 56 <= lat < 64 and 3 <= lon < 12:
        return 32
    if 72 <= lat <= 84:
        if lon < 9:
            return 31
        if lon < 21:
            return 33
        if lon < 33:
            return 35
        if lon < 42:
            return 37
    return int((lon + 180) / 6) + 1


def _lat_band(lat: float) -> str:
    return _BANDS[min(19, int((lat + 80) / 8))]


def _to_utm(lat: float, lon: float, zone: int) -> tuple[float, float]:
    a, f = 6_378_137.0, 1.0 / 298.257223563
    e2 = 2 * f - f * f
    e4 = e2 * e2
    e6 = e4 * e2
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    lr = math.radians(lat)
    lo = math.radians(lon)
    lo0 = math.radians((zone - 1) * 6 - 180 + 3)
    N = a / math.sqrt(1 - e2 * math.sin(lr) ** 2)
    T = math.tan(lr) ** 2
    C = ep2 * math.cos(lr) ** 2
    av = math.cos(lr) * (lo - lo0)
    M = a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lr
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lr)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lr)
        - (35 * e6 / 3072) * math.sin(6 * lr)
    )
    e = (
        k0
        * N
        * (
            av
            + (1 - T + C) * av**3 / 6
            + (5 - 18 * T + T**2 + 72 * C - 58 * ep2) * av**5 / 120
        )
        + 500_000
    )
    n = k0 * (
        M
        + N
        * math.tan(lr)
        * (
            av**2 / 2
            + (5 - T + 9 * C + 4 * C**2) * av**4 / 24
            + (61 - 58 * T + T**2 + 600 * C - 330 * ep2) * av**6 / 720
        )
    )
    if lat < 0:
        n += 10_000_000
    return e, n


def encode(lat: float, lon: float, precision: int = 5) -> str:
    """Return an MGRS string for WGS-84 *lat*/*lon* (precision = digits per axis, 1–5)."""
    try:
        z = _utm_zone(lat, lon)
        b = _lat_band(lat)
        e, n = _to_utm(lat, lon, z)
        col = _SET_COLS[(z - 1) % 3][max(0, min(7, int(e / 100_000) - 1))]
        row = (_ROW_ODD if z % 2 else _ROW_EVEN)[int(n / 100_000) % 20]
        es = str(int(e % 100_000)).zfill(5)[:precision]
        ns = str(int(n % 100_000)).zfill(5)[:precision]
        return f"{z}{b}{col}{row} {es}{ns}"
    except Exception:
        return f"{lat:.4f},{lon:.4f}"
