from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, computed_field

_NAME = Field(min_length=1, max_length=120)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyIn(BaseModel):
    name: str = _NAME


class CompanyOut(ORMModel):
    id: int
    name: str


class PlatoonIn(BaseModel):
    name: str = _NAME
    company_id: int


class PlatoonOut(ORMModel):
    id: int
    name: str
    company_id: int


class SectionIn(BaseModel):
    name: str = _NAME
    platoon_id: int


class SectionOut(ORMModel):
    id: int
    name: str
    platoon_id: int


class TeamIn(BaseModel):
    name: str = _NAME
    section_id: int


class TeamOut(ORMModel):
    id: int
    name: str
    section_id: int


_ONLINE_WINDOW = timedelta(seconds=90)


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

    @computed_field  # type: ignore[misc]
    @property
    def online(self) -> bool:
        if self.status != "ONLINE":
            return False
        last = self.last_seen
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last) <= _ONLINE_WINDOW


class OperatorUpdate(BaseModel):
    rank: str | None = None
    role: str | None = None
    status: str | None = None
    team_id: int | None = None


class PasswordReset(BaseModel):
    password: str


class TacticalObjectIn(BaseModel):
    type: str
    symbol_code: str = ""
    latitude: float
    longitude: float
    notes: str = ""
    visibility: str = "COMPANY"
    photo_id: int | None = None
    # Heading clockwise from north for oriented point symbols (attack/ambush/defense).
    rotation: float = 0.0
    # JSON string: {"type":"point|line|polygon","coords":[[lat,lon],...]}.
    # Empty = treat as point at (latitude, longitude).
    geometry: str = ""
    # NATO unit echelon: "" / "TM" / "SEC" / "PL" / "COY" / "BN" / "BDE"
    echelon: str = ""


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
    rotation: float = 0.0
    geometry: str = ""
    echelon: str = ""


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


class ReportUpdate(BaseModel):
    status: str
    reviewer_note: str = ""


class ReportOut(ORMModel):
    id: int
    type: str
    operator_id: int
    payload: str
    timestamp: datetime
    status: str = "RECEIVED"
    reviewer_note: str = ""


class FireMissionIn(BaseModel):
    latitude:     float
    longitude:    float
    altitude:     float  = 0.0
    direction:    float               # azimuth ° (observer → target)
    mission_type: str                 # ADJUST_FIRE | FIRE_FOR_EFFECT | SUPPRESSION | ILLUMINATION
    ammunition:   str                 # HE | ILLUM | SMOKE | WP | ICM | MIXED
    quantity:     int    = 1
    description:  str    = ""


class FireMissionUpdate(BaseModel):
    status:          str | None = None
    fdc_operator_id: int | None = None
    notes:           str | None = None


class FireMissionOut(ORMModel):
    id:              int
    operator_id:     int
    latitude:        float
    longitude:       float
    altitude:        float
    direction:       float
    mission_type:    str
    ammunition:      str
    quantity:        int
    description:     str
    status:          str
    fdc_operator_id: int | None
    timestamp:       datetime
    notes:           str
