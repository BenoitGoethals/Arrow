from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.storage.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Mission(Base):
    """Top-level container for a tactical operation.

    Every map element (tactical objects, alerts, fire missions, messages,
    reports) is scoped to one Mission. Overlays and KML layers are global
    (shared across missions).

    Lifecycle: PLANNING → ACTIVE → ENDED.
    On end or reset a full JSON snapshot of all mission objects is saved.
    """

    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PLANNING")
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    snapshot: Mapped[str] = mapped_column(Text, default="")
    snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    map_center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    map_center_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    map_zoom: Mapped[int] = mapped_column(Integer, default=13)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)

    platoons: Mapped[list["Platoon"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Platoon(Base):
    __tablename__ = "platoons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))

    company: Mapped[Company] = relationship(back_populates="platoons")
    sections: Mapped[list["Section"]] = relationship(
        back_populates="platoon", cascade="all, delete-orphan"
    )


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    platoon_id: Mapped[int] = mapped_column(ForeignKey("platoons.id"))

    platoon: Mapped[Platoon] = relationship(back_populates="sections")
    teams: Mapped[list["Team"]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"))

    section: Mapped[Section] = relationship(back_populates="teams")
    operators: Mapped[list["Operator"]] = relationship(back_populates="team")


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    callsign: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    rank: Mapped[str] = mapped_column(String(40), default="OR-1")
    status: Mapped[str] = mapped_column(
        String(20), default="OFFLINE"
    )  # presence: ONLINE/OFFLINE
    # Operational status, independent of presence — set by BC/ADMIN.
    # OPS (mission-capable) | INOPS (out of action) | KIA | MIA
    ops_status: Mapped[str] = mapped_column(String(10), default="OPS")
    role: Mapped[str] = mapped_column(
        String(20), default="OPERATOR"
    )  # ADMIN, BATTLE_CAPTAIN, OPERATOR, LOG, FO, CAS, INTEL, OPS, MED, CBRN, FBC
    password_hash: Mapped[str] = mapped_column(String(255))

    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Source of the last position fix: "ATAK" (device via CoT TCP), "APP" (mobile/web GPS), or None.
    position_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    # Account lockout (A04)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # TOTP MFA (PR.AA)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(default=False)

    # Single-device session enforcement — only the token whose jti matches this
    # field is valid; a new login overwrites it, instantly invalidating all others.
    session_jti: Mapped[str | None] = mapped_column(String(36), nullable=True)

    team: Mapped[Team | None] = relationship(back_populates="operators")
    positions: Mapped[list["OperatorPosition"]] = relationship(
        back_populates="operator",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class OperatorPosition(Base):
    """Time-series of every GPS fix received from an operator.

    The Operator row still holds the *current* position for fast live queries.
    This table keeps the full history for track visualisation and behaviour analytics.
    """

    __tablename__ = "operator_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"),
        index=True,
    )
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        index=True,
    )

    operator: Mapped["Operator"] = relationship(back_populates="positions")


class Vehicle(Base):
    """A tactical vehicle owned/used by a unit.

    Generic across the order of battle — any unit type has its own vehicles
    (the ``vehicle_type`` free-text field captures the platform: LMV, Boxer,
    MAN truck, RHIB, …). A vehicle is assigned to **either** a single operator
    (``operator_id``) **or** a whole team (``team_id``); both nullable, at most
    one set. The vehicle has no GPS of its own — its map position is derived
    from the assigned operator (or, for a team, that team's anchor operator).

    ``ops_status`` mirrors the operator set: OPS | INOPS | KIA | MIA
    (KIA/MIA read as destroyed/missing for materiel).
    """

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    callsign: Mapped[str] = mapped_column(String(60))
    vehicle_type: Mapped[str] = mapped_column(String(80), default="")
    # MIL-STD-2525 equipment SIDC (rendered on the map); empty = generic equipment.
    symbol_code: Mapped[str] = mapped_column(String(40), default="")
    affiliation: Mapped[str] = mapped_column(String(12), default="FRIENDLY")
    ops_status: Mapped[str] = mapped_column(String(10), default="OPS")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str] = mapped_column(String(80), default="image/jpeg")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    # SHA-256 of the plaintext bytes — used by the TAK Marti file-share API so
    # ATAK can fetch the binary by hash (GET /Marti/sync/content?hash=...).
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class MapVisibility(Base):
    """Singleton (id=1) — admin-controlled global filter for what shows on
    every connected client. Two independent axes:

      * Map axis (``tactical_objects`` … ``overlays``) — toggles whether a
        category of objects is rendered on the tactical map.
      * Notification axis (``notif_*``) — toggles whether the right-side
        toast cards (chat, FM, alerts, stream events) pop up.

    An ADMIN can hide e.g. CoT tracks on the map without silencing the
    fire-mission radio toasts, and vice versa. Defaults are all-on.
    """

    __tablename__ = "map_visibility"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    # Map axis — what shows on the map canvas.
    tactical_objects: Mapped[bool] = mapped_column(default=True)
    operators: Mapped[bool] = mapped_column(default=True)
    fire_missions: Mapped[bool] = mapped_column(default=True)
    alerts: Mapped[bool] = mapped_column(default=True)
    reports: Mapped[bool] = mapped_column(default=True)
    cot_tracks: Mapped[bool] = mapped_column(default=True)
    kml_layers: Mapped[bool] = mapped_column(default=True)
    overlays: Mapped[bool] = mapped_column(default=True)
    vehicles: Mapped[bool] = mapped_column(default=True)
    # Notification axis — what pops up as a toast card on the right.
    notif_chat: Mapped[bool] = mapped_column(default=True)
    notif_fire_missions: Mapped[bool] = mapped_column(default=True)
    notif_alerts: Mapped[bool] = mapped_column(default=True)
    notif_streams: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class TacticalObject(Base):
    __tablename__ = "tactical_objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ENEMY, POI, MARKER, ROUTE, ZONE, OBJECTIVE, plus tactical control graphics:
    # ATK_AXIS, DEF_AREA, AMBUSH, BOUNDARY, FLET, FLOT, PHASE_LINE, OBJ_AREA
    type: Mapped[str] = mapped_column(String(40))
    symbol_code: Mapped[str] = mapped_column(String(40), default="")  # MIL-STD-2525
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    # latitude/longitude is the anchor point; for line/polygon graphics it's the
    # first vertex (used by simple list views and clustering). The full geometry
    # — if any — lives in `geometry` as a JSON string.
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(
        String(20), default="COMPANY"
    )  # TEAM, SECTION, PLATOON, COMPANY
    photo_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("photos.id"), nullable=True
    )
    # Heading in degrees clockwise from north (0..360) for oriented point symbols
    # (attack axis, ambush V, defense U). 0 = symbol points north.
    rotation: Mapped[float] = mapped_column(Float, default=0.0)
    # GeoJSON-ish: {"type":"point|line|polygon","coords":[[lat,lon],...]}.
    # Empty string = treat as point at (latitude, longitude).
    geometry: Mapped[str] = mapped_column(Text, default="")
    # NATO unit echelon: "" (none), "TM", "SEC", "PL", "COY", "BN", "BDE".
    # Rendered as size designator (dots/bars) above point symbols, or as a
    # text label on line/polygon graphics.
    echelon: Mapped[str] = mapped_column(String(8), default="")
    # NATO affiliation for tactical control graphics colour rule.
    # FRIENDLY (blue), ENEMY (red), UNKNOWN (yellow). Default FRIENDLY.
    affiliation: Mapped[str] = mapped_column(String(12), default="FRIENDLY")
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )


class CotTrack(Base):
    """Live CoT entity received via POST /cot from a non-operator (foreign) UID.

    Upserted on every receipt; ``cot_uid`` is the CoT event uid field
    (e.g. "SIM.HOT-INF-1").  Shown on the tactical map with the NATO
    mil-symbol that matches the CoT type.
    """

    __tablename__ = "cot_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    cot_uid: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    cot_type: Mapped[str] = mapped_column(String(40))
    callsign: Mapped[str] = mapped_column(String(60), default="")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    hae: Mapped[float] = mapped_column(Float, default=0.0)
    speed: Mapped[float] = mapped_column(Float, default=0.0)
    course: Mapped[float] = mapped_column(Float, default=0.0)
    team: Mapped[str] = mapped_column(String(60), default="")
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class AtakShape(Base):
    """ATAK-drawn map annotation (route, line, area) received over CoT TCP."""

    __tablename__ = "atak_shapes"

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    cot_type: Mapped[str] = mapped_column(String(40), default="")
    shape_type: Mapped[str] = mapped_column(String(20), default="LINE")
    title: Mapped[str] = mapped_column(String(200), default="")
    callsign: Mapped[str] = mapped_column(String(80), default="")
    geometry_json: Mapped[str] = mapped_column(Text, default="")
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # TIC, MEDICAL, EVAC, LOST_COMMS
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    operator: Mapped["Operator"] = relationship()
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    receiver_id: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )
    group_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    message_type: Mapped[str] = mapped_column(String(30), default="DIRECT")
    photo_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("photos.id"), nullable=True
    )
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    # ROOM messages target a ChatRoom; DIRECT uses receiver_id; BROADCAST targets all.
    chatroom_id: Mapped[int | None] = mapped_column(
        ForeignKey("chatrooms.id"), nullable=True
    )


class ChatRoom(Base):
    """A named multi-operator chat room with an explicit membership list.

    Maps 1:1 to an ATAK GeoChat named chatroom (room name == ChatRoom.name).
    Messages with message_type=ROOM are delivered to the room's members.
    """

    __tablename__ = "chatrooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    # Origin tag so an ATAK-created room is distinguishable from a native one.
    origin: Mapped[str] = mapped_column(String(10), default="ARROW")  # ARROW | ATAK

    members: Mapped[list["ChatRoomMember"]] = relationship(
        back_populates="chatroom",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ChatRoomMember(Base):
    __tablename__ = "chatroom_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    chatroom_id: Mapped[int] = mapped_column(
        ForeignKey("chatrooms.id", ondelete="CASCADE"), index=True
    )
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)

    chatroom: Mapped["ChatRoom"] = relationship(back_populates="members")


class Battle(Base):
    __tablename__ = "battles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class FireMission(Base):
    """Artillery / mortar call-for-fire request."""

    __tablename__ = "fire_missions"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude: Mapped[float] = mapped_column(Float, default=0.0)  # metres MSL
    direction: Mapped[float] = mapped_column(Float)  # azimuth °
    mission_type: Mapped[str] = mapped_column(String(30))  # ADJUST_FIRE etc.
    ammunition: Mapped[str] = mapped_column(String(40))  # HE / ILLUM / SMOKE …
    quantity: Mapped[int] = mapped_column(default=1)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    fdc_operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(
        String(40)
    )  # CONTACT, SPOT, CASEVAC, MEDEVAC, CAS
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    payload: Mapped[str] = mapped_column(Text)  # JSON-encoded structured data
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    # Status lifecycle managed by BC/ADMIN; sent back to originating operator via WS
    status: Mapped[str] = mapped_column(String(20), default="RECEIVED")
    reviewer_note: Mapped[str] = mapped_column(Text, default="")
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    # CAS-specific: Forward Observer assignment and Troops-In-Contact priority flag
    fo_operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )
    tic: Mapped[bool] = mapped_column(default=False)


class ReportPhoto(Base):
    """Junction table linking zero-or-more photos to a report."""

    __tablename__ = "report_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id"))
    attached_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class CasAsset(Base):
    """CAS platform available in the battlespace — timeslot-based capacity management.

    Status lifecycle: AVAILABLE → ON_STATION → TASKED → RTB → UNAVAILABLE.
    BC/ADMIN creates and updates assets; operators read the list to pick an asset
    when submitting a CAS 9-liner request.
    """

    __tablename__ = "cas_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    callsign: Mapped[str] = mapped_column(String(60))
    aircraft_type: Mapped[str] = mapped_column(
        String(60), default=""
    )  # A-10, F-16, AH-64 …
    ordnance: Mapped[str] = mapped_column(Text, default="")  # e.g. "2×GBU-12, 20mm×500"
    frequency: Mapped[str] = mapped_column(String(40), default="")  # primary radio freq
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE")
    # Availability window — both nullable (open-ended slot)
    available_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    available_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class AuditLog(Base):
    """Immutable security event log — CSF 2.0 DE.CM / GV.OV."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    outcome: Mapped[str] = mapped_column(String(10))  # SUCCESS | FAILURE
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )
    resource: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )  # e.g. "operator:5"
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class MapSnapshot(Base):
    """Frozen JSON snapshot of every TacticalObject at the moment of capture.

    Used by `POST /admin/map/reset` so admins can wipe the live map and
    later restore any past state with `POST /admin/map/snapshots/{id}/restore`.
    """

    __tablename__ = "map_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text)  # JSON list of TacticalObjectOut dicts


class Opord(Base):
    """Operation Order — five-paragraph NATO/US OPORD with map snapshots.

    Each paragraph block is stored as a JSON string so the doctrinal
    sub-fields (OAKOC, CDS, DRAW-D, ASCOPE, CCIR, PACE, supply classes,
    succession, etc.) can evolve without schema migrations. ``map_snapshots``
    holds a list of {id, label, bbox, center, zoom, photo_id, annotations}
    where ``photo_id`` references the existing ``photos`` table for the PNG.
    """

    __tablename__ = "opords"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    opord_number: Mapped[str] = mapped_column(String(40), default="")
    dtg: Mapped[str] = mapped_column(String(40), default="")
    time_zone: Mapped[str] = mapped_column(String(8), default="ZULU")
    classification: Mapped[str] = mapped_column(String(40), default="UNCLASSIFIED")
    references: Mapped[str] = mapped_column(Text, default="")
    task_organization: Mapped[str] = mapped_column(Text, default="")

    situation: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    mission: Mapped[str] = mapped_column(Text, default="")
    execution: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    sustainment: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    command_signal: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    map_snapshots: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    # Frozen layer-export envelopes (overlays/KML/OSINT) — keeps the order
    # self-contained: {id, kind, source_id, name, envelope}. See backend.layers.
    attached_layers: Mapped[str] = mapped_column(Text, default="[]")  # JSON list

    status: Mapped[str] = mapped_column(
        String(20), default="DRAFT"
    )  # DRAFT | PUBLISHED
    author_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    battle_id: Mapped[int | None] = mapped_column(
        ForeignKey("battles.id"), nullable=True
    )
    recipient_ids: Mapped[str] = mapped_column(
        Text, default="[]"
    )  # JSON list of operator ids
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ApkDistConfig(Base):
    """Admin-configured location of the Android APK to distribute.

    Singleton row (id=1). The APK lives either on a locally-mounted path
    (LOCAL — covers OS-mounted NFS shares) or on an SMB server reached
    directly over the wire (SMB — requires ``smbprotocol``).
    """

    __tablename__ = "apk_dist_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    kind: Mapped[str] = mapped_column(String(10), default="LOCAL")  # LOCAL | SMB
    host: Mapped[str] = mapped_column(String(255), default="")  # SMB only
    share: Mapped[str] = mapped_column(String(255), default="")  # SMB only
    path: Mapped[str] = mapped_column(
        String(1024), default=""
    )  # LOCAL: filesystem path (file or dir); SMB: path within share
    filename: Mapped[str] = mapped_column(String(255), default="arrow.apk")
    username: Mapped[str] = mapped_column(String(255), default="")  # SMB only
    password: Mapped[str] = mapped_column(
        String(255), default=""
    )  # SMB only (stored as-is — admin-only access)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Overlay(Base):
    """Named, persisted bundle of TacticalObject ids — reusable map view.

    Operators on the web build an overlay by picking a set of tactical objects
    (enemies / POIs / objectives / tactical control graphics) and saving them
    under a name. The same overlay can be re-applied later, and multiple
    overlays can be selected together — the active set is the union of their
    member ids. ``object_ids`` is JSON to avoid an N-row join-table for what is
    typically a small membership list.
    """

    __tablename__ = "overlays"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )
    object_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of int


class KmlLayer(Base):
    """Imported KML/KMZ file flattened into a JSON feature collection.

    ``features`` is a JSON string of {type, name, description, style, coords}
    entries shared verbatim by the web (Leaflet) and Android (OSMdroid)
    clients so neither needs to parse XML.
    """

    __tablename__ = "kml_layers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    visible: Mapped[bool] = mapped_column(default=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    features: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    bbox: Mapped[str] = mapped_column(
        Text, default=""
    )  # "minLon,minLat,maxLon,maxLat" or ""
    raw_kml: Mapped[str] = mapped_column(
        Text, default=""
    )  # original XML for re-download


class SystemSetting(Base):
    """Generic admin-editable key-value store for runtime configuration.

    Keys are namespaced by convention: ``octopus.url``, ``octopus.api_key``, …
    Values stored in DB always override the same key from config.xml.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class OctopusDetection(Base):
    """Detection event received from the Octopus webhook."""

    __tablename__ = "octopus_detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    stream_id: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(default=0.0)
    description: Mapped[str] = mapped_column(Text, default="")
    bbox: Mapped[str] = mapped_column(Text, default="[]")  # JSON [x1,y1,x2,y2]
    snapshot_url: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ExternalStream(Base):
    """Operator-registered external video stream URL.

    Types: ``mjpeg`` (HTTP MJPEG), ``hls`` (HLS .m3u8), ``video`` (direct MP4/WebM URL).
    """

    __tablename__ = "external_streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(500))
    stream_type: Mapped[str] = mapped_column(String(20))  # mjpeg | hls | video
    description: Mapped[str] = mapped_column(String(300), default="")
    added_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class StreamRecording(Base):
    """Persisted record of an Android-produced video stream.

    Frames are stored on disk as a single concatenated file:
        [u32_be timestamp_ms_offset][u32_be jpeg_size][jpeg_bytes]  …

    Always replayable as motion-JPEG via /streams/recordings/{id}/playback.
    """

    __tablename__ = "stream_recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(120), index=True)
    callsign: Mapped[str] = mapped_column(String(40))
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(255))


class LogrepRoute(Base):
    """Routing record for a LOGREP report — tracks which staff branches received
    it and their feedback.

    Destinations are free-form labels (S1, S2, S3, S4, COY_A, COY_B …) so that
    any order of battle can be represented without schema changes.
    Lifecycle: PENDING → ACKNOWLEDGED → FEEDBACK.
    """

    __tablename__ = "logrep_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    destination: Mapped[str] = mapped_column(String(40))  # S1, S2, COY_A …
    routed_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    routed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    feedback_text: Mapped[str] = mapped_column(Text, default="")
    feedback_by: Mapped[str] = mapped_column(String(80), default="")  # callsign
    feedback_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StrikePackage(Base):
    """Composite tactical plan bundling all assets for a kinetic operation.

    Assets (drones, ISR, air support, sniper overwatch, EW, comms, assault plan,
    exfil routes) are stored as a single JSON blob in ``assets`` so the schema
    can evolve without migrations. Links to existing Arrow objects (operators,
    tactical objects, fire missions, reports) are stored as JSON id lists.

    Lifecycle: PLANNING → ACTIVE → COMPLETE (or ABORTED).
    """

    __tablename__ = "strike_packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="PLANNING")
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )
    target_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_description: Mapped[str] = mapped_column(Text, default="")
    # JSON id lists — links to existing Arrow objects in the same mission
    operator_ids: Mapped[str] = mapped_column(Text, default="[]")
    tactical_object_ids: Mapped[str] = mapped_column(Text, default="[]")
    fire_mission_ids: Mapped[str] = mapped_column(Text, default="[]")
    report_ids: Mapped[str] = mapped_column(Text, default="[]")
    vehicle_ids: Mapped[str] = mapped_column(Text, default="[]")
    # Full asset manifest — JSON-encoded PackageAssets structure
    assets: Mapped[str] = mapped_column(Text, default="{}")


class CopDocument(Base):
    """Uploaded supporting document for the Common Operational Picture.

    Accepts .docx / .doc and .txt files. Content is stored as raw bytes so
    no external filesystem dependency is introduced. TXT content is also
    mirrored in ``text_preview`` for in-browser display without a download.
    """

    __tablename__ = "cop_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(20))  # TXT or WORD
    file_data: Mapped[bytes] = mapped_column(LargeBinary)
    text_preview: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )


# ── LOGCOP ────────────────────────────────────────────────────────────────────


class LogcopSupply(Base):
    """Supply status for one NATO Class of Supply, scoped to a mission."""

    __tablename__ = "logcop_supply"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    class_code: Mapped[str] = mapped_column(
        String(6)
    )  # I II III IIIA IV V VI VII VIII IX X
    label: Mapped[str] = mapped_column(String(120))
    current_qty: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(20), default="DOS")
    threshold_amber: Mapped[float] = mapped_column(Float, default=2.0)
    threshold_red: Mapped[float] = mapped_column(Float, default=1.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )


class LogcopVehicle(Base):
    """FMC / PMC / NMC vehicle status per unit."""

    __tablename__ = "logcop_vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    unit_name: Mapped[str] = mapped_column(String(80))
    vehicle_type: Mapped[str] = mapped_column(String(80))
    total: Mapped[int] = mapped_column(Integer, default=0)
    fmc: Mapped[int] = mapped_column(Integer, default=0)  # Fully Mission Capable
    pmc: Mapped[int] = mapped_column(Integer, default=0)  # Partially Mission Capable
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )


class LogcopConvoy(Base):
    """LOGPAC / convoy status."""

    __tablename__ = "logcop_convoys"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    callsign: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="LOADING")
    # EN_ROUTE | LOADING | DELIVERED | DELAYED | CANCELLED
    cargo: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(120), default="")
    destination: Mapped[str] = mapped_column(String(120), default="")
    eta: Mapped[str] = mapped_column(String(20), default="")  # "HH:MMZ"
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )


class LogcopSupplyPoint(Base):
    """Geographic supply point on the LOGCOP map (BSA, FARP, AMMO dump, etc.)."""

    __tablename__ = "logcop_supply_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120))
    point_type: Mapped[str] = mapped_column(String(20))
    # BSA | FARP | CTCP | AMMO_DUMP | FUEL_POINT | MED_POST | FSC | MSR
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("operators.id"), nullable=True
    )


# ── EPIC — Intelligence Analysis Workboard ────────────────────────────────────


class EpicProject(Base):
    """An analyst-defined intelligence collection project (corkboard)."""

    __tablename__ = "epic_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="#388bfd")
    status: Mapped[str] = mapped_column(
        String(20), default="ACTIVE"
    )  # ACTIVE | ARCHIVED
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    mission_id: Mapped[int | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True
    )
    nodes: Mapped[list["EpicNode"]] = relationship(
        "EpicNode", back_populates="project", cascade="all,delete-orphan"
    )
    links: Mapped[list["EpicLink"]] = relationship(
        "EpicLink", back_populates="project", cascade="all,delete-orphan"
    )


class EpicNode(Base):
    """A card pinned on an EpicProject canvas — wraps a Report, Photo, or is standalone."""

    __tablename__ = "epic_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("epic_projects.id"), nullable=False
    )
    node_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # REPORT | PHOTO | ALERT | NOTE | ENTITY
    x: Mapped[float] = mapped_column(Float, default=100.0)
    y: Mapped[float] = mapped_column(Float, default=100.0)
    # Cross-references (mutually exclusive — only one is set)
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("reports.id"), nullable=True
    )
    photo_id: Mapped[int | None] = mapped_column(ForeignKey("photos.id"), nullable=True)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id"), nullable=True)
    # Standalone content (NOTE / ENTITY)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # PERSON | VEHICLE | LOCATION | ORG
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string[]
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    project: Mapped["EpicProject"] = relationship("EpicProject", back_populates="nodes")


class EpicLink(Base):
    """A directed relationship between two EpicNode cards."""

    __tablename__ = "epic_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("epic_projects.id"), nullable=False
    )
    source_node_id: Mapped[int] = mapped_column(
        ForeignKey("epic_nodes.id"), nullable=False
    )
    target_node_id: Mapped[int] = mapped_column(
        ForeignKey("epic_nodes.id"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    link_type: Mapped[str] = mapped_column(String(30), default="RELATED")
    # RELATED | CONFIRMS | CONTRADICTS | OBSERVED_AT | ASSOCIATED_WITH | PHOTOGRAPHED_AT
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    project: Mapped["EpicProject"] = relationship("EpicProject", back_populates="links")
