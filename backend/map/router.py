"""Map-layer endpoints: tile sources, MBTiles tile serving, offline manifests."""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.auth.dependencies import get_current_operator
from backend.auth.infrastructure import token_service
from backend.auth.jwt_auth import require_role
from backend.config.xml_config import load_config
from backend.map.mbtiles import read_meta, read_tile
from backend.storage.database import get_db
from backend.storage.models import Operator

router = APIRouter(prefix="/map", tags=["map"])

_MAPS_DIR = Path(__file__).resolve().parents[2] / "maps"

_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "pbf": "application/x-protobuf",
}


class MapSource(BaseModel):
    name: str
    title: str
    type: str          # "raster" or "vector"
    format: str
    min_zoom: int
    max_zoom: int
    bounds: list[float] | None = None   # [minLon, minLat, maxLon, maxLat]
    center: list[float] | None = None   # [lon, lat]
    attribution: str | None = None
    url_template: str
    is_default: bool = False
    # Total size of the underlying MBTiles file on disk, in bytes. Null for
    # built-in online sources (OSM) where there is no local file.
    size_bytes: int | None = None
    # Whether this source can be downloaded as a raw .mbtiles archive — true
    # for file-backed sources, false for upstream online tile providers.
    downloadable: bool = False


class OfflineZone(BaseModel):
    name: str
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    min_zoom: int = 6
    max_zoom: int = 16


_offline_zones: list[OfflineZone] = []


# ── Auth helper for tile requests ──────────────────────────────────────────────
# Leaflet and OSMdroid can't easily attach an Authorization header to tile URLs,
# so the tile endpoint accepts either a Bearer header or a `?token=...` query
# parameter — the same pattern the websocket endpoint uses.
def _tile_auth(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    db=Depends(get_db),
) -> Operator:
    raw: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    elif token:
        raw = token.strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing token")
    payload = token_service.decode_token(raw)
    if token_service.is_mfa_pending(payload):
        raise HTTPException(status_code=401, detail="MFA verification required")
    callsign = payload.get("sub")
    if not callsign:
        raise HTTPException(status_code=401, detail="Invalid token")
    op = db.query(Operator).filter(Operator.callsign == callsign).first()
    if not op:
        raise HTTPException(status_code=401, detail="Operator not found")
    return op


def _scan_sources() -> list[MapSource]:
    out: list[MapSource] = []
    if not _MAPS_DIR.exists():
        return out
    for path in sorted(_MAPS_DIR.glob("*.mbtiles")):
        try:
            meta = read_meta(path)
        except sqlite3.Error:
            continue
        ext = "jpg" if meta.fmt == "jpeg" else meta.fmt
        out.append(MapSource(
            name=meta.name,
            title=meta.title,
            type="vector" if meta.fmt == "pbf" else "raster",
            format=meta.fmt,
            min_zoom=meta.min_zoom,
            max_zoom=meta.max_zoom,
            bounds=list(meta.bounds) if meta.bounds else None,
            center=list(meta.center) if meta.center else None,
            attribution=meta.attribution,
            url_template=f"/map/tiles/{meta.name}/{{z}}/{{x}}/{{y}}.{ext}",
            size_bytes=path.stat().st_size,
            downloadable=True,
        ))
    return out


# ── Public endpoints ──────────────────────────────────────────────────────────


@router.get("/geocode")
def geocode(
    q: str = Query(..., description="Address, place name, or free-text location"),
    _: Operator = Depends(get_current_operator),
) -> JSONResponse:
    """Proxy Nominatim geocoding to avoid browser CORS/CSP restrictions."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query is empty")
    url = (
        "https://nominatim.openstreetmap.org/search?"
        + urllib.parse.urlencode({"q": q, "format": "json", "limit": "5",
                                  "addressdetails": "0"})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "ArrowTactical/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            import json
            data = json.loads(resp.read())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Geocoding failed: {exc}") from exc
    return JSONResponse(content=data)


@router.get("/config")
def map_config(_: Operator = Depends(get_current_operator)) -> dict:
    cfg = load_config()
    return {
        "tile_url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "offline_enabled": cfg.maps.offline,
        "owm_api_key": cfg.maps.owm_api_key,
    }


_WMS_LAYERS = (
    ("operators",        "Operators"),
    ("tactical_objects", "Tactical Objects"),
    ("cot_tracks",       "CoT Tracks"),
    ("alerts",           "Alerts"),
    ("fire_missions",    "Fire Missions"),
    ("supply_points",    "Supply Points"),
)


def _wms_sources() -> list[MapSource]:
    """Return MapServer WMS sources when running on PostgreSQL."""
    cfg = load_config()
    if not cfg.database.url.startswith("postgresql"):
        return []
    wms_base = os.environ.get("ARROW_MAPSERVER_URL", "/mapserver")
    sources: list[MapSource] = []
    for layer_id, layer_title in _WMS_LAYERS:
        sources.append(MapSource(
            name=f"wms_{layer_id}",
            title=f"WMS: {layer_title}",
            type="wms",
            format="png",
            min_zoom=0,
            max_zoom=19,
            url_template=(
                f"{wms_base}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
                f"&LAYERS={layer_id}&SRS=EPSG:{{srs}}&FORMAT=image/png"
                "&TRANSPARENT=true&WIDTH={width}&HEIGHT={height}&BBOX={bbox}"
            ),
        ))
    return sources


@router.get("/sources", response_model=list[MapSource])
def list_sources(_: Operator = Depends(get_current_operator)) -> list[MapSource]:
    """All selectable base map sources: built-in OSM plus every MBTiles in maps/."""
    osm = MapSource(
        name="osm",
        title="OpenStreetMap",
        type="raster",
        format="png",
        min_zoom=0,
        max_zoom=19,
        attribution="© OpenStreetMap contributors",
        url_template="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        is_default=True,
    )
    return [osm, *_scan_sources(), *_wms_sources()]


@router.get("/tiles/{name}/{z}/{x}/{y}.{ext}")
def get_tile(
    name: str,
    z: int,
    x: int,
    y: int,
    ext: str,
    _: Operator = Depends(_tile_auth),
) -> Response:
    # Defence in depth — path traversal guard. Tile names come from filenames
    # we control under maps/, but the route param is user-supplied.
    if "/" in name or ".." in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid source name")
    path = _MAPS_DIR / f"{name}.mbtiles"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Unknown map source")
    data = read_tile(path, z, x, y)
    if data is None:
        # 204 lets Leaflet/OSMdroid quietly skip absent tiles without logging
        # an error for each one outside the source's coverage area.
        return Response(status_code=204)
    mime = _MIME.get(ext.lower(), "application/octet-stream")
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ── Map management — upload / delete / download ──────────────────────────────
# Upload + delete are gated on ADMIN/BATTLE_CAPTAIN. Download uses the same
# token-via-query auth as /map/tiles so the Android client can resume large
# files via a plain HTTP GET without juggling headers.

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MBTILES_DIR = _MAPS_DIR


def _safe_name(name: str) -> str:
    """Validate a source name to keep it inside maps/ — defence in depth."""
    if not name or not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid source name")
    if name.startswith(".") or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid source name")
    return name


def _validate_mbtiles(path: Path) -> None:
    """Refuse anything that isn't a real MBTiles SQLite archive.

    Per the MBTiles 1.2/1.3 spec `tiles` and `metadata` can be implemented as
    either tables OR views — tippecanoe and mbutil both emit a `tiles` view
    over `map` + `images` for de-duplication — so checking `type='table'`
    alone falsely rejects valid files. Also probe the actual contents: a real
    archive has at least one row in metadata and the tiles relation answers
    a COUNT(*) without error.
    """
    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, check_same_thread=False
        )
        try:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
            if "tiles" not in names or "metadata" not in names:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Missing required MBTiles relations 'tiles' and/or "
                        f"'metadata'. Found: {sorted(names)}"
                    ),
                )
            # Smoke-test the relations are queryable — covers files that have
            # a `tiles` view referencing a missing underlying table.
            conn.execute("SELECT COUNT(*) FROM metadata").fetchone()
            conn.execute("SELECT COUNT(*) FROM tiles LIMIT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=400, detail=f"Not a valid MBTiles archive: {exc}")


@router.post("/sources", response_model=MapSource, status_code=201)
async def upload_source(
    file: UploadFile = File(...),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> MapSource:
    """Streaming MBTiles upload.

    The file is written to a temp file under maps/ in 1 MB chunks so even
    multi-gigabyte uploads never sit fully in memory. The temp file is
    validated as a real MBTiles archive and then atomically renamed into
    place — readers never see a half-written file.
    """
    import logging  # noqa: PLC0415
    log = logging.getLogger(__name__)

    filename = file.filename or ""
    if not filename.lower().endswith(".mbtiles"):
        raise HTTPException(status_code=400, detail="Filename must end in .mbtiles")
    # Sanitise the filename stem — browsers may include spaces, parentheses,
    # or other chars that break our strict regex. Normalise to underscores and
    # collapse runs.
    raw_stem = Path(filename).stem
    safe_chars = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_stem).strip("._-")
    if not safe_chars:
        raise HTTPException(status_code=400, detail=f"Cannot derive a valid name from {filename!r}")
    stem = _safe_name(safe_chars)
    final_path = _MBTILES_DIR / f"{stem}.mbtiles"

    try:
        _MBTILES_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.exception("upload: cannot create maps dir %s", _MBTILES_DIR)
        raise HTTPException(status_code=500, detail=f"maps dir not writable: {exc}")

    if not os.access(_MBTILES_DIR, os.W_OK):
        raise HTTPException(
            status_code=500,
            detail=f"maps dir {_MBTILES_DIR} is not writable by the backend "
                   f"(check the docker-compose volume mount and host permissions)",
        )

    try:
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{stem}.", suffix=".mbtiles.part", dir=_MBTILES_DIR
        )
    except OSError as exc:
        log.exception("upload: mkstemp failed in %s", _MBTILES_DIR)
        raise HTTPException(status_code=500, detail=f"Cannot create temp file: {exc}")

    tmp_path = Path(tmp_path_str)
    bytes_written = 0
    try:
        with os.fdopen(tmp_fd, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                bytes_written += len(chunk)
        if bytes_written == 0:
            raise HTTPException(status_code=400, detail="Empty upload body")
        log.info("upload: wrote %d bytes to %s", bytes_written, tmp_path)
        _validate_mbtiles(tmp_path)
        # Drop any cached connection to the destination before replacing the file.
        from backend.map.mbtiles import _open  # noqa: PLC0415
        _open.cache_clear()
        os.replace(tmp_path, final_path)
    except HTTPException:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        log.exception("upload: unexpected failure for %s", filename)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")

    try:
        meta = read_meta(final_path)
    except Exception as exc:
        log.exception("upload: read_meta failed for %s", final_path)
        raise HTTPException(status_code=500, detail=f"Saved but unreadable: {exc}")
    ext = "jpg" if meta.fmt == "jpeg" else meta.fmt
    return MapSource(
        name=meta.name,
        title=meta.title,
        type="vector" if meta.fmt == "pbf" else "raster",
        format=meta.fmt,
        min_zoom=meta.min_zoom,
        max_zoom=meta.max_zoom,
        bounds=list(meta.bounds) if meta.bounds else None,
        center=list(meta.center) if meta.center else None,
        attribution=meta.attribution,
        url_template=f"/map/tiles/{meta.name}/{{z}}/{{x}}/{{y}}.{ext}",
        size_bytes=final_path.stat().st_size,
        downloadable=True,
    )


@router.delete("/sources/{name}", status_code=204)
def delete_source(
    name: str,
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Response:
    safe = _safe_name(name)
    path = _MBTILES_DIR / f"{safe}.mbtiles"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Unknown map source")
    # Drop the cached SQLite handle for this file before deleting on disk.
    from backend.map.mbtiles import _open as _open_cached  # noqa: PLC0415
    _open_cached.cache_clear()
    path.unlink()
    return Response(status_code=204)


@router.get("/sources/{name}/download")
def download_source(
    name: str,
    _: Operator = Depends(_tile_auth),
) -> FileResponse:
    """Stream the raw .mbtiles file so the Android client can render offline.

    FileResponse handles HTTP Range requests automatically — a half-downloaded
    file can be resumed by re-issuing the GET with `Range: bytes=N-`.
    """
    safe = _safe_name(name)
    path = _MBTILES_DIR / f"{safe}.mbtiles"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Unknown map source")
    return FileResponse(
        path,
        media_type="application/vnd.mapbox-vector-tile",
        filename=f"{safe}.mbtiles",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/offline-zones", response_model=list[OfflineZone])
def list_zones(_: Operator = Depends(get_current_operator)) -> list[OfflineZone]:
    return _offline_zones


@router.post("/offline-zones", response_model=OfflineZone)
def add_zone(zone: OfflineZone, _: Operator = Depends(get_current_operator)) -> OfflineZone:
    _offline_zones.append(zone)
    return zone
