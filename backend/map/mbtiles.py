"""MBTiles (SQLite-backed raster/vector tile archive) reader.

The MBTiles spec stores tiles in `tiles(zoom_level, tile_column, tile_row,
tile_data)` with TMS row order — the row index must be flipped before lookup
against an XYZ tile coordinate.

Connections are cached per file path with `check_same_thread=False`: FastAPI
runs sync endpoints on a threadpool, and SQLite's serialised threading mode
(the default Python build) lets multiple threads share a read-only handle.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(slots=True, frozen=True)
class MbtilesMeta:
    name: str
    title: str
    fmt: str
    min_zoom: int
    max_zoom: int
    bounds: tuple[float, float, float, float] | None
    center: tuple[float, float] | None
    attribution: str | None


@lru_cache(maxsize=64)
def _open(path: str) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


def _metadata(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT name, value FROM metadata").fetchall()
    return {n: v for (n, v) in rows if n is not None}


def read_meta(path: Path) -> MbtilesMeta:
    """Read the `metadata` table for an MBTiles file and return a parsed view."""
    conn = _open(str(path))
    md = _metadata(conn)
    fmt = (md.get("format") or "png").lower()
    bounds: tuple[float, float, float, float] | None = None
    if "bounds" in md:
        try:
            parts = [float(x) for x in md["bounds"].split(",")]
            if len(parts) >= 4:
                bounds = (parts[0], parts[1], parts[2], parts[3])
        except ValueError:
            bounds = None
    center: tuple[float, float] | None = None
    if "center" in md:
        try:
            parts = [float(x) for x in md["center"].split(",")]
            if len(parts) >= 2:
                center = (parts[0], parts[1])
        except ValueError:
            center = None
    return MbtilesMeta(
        name=path.stem,
        # Use the filename stem as the human-readable title. The MBTiles
        # `metadata.name` is often a generic export-tool default (e.g.
        # "cache" / "Unnamed atlas") and not useful to operators.
        title=path.stem,
        fmt=fmt,
        min_zoom=int(md.get("minzoom") or 0),
        max_zoom=int(md.get("maxzoom") or 18),
        bounds=bounds,
        center=center,
        attribution=md.get("attribution"),
    )


def read_tile(path: Path, z: int, x: int, y: int) -> bytes | None:
    """Look up one XYZ tile. Returns None if the tile is absent.

    The MBTiles row index is TMS (origin bottom-left), so we flip y first.

    Connections are cached and shared across threads (FastAPI runs sync
    endpoints on a threadpool). If an admin uploads a new MBTiles archive
    mid-request, ``_open.cache_clear()`` plus ``os.replace`` can leave a
    cached connection pointing at a stale inode or already-closed handle —
    SQLite then raises ``InterfaceError: bad parameter or other API misuse``
    on the next ``execute``. We invalidate the cache and retry exactly once,
    which heals the race without spinning forever on a genuinely broken file.
    """
    tms_y = (1 << z) - 1 - y
    params = (int(z), int(x), int(tms_y))
    for attempt in (0, 1):
        conn = _open(str(path))
        try:
            row = conn.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                params,
            ).fetchone()
            return row[0] if row else None
        except (
            sqlite3.InterfaceError,
            sqlite3.ProgrammingError,
            sqlite3.OperationalError,
        ):
            if attempt == 1:
                raise
            _open.cache_clear()
    return None
