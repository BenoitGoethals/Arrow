from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from backend.utils.mgrs import encode as _mgrs_encode


class MissionCreate(BaseModel):
    name: str
    description: str = ""
    map_center_lat: float | None = None
    map_center_lng: float | None = None
    map_zoom: int = 13


class MissionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    map_center_lat: float | None = None
    map_center_lng: float | None = None
    map_zoom: int | None = None


class MissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    status: str
    created_by: int
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    snapshot_at: datetime | None
    map_center_lat: float | None
    map_center_lng: float | None
    map_zoom: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def map_center_mgrs(self) -> str | None:
        if self.map_center_lat is not None and self.map_center_lng is not None:
            return _mgrs_encode(self.map_center_lat, self.map_center_lng)
        return None


class MissionSnapshotOut(MissionOut):
    snapshot: str


class AssignOperatorsIn(BaseModel):
    operator_ids: list[int]
