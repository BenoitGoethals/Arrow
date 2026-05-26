from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class MissionCreate(BaseModel):
    name:        str
    description: str = ""


class MissionUpdate(BaseModel):
    name:        str | None = None
    description: str | None = None


class MissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:          int
    name:        str
    description: str
    status:      str
    created_by:  int
    created_at:  datetime
    started_at:  datetime | None
    ended_at:    datetime | None
    snapshot_at: datetime | None


class MissionSnapshotOut(MissionOut):
    snapshot: str   # raw JSON — only returned on explicit snapshot endpoint


class AssignOperatorsIn(BaseModel):
    operator_ids: list[int]
