"""Pydantic schemas for OPORD CRUD.

The five paragraphs are accepted as free-form dicts so the web editor can
evolve doctrinal sub-fields without forcing a backend schema change.
The web form contributes the canonical sub-keys documented in the README.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MapSnapshotIn(BaseModel):
    label: str = ""
    bbox: list[float] = Field(default_factory=list)  # [south, west, north, east]
    center: list[float] = Field(default_factory=list)  # [lat, lon]
    zoom: float = 0.0
    image_b64: str = ""  # base64 PNG (without data: prefix)
    annotations: str = ""


class MapSnapshotRenderIn(BaseModel):
    """Server-side tile-stitched snapshot — no client-side canvas needed."""

    label: str = ""
    bbox: list[float]  # [south, west, north, east]
    zoom: int = 14
    annotations: str = ""


class MapSnapshotOut(BaseModel):
    id: int
    label: str
    bbox: list[float]
    center: list[float]
    zoom: float
    photo_id: int
    annotations: str


class OpordBase(BaseModel):
    title: str
    opord_number: str = ""
    dtg: str = ""
    time_zone: str = "ZULU"
    classification: str = "UNCLASSIFIED"
    references: str = ""
    task_organization: str = ""
    situation: dict[str, Any] = Field(default_factory=dict)
    mission: str = ""
    execution: dict[str, Any] = Field(default_factory=dict)
    sustainment: dict[str, Any] = Field(default_factory=dict)
    command_signal: dict[str, Any] = Field(default_factory=dict)
    battle_id: int | None = None


class OpordCreate(OpordBase):
    pass


class OpordUpdate(OpordBase):
    pass


class OpordOut(OpordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    author_id: int
    recipient_ids: list[int] = Field(default_factory=list)
    map_snapshots: list[MapSnapshotOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class OpordSendIn(BaseModel):
    operator_ids: list[int]
