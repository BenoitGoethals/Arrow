"""Map-layer endpoints: tile sources, MBTiles tile serving, offline manifests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel

from backend.auth.dependencies import get_current_operator
from backend.auth.infrastructure import token_service
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
        ))
    return out


# ── Public endpoints ──────────────────────────────────────────────────────────


@router.get("/config")
def map_config(_: Operator = Depends(get_current_operator)) -> dict:
    cfg = load_config()
    return {
        "tile_url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "offline_enabled": cfg.maps.offline,
    }


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
    return [osm, *_scan_sources()]


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


@router.get("/offline-zones", response_model=list[OfflineZone])
def list_zones(_: Operator = Depends(get_current_operator)) -> list[OfflineZone]:
    return _offline_zones


@router.post("/offline-zones", response_model=OfflineZone)
def add_zone(zone: OfflineZone, _: Operator = Depends(get_current_operator)) -> OfflineZone:
    _offline_zones.append(zone)
    return zone
