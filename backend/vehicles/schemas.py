"""Pydantic schemas for the Vehicle module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class VehicleIn(BaseModel):
    callsign: str = Field(min_length=1, max_length=60)
    vehicle_type: str = ""
    symbol_code: str = ""
    affiliation: str = "FRIENDLY"
    ops_status: str = "OPS"
    team_id: int | None = None
    operator_id: int | None = None
    mission_id: int | None = None
    notes: str = ""


class VehicleUpdate(BaseModel):
    callsign: str | None = None
    vehicle_type: str | None = None
    symbol_code: str | None = None
    affiliation: str | None = None
    ops_status: str | None = None
    team_id: int | None = None
    operator_id: int | None = None
    mission_id: int | None = None
    notes: str | None = None


class VehicleOut(ORMModel):
    id: int
    callsign: str
    vehicle_type: str
    symbol_code: str
    affiliation: str
    ops_status: str
    team_id: int | None
    operator_id: int | None
    mission_id: int | None
    notes: str
    created_by: int
    created_at: datetime
    updated_at: datetime
    # Derived from the assigned operator/team — populated by the router.
    latitude: float | None = None
    longitude: float | None = None
    online: bool = False
