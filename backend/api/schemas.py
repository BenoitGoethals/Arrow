from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

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
    ops_status: str = "OPS"
    role: str
    team_id: int | None
    team_role: str | None
    mission_id: int | None
    latitude: float | None
    longitude: float | None
    altitude: float | None
    position_source: str | None = None
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
    ops_status: str | None = None
    team_id: int | None = None
    team_role: str | None = None
    mission_id: int | None = None


class OpsStatusUpdate(BaseModel):
    ops_status: str  # OPS | INOPS | KIA | MIA


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
    # NATO affiliation — drives the colour of tactical control graphics so
    # every TG type (attack, ambush, defense, etc.) can be drawn as either
    # FRIENDLY (blue) or ENEMY (red) or UNKNOWN (yellow). Defaults to FRIENDLY.
    affiliation: str = "FRIENDLY"


class TacticalObjectPatch(BaseModel):
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None
    rotation: float | None = None


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
    affiliation: str = "FRIENDLY"


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
    callsign: str | None = None
    latitude: float | None
    longitude: float | None
    timestamp: datetime
    status: str

    @model_validator(mode='before')
    @classmethod
    def _pull_callsign(cls, data):
        if not isinstance(data, dict) and hasattr(data, 'operator') and data.operator is not None:
            return {
                'id': data.id, 'type': data.type, 'operator_id': data.operator_id,
                'callsign': data.operator.callsign,
                'latitude': data.latitude, 'longitude': data.longitude,
                'timestamp': data.timestamp, 'status': data.status,
            }
        return data


class MessageIn(BaseModel):
    receiver_id: int | None = None
    group_id: str | None = None
    chatroom_id: int | None = None
    content: str = ""
    message_type: str = "DIRECT"   # DIRECT | BROADCAST | ROOM
    photo_id: int | None = None


class ChatRoomMemberOut(ORMModel):
    operator_id: int
    callsign: str | None = None


class ChatRoomIn(BaseModel):
    name: str
    member_ids: list[int] = []


class ChatRoomOut(BaseModel):
    id: int
    name: str
    created_by: int
    created_at: datetime
    mission_id: int | None = None
    origin: str = "ARROW"
    member_ids: list[int] = []
    members: list[ChatRoomMemberOut] = []


class ChatRoomMemberIn(BaseModel):
    operator_id: int


class MessageOut(ORMModel):
    id: int
    sender_id: int
    receiver_id: int | None
    group_id: str | None
    chatroom_id: int | None = None
    content: str
    timestamp: datetime
    message_type: str
    photo_id: int | None
    photo_mime_type: str | None = None


class PositionIn(BaseModel):
    latitude: float
    longitude: float
    altitude: float | None = None


class PositionHistoryOut(ORMModel):
    id: int
    operator_id: int
    latitude: float
    longitude: float
    altitude: float | None
    recorded_at: datetime


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


class DroneSpotIn(BaseModel):
    """Operator-submitted drone observation (UAV / loitering munition / FPV / ISR).

    Stored as a Report with `type="DRONE_SPOT"` and an Alert with
    `type="DRONE_SPOTTED"` so map + alerts both pick it up.
    """
    latitude:      float
    longitude:     float
    drone_type:    str   = "UNKNOWN"   # QUADCOPTER | FIXED_WING | FPV | LOITERING_MUNITION | ISR | UNKNOWN | <model>
    altitude_m:    float | None = None
    direction_deg: float | None = None  # 0..359, bearing of travel
    speed_kts:     float | None = None
    behavior:      str   = "UNKNOWN"   # HOVERING | TRANSITING | ATTACK_RUN | RECONNAISSANCE | LOITERING | EVADING | UNKNOWN
    notes:         str   = ""


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
    fo_operator_id: int | None = None
    tic: bool = False
    mission_id: int | None = None


class LogrepRouteIn(BaseModel):
    destinations: list[str]   # ["S1", "S2", "COY_A", …]


class LogrepRouteFeedbackIn(BaseModel):
    feedback_text: str
    feedback_by:   str = ""   # callsign of the responder


class LogrepRouteOut(ORMModel):
    id:            int
    report_id:     int
    destination:   str
    routed_by:     int
    routed_at:     datetime
    status:        str
    feedback_text: str
    feedback_by:   str
    feedback_at:   datetime | None


class CasNineLinerIn(BaseModel):
    """Structured CAS 9-liner request.

    Line 5 carries both the human-readable MGRS string and the exact WGS-84
    coordinates so the backend can geocode and broadcast a map marker.
    """
    # Standard 9-liner lines
    line_1: str = ""   # IP (Initial Point)
    line_2: str = ""   # Heading / Distance from IP to target
    line_3: str = ""   # Target elevation MSL
    line_4: str = ""   # Target description
    # Line 5: target location — provided as MGRS + optional precise lat/lon
    line_5_mgrs: str = ""
    line_5_lat:  float | None = None
    line_5_lon:  float | None = None
    line_6: str = ""   # Type of mark (Laser / Smoke / IR pointer / Mark-63 / None)
    line_7: str = ""   # Friendly location relative to target
    line_8: str = ""   # Egress direction
    line_9: str = ""   # Remarks / Threats / TOT
    # CAS request metadata
    tic: bool = False               # Troops In Contact — triggers priority WS event
    fo_operator_id: int | None = None   # Forward Observer assigned to this request
    asset_id: int | None = None         # CAS asset nominated for the mission


class CasAssetIn(BaseModel):
    callsign:      str
    aircraft_type: str = ""
    ordnance:      str = ""
    frequency:     str = ""
    status:        str = "AVAILABLE"
    available_from: datetime | None = None
    available_to:   datetime | None = None
    notes:          str = ""
    mission_id:     int | None = None


class CasAssetUpdate(BaseModel):
    callsign:      str | None = None
    aircraft_type: str | None = None
    ordnance:      str | None = None
    frequency:     str | None = None
    status:        str | None = None
    available_from: datetime | None = None
    available_to:   datetime | None = None
    notes:          str | None = None


class CasAssetOut(ORMModel):
    id:            int
    callsign:      str
    aircraft_type: str
    ordnance:      str
    frequency:     str
    status:        str
    available_from: datetime | None
    available_to:   datetime | None
    notes:          str
    mission_id:     int | None
    created_by:     int
    created_at:     datetime
    updated_at:     datetime


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


class CotTrackOut(ORMModel):
    id:        int
    cot_uid:   str
    cot_type:  str
    callsign:  str
    latitude:  float
    longitude: float
    hae:       float
    speed:     float
    course:    float
    team:      str
    remarks:   str | None = None
    last_seen: datetime

    @computed_field
    @property
    def sidc(self) -> str:
        from backend.cot.cot import cot_type_to_sidc  # noqa: PLC0415
        return cot_type_to_sidc(self.cot_type)


class AtakShapeOut(ORMModel):
    id:            int
    uid:           str
    cot_type:      str
    shape_type:    str
    title:         str
    callsign:      str
    geometry_json: str
    last_seen:     datetime
