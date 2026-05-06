"""Map-layer endpoints: offline tile manifests, overlays."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.jwt_auth import get_current_operator
from backend.config.xml_config import load_config
from backend.storage.models import Operator

router = APIRouter(prefix="/map", tags=["map"])


class OfflineZone(BaseModel):
    name: str
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    min_zoom: int = 6
    max_zoom: int = 16


# In-memory zone registry — replace with persistent storage when needed.
_offline_zones: list[OfflineZone] = []


@router.get("/config")
def map_config(_: Operator = Depends(get_current_operator)) -> dict:
    cfg = load_config()
    return {
        "tile_url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "offline_enabled": cfg.maps.offline,
    }


@router.get("/offline-zones", response_model=list[OfflineZone])
def list_zones(_: Operator = Depends(get_current_operator)) -> list[OfflineZone]:
    return _offline_zones


@router.post("/offline-zones", response_model=OfflineZone)
def add_zone(zone: OfflineZone, _: Operator = Depends(get_current_operator)) -> OfflineZone:
    _offline_zones.append(zone)
    return zone
