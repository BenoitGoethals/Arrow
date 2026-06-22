"""Thin wrapper around the mgrs package for server-side MGRS conversion."""

from __future__ import annotations

try:
    import mgrs as _mgrs_lib

    _converter = _mgrs_lib.MGRS()

    def to_mgrs(lat: float, lon: float, precision: int = 5) -> str:
        try:
            return _converter.toMGRS(float(lat), float(lon), MGRSPrecision=precision)
        except Exception:
            return f"{lat:.5f}, {lon:.5f}"

except ImportError:

    def to_mgrs(lat: float, lon: float, precision: int = 5) -> str:  # type: ignore[misc]
        return f"{lat:.5f}, {lon:.5f}"
