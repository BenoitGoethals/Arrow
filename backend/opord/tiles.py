"""Server-side OSM tile stitcher for OPORD map snapshots.

Given a bbox (south, west, north, east) and zoom, fetches the covering
XYZ tiles from a configurable tile URL template and stitches them into a
single PNG cropped to the bbox. Tile fetches are cached on disk under
``data/tile_cache/`` to keep retries cheap and stay within OSM tile usage
policy on internal/dev usage.
"""

from __future__ import annotations

import io
import math
import os
from pathlib import Path

import urllib.request
from PIL import Image

TILE_URL = os.environ.get("ARROW_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
TILE_USER_AGENT = os.environ.get("ARROW_TILE_UA", "Arrow-OPORD/0.1 (internal)")
TILE_CACHE = Path("data/tile_cache")
TILE_CACHE.mkdir(parents=True, exist_ok=True)
TILE_SIZE = 256
MAX_TILES = 144  # safety cap (12x12)


def _lon_to_x(lon: float, z: int) -> float:
    return (lon + 180.0) / 360.0 * (1 << z)


def _lat_to_y(lat: float, z: int) -> float:
    rad = math.radians(lat)
    return (1 - math.log(math.tan(rad) + 1 / math.cos(rad)) / math.pi) / 2 * (1 << z)


def _fetch_tile(z: int, x: int, y: int) -> bytes:
    cache = TILE_CACHE / f"{z}_{x}_{y}.png"
    if cache.exists():
        return cache.read_bytes()
    url = TILE_URL.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    req = urllib.request.Request(url, headers={"User-Agent": TILE_USER_AGENT})
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        if resp.status != 200:
            raise RuntimeError(f"tile {z}/{x}/{y} HTTP {resp.status}")
        data = resp.read()
    cache.write_bytes(data)
    return data


def render_snapshot_png(bbox: list[float], zoom: int) -> bytes:
    """Stitch OSM tiles into a PNG covering ``bbox`` (south, west, north, east)."""
    if len(bbox) != 4:
        raise ValueError("bbox must be [south, west, north, east]")
    south, west, north, east = bbox
    z = max(0, min(19, int(zoom)))

    x0f, y0f = _lon_to_x(west, z), _lat_to_y(north, z)
    x1f, y1f = _lon_to_x(east, z), _lat_to_y(south, z)
    x0, y0 = int(math.floor(x0f)), int(math.floor(y0f))
    x1, y1 = int(math.ceil(x1f)),  int(math.ceil(y1f))
    n_tiles = max(1, x1 - x0) * max(1, y1 - y0)
    if n_tiles > MAX_TILES:
        # zoom out until under the cap
        while n_tiles > MAX_TILES and z > 1:
            z -= 1
            x0f, y0f = _lon_to_x(west, z), _lat_to_y(north, z)
            x1f, y1f = _lon_to_x(east, z), _lat_to_y(south, z)
            x0, y0 = int(math.floor(x0f)), int(math.floor(y0f))
            x1, y1 = int(math.ceil(x1f)),  int(math.ceil(y1f))
            n_tiles = max(1, x1 - x0) * max(1, y1 - y0)

    width  = (x1 - x0) * TILE_SIZE
    height = (y1 - y0) * TILE_SIZE
    canvas = Image.new("RGB", (width, height), (210, 210, 210))

    for tx in range(x0, x1):
        for ty in range(y0, y1):
            try:
                blob = _fetch_tile(z, tx, ty)
                tile = Image.open(io.BytesIO(blob)).convert("RGB")
                canvas.paste(tile, ((tx - x0) * TILE_SIZE, (ty - y0) * TILE_SIZE))
            except Exception:
                continue

    crop_left   = int((x0f - x0) * TILE_SIZE)
    crop_top    = int((y0f - y0) * TILE_SIZE)
    crop_right  = int((x1f - x0) * TILE_SIZE)
    crop_bottom = int((y1f - y0) * TILE_SIZE)
    if crop_right > crop_left and crop_bottom > crop_top:
        canvas = canvas.crop((crop_left, crop_top, crop_right, crop_bottom))

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()
