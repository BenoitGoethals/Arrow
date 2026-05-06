from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyIn(BaseModel):
    name: str


class CompanyOut(ORMModel):
    id: int
    name: str


class PlatoonIn(BaseModel):
    name: str
    company_id: int


class PlatoonOut(ORMModel):
    id: int
    name: str
    company_id: int


class SectionIn(BaseModel):
    name: str
    platoon_id: int


class SectionOut(ORMModel):
    id: int
    name: str
    platoon_id: int


class TeamIn(BaseModel):
    name: str
    section_id: int


class TeamOut(ORMModel):
    id: int
    name: str
    section_id: int


class OperatorOut(ORMModel):
    id: int
    callsign: str
    rank: str
    status: str
    role: str
    team_id: int | None
    latitude: float | None
    longitude: float | None
    altitude: float | None
    last_seen: datetime


class OperatorUpdate(BaseModel):
    rank: str | None = None
    status: str | None = None
    team_id: int | None = None


class TacticalObjectIn(BaseModel):
    type: str
    symbol_code: str = ""
    latitude: float
    longitude: float
    notes: str = ""
    visibility: str = "COMPANY"
    photo_id: int | None = None


class TacticalObjectOut(ORMModel):
    id: int
    type: str
    symbol_code: str
    created_by: int
    latitude: float
    longitude: float
    timestamp: datetime
    notes: str
    visibility: str
    photo_id: int | None


class PhotoOut(BaseModel):
    id: int
    url: str


class AlertIn(BaseModel):
    type: str
    latitude: float | None = None
    longitude: float | None = None


class AlertOut(ORMModel):
    id: int
    type: str
    operator_id: int
    latitude: float | None
    longitude: float | None
    timestamp: datetime
    status: str


class MessageIn(BaseModel):
    receiver_id: int | None = None
    group_id: str | None = None
    content: str
    message_type: str = "DIRECT"
    photo_id: int | None = None


class MessageOut(ORMModel):
    id: int
    sender_id: int
    receiver_id: int | None
    group_id: str | None
    content: str
    timestamp: datetime
    message_type: str
    photo_id: int | None


class PositionIn(BaseModel):
    latitude: float
    longitude: float
    altitude: float | None = None


class BattleIn(BaseModel):
    name: str
    description: str = ""


class BattleOut(ORMModel):
    id: int
    name: str
    description: str
    started_at: datetime
    ended_at: datetime | None
    status: str


class ReportIn(BaseModel):
    type: str
    payload: dict


class ReportOut(ORMModel):
    id: int
    type: str
    operator_id: int
    payload: str
    timestamp: datetime
