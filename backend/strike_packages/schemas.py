"""Pydantic schemas for the Strike Package module."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Asset sub-types ───────────────────────────────────────────────────────────

class DroneAsset(BaseModel):
    callsign: str = ""
    platform: str = ""          # MQ-9, TB2, DJI Matrice, etc.
    loiter_lat: float | None = None
    loiter_lon: float | None = None
    feed_url: str = ""
    notes: str = ""


class IsrAsset(BaseModel):
    sensor: str = ""            # SIGINT, IMINT, HUMINT, MASINT
    platform: str = ""
    collection_priority: str = "MEDIUM"   # HIGH | MEDIUM | LOW
    notes: str = ""


class AirSupportAsset(BaseModel):
    aircraft: str = ""          # F-18, AH-64, AC-130, etc.
    callsign: str = ""
    ordnance: str = ""          # GBU-12, Hellfire, 30mm, etc.
    station_time_min: int = 0
    frequency: str = ""
    notes: str = ""


class SniperOverwatch(BaseModel):
    callsign: str = ""
    position_lat: float | None = None
    position_lon: float | None = None
    sector_of_fire: str = ""
    engagement_criteria: str = ""


class EwAsset(BaseModel):
    system: str = ""            # AN/ALQ-99, CREW, DUKE, etc.
    callsign: str = ""
    frequency_bands: str = ""
    objective: str = "JAM"      # JAM | SIGINT | EW_ATTACK | DECEPTION
    notes: str = ""


class CommsConfig(BaseModel):
    primary_freq: str = ""
    alternate_freq: str = ""
    waveform: str = ""
    pace_plan: str = ""         # Primary/Alternate/Contingency/Emergency one-liner


class AssaultPhase(BaseModel):
    name: str = ""
    description: str = ""
    actions: str = ""


class AssaultPlan(BaseModel):
    phases: list[AssaultPhase] = []
    breach_points: list[str] = []
    actions_on_objective: str = ""
    consolidation: str = ""


class ExfilRoute(BaseModel):
    name: str = ""              # PRIMARY | ALTERNATE | EMERGENCY
    type: str = "GROUND"        # GROUND | AIR | WATER
    description: str = ""
    tactical_object_id: int | None = None   # links to a ROUTE TacticalObject


class PackageAssets(BaseModel):
    drones: list[DroneAsset] = []
    isr: list[IsrAsset] = []
    air_support: list[AirSupportAsset] = []
    sniper_overwatch: list[SniperOverwatch] = []
    electronic_warfare: list[EwAsset] = []
    comms: CommsConfig = Field(default_factory=CommsConfig)
    assault_plan: AssaultPlan = Field(default_factory=AssaultPlan)
    exfil_routes: list[ExfilRoute] = []


# ── API in/out ────────────────────────────────────────────────────────────────

class StrikePackageIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    mission_id: int | None = None
    target_lat: float | None = None
    target_lon: float | None = None
    target_description: str = ""
    operator_ids: list[int] = []
    tactical_object_ids: list[int] = []
    fire_mission_ids: list[int] = []
    report_ids: list[int] = []
    assets: PackageAssets = Field(default_factory=PackageAssets)


class StrikePackageUpdate(BaseModel):
    name: str | None = None
    target_lat: float | None = None
    target_lon: float | None = None
    target_description: str | None = None
    operator_ids: list[int] | None = None
    tactical_object_ids: list[int] | None = None
    fire_mission_ids: list[int] | None = None
    report_ids: list[int] | None = None
    assets: PackageAssets | None = None


class StrikePackageOut(ORMModel):
    id: int
    name: str
    status: str
    mission_id: int | None
    created_by: int
    created_at: datetime
    updated_at: datetime
    target_lat: float | None
    target_lon: float | None
    target_description: str
    operator_ids: list[int]
    tactical_object_ids: list[int]
    fire_mission_ids: list[int]
    report_ids: list[int]
    assets: PackageAssets

    @field_validator("operator_ids", "tactical_object_ids", "fire_mission_ids", "report_ids", mode="before")
    @classmethod
    def _parse_id_list(cls, v: object) -> list[int]:
        if isinstance(v, str):
            return json.loads(v)
        return v  # type: ignore[return-value]

    @field_validator("assets", mode="before")
    @classmethod
    def _parse_assets(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v
