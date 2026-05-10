"""Server-side OSM tile stitcher + tactical overlay for OPORD map snapshots.

Given a bbox (south, west, north, east) and zoom, fetches the covering
XYZ tiles from a configurable tile URL template, stitches them into a
single PNG cropped to the bbox, and overlays all tactical elements that
intersect the bbox: tactical objects (point/line/polygon), online
operators, and active alerts. Tile fetches are cached on disk under
``data/tile_cache/`` to keep retries cheap and stay within OSM tile
usage policy.
"""

from __future__ import annotations

import io
import json
import math
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from backend.storage.models import Alert, Operator, TacticalObject

TILE_URL = os.environ.get("ARROW_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
TILE_USER_AGENT = os.environ.get("ARROW_TILE_UA", "Arrow-OPORD/0.1 (internal)")
TILE_CACHE = Path("data/tile_cache")
TILE_CACHE.mkdir(parents=True, exist_ok=True)
TILE_SIZE = 256
MAX_TILES = 144  # safety cap (12x12)

# ── Symbology ─────────────────────────────────────────────────────────────────
# (fill, outline) RGB tuples. Mirrors the web tactical map roughly.
TYPE_STYLES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "ENEMY":      ((220, 38, 38),  (127, 29, 29)),    # red
    "POI":        ((59, 130, 246), (30, 64, 175)),    # blue
    "MARKER":     ((148, 163, 184),(71, 85, 105)),    # slate
    "OBJECTIVE":  ((34, 197, 94),  (22, 101, 52)),    # green
    "ROUTE":      ((59, 130, 246), (30, 64, 175)),    # blue
    "ZONE":       ((251, 146, 60), (124, 45, 18)),    # orange
    "ATK_AXIS":   ((220, 38, 38),  (127, 29, 29)),
    "DEF_AREA":   ((34, 197, 94),  (22, 101, 52)),
    "AMBUSH":     ((239, 68, 68),  (127, 29, 29)),
    "BOUNDARY":   ((148, 163, 184),(71, 85, 105)),
    "FLET":       ((34, 197, 94),  (22, 101, 52)),
    "FLOT":       ((220, 38, 38),  (127, 29, 29)),
    "PHASE_LINE": ((250, 204, 21), (113, 63, 18)),
    "OBJ_AREA":   ((34, 197, 94),  (22, 101, 52)),
}
DEFAULT_STYLE = ((148, 163, 184), (71, 85, 105))
OPERATOR_FILL = (16, 185, 129)        # green online dot
OPERATOR_OUTLINE = (6, 95, 70)
ALERT_FILL = (250, 204, 21)           # amber pulse
ALERT_OUTLINE = (180, 83, 9)


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


def _parse_geometry(raw: str) -> tuple[str, list[tuple[float, float]]]:
    """Parse the ``TacticalObject.geometry`` JSON string into (kind, [(lat,lon), ...])."""
    if not raw:
        return "point", []
    try:
        g = json.loads(raw)
    except Exception:
        return "point", []
    kind = (g.get("type") or "point").lower()
    coords_raw = g.get("coords") or []
    out: list[tuple[float, float]] = []
    for c in coords_raw:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            out.append((float(c[0]), float(c[1])))
    return kind, out


def _load_font(size: int) -> ImageFont.ImageFont:
    """Best-effort load of a TTF; falls back to default bitmap font."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_snapshot_png(
    bbox: list[float],
    zoom: int,
    db: Session | None = None,
) -> bytes:
    """Stitch OSM tiles + overlay tactical elements within ``bbox``.

    Pass a SQLAlchemy ``Session`` to include all tactical objects, online
    operators (last_seen ≤ 90 s) and active alerts whose coordinates fall
    inside the bbox. With ``db=None`` the function returns the basemap only.
    """
    if len(bbox) != 4:
        raise ValueError("bbox must be [south, west, north, east]")
    south, west, north, east = bbox
    z = max(0, min(19, int(zoom)))

    x0f, y0f = _lon_to_x(west, z), _lat_to_y(north, z)
    x1f, y1f = _lon_to_x(east, z), _lat_to_y(south, z)
    x0, y0 = int(math.floor(x0f)), int(math.floor(y0f))
    x1, y1 = int(math.ceil(x1f)),  int(math.ceil(y1f))
    n_tiles = max(1, x1 - x0) * max(1, y1 - y0)
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

    # Overlay BEFORE cropping so geometry that crosses the edge still draws cleanly.
    if db is not None:
        _draw_overlays(canvas, db, bbox, z, x0, y0)

    crop_left   = int((x0f - x0) * TILE_SIZE)
    crop_top    = int((y0f - y0) * TILE_SIZE)
    crop_right  = int((x1f - x0) * TILE_SIZE)
    crop_bottom = int((y1f - y0) * TILE_SIZE)
    if crop_right > crop_left and crop_bottom > crop_top:
        canvas = canvas.crop((crop_left, crop_top, crop_right, crop_bottom))

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ── Overlay drawing ───────────────────────────────────────────────────────────

def _project(lat: float, lon: float, z: int, x0: int, y0: int) -> tuple[float, float]:
    """Lat/lon → pixel inside the un-cropped stitched canvas."""
    px = (_lon_to_x(lon, z) - x0) * TILE_SIZE
    py = (_lat_to_y(lat, z) - y0) * TILE_SIZE
    return px, py


def _in_bbox(lat: float, lon: float, bbox: list[float]) -> bool:
    s, w, n, e = bbox
    return s <= lat <= n and w <= lon <= e


def _draw_overlays(canvas: Image.Image, db: Session, bbox: list[float],
                   z: int, x0: int, y0: int) -> None:
    s, w, n, e = bbox
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _load_font(11)
    font_small = _load_font(9)

    # ── Tactical objects ─────────────────────────────────────────────────────
    objects: Iterable[TacticalObject] = (
        db.query(TacticalObject)
          .filter(TacticalObject.latitude >= s, TacticalObject.latitude <= n,
                  TacticalObject.longitude >= w, TacticalObject.longitude <= e)
          .all()
    )
    for to in objects:
        fill, outline = TYPE_STYLES.get(to.type or "", DEFAULT_STYLE)
        kind, coords = _parse_geometry(to.geometry or "")
        if kind in ("line", "polygon") and len(coords) >= 2:
            pts = [_project(la, lo, z, x0, y0) for la, lo in coords]
            if kind == "polygon":
                draw.polygon(pts, fill=fill + (70,), outline=outline + (255,))
            else:
                draw.line(pts, fill=outline + (255,), width=3)
        # always draw the anchor point (also serves as label anchor for lines/polys)
        if _in_bbox(to.latitude, to.longitude, bbox):
            px, py = _project(to.latitude, to.longitude, z, x0, y0)
            r = 7
            draw.ellipse((px - r, py - r, px + r, py + r),
                         fill=fill + (255,), outline=outline + (255,), width=2)
            label = to.symbol_code or to.type
            if label:
                draw.text((px + r + 2, py - r - 2), label, fill=(15, 23, 42, 255),
                          font=font, stroke_width=2, stroke_fill=(255, 255, 255, 220))

    # ── Operators (online: last_seen within 90 s) ───────────────────────────
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
    operators: Iterable[Operator] = (
        db.query(Operator)
          .filter(Operator.latitude.isnot(None), Operator.longitude.isnot(None),
                  Operator.last_seen >= cutoff)
          .all()
    )
    for op in operators:
        if not _in_bbox(op.latitude, op.longitude, bbox):
            continue
        px, py = _project(op.latitude, op.longitude, z, x0, y0)
        r = 6
        draw.ellipse((px - r, py - r, px + r, py + r),
                     fill=OPERATOR_FILL + (255,), outline=OPERATOR_OUTLINE + (255,), width=2)
        draw.text((px + r + 2, py - r - 2), op.callsign, fill=(15, 23, 42, 255),
                  font=font_small, stroke_width=2, stroke_fill=(255, 255, 255, 220))

    # ── Active alerts ────────────────────────────────────────────────────────
    alerts: Iterable[Alert] = (
        db.query(Alert)
          .filter(Alert.status == "ACTIVE",
                  Alert.latitude.isnot(None), Alert.longitude.isnot(None))
          .all()
    )
    for al in alerts:
        if not _in_bbox(al.latitude, al.longitude, bbox):
            continue
        px, py = _project(al.latitude, al.longitude, z, x0, y0)
        # diamond marker for alerts
        size = 9
        diamond = [(px, py - size), (px + size, py), (px, py + size), (px - size, py)]
        draw.polygon(diamond, fill=ALERT_FILL + (230,), outline=ALERT_OUTLINE + (255,))
        draw.text((px + size + 2, py - size), al.type, fill=(120, 53, 15, 255),
                  font=font_small, stroke_width=2, stroke_fill=(255, 255, 255, 220))

    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB"))
