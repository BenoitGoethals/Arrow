from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
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

    id:             Mapped[int]           = mapped_column(primary_key=True)
    name:           Mapped[str]           = mapped_column(String(160))
    description:    Mapped[str]           = mapped_column(Text, default="")
    status:         Mapped[str]           = mapped_column(String(20), default="PLANNING")
    created_by:     Mapped[int]           = mapped_column(ForeignKey("operators.id"))
    created_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at:     Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at:       Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot:       Mapped[str]           = mapped_column(Text, default="")
    snapshot_at:    Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    map_center_lat: Mapped[float|None]    = mapped_column(Float, nullable=True)
    map_center_lng: Mapped[float|None]    = mapped_column(Float, nullable=True)
    map_zoom:       Mapped[int]           = mapped_column(Integer, default=13)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)

    platoons: Mapped[list["Platoon"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Platoon(Base):
    __tablename__ = "platoons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))

    company: Mapped[Company] = relationship(back_populates="platoons")
    sections: Mapped[list["Section"]] = relationship(back_populates="platoon", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    platoon_id: Mapped[int] = mapped_column(ForeignKey("platoons.id"))

    platoon: Mapped[Platoon] = relationship(back_populates="sections")
    teams: Mapped[list["Team"]] = relationship(back_populates="section", cascade="all, delete-orphan")


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
    status: Mapped[str] = mapped_column(String(20), default="OFFLINE")
    role: Mapped[str] = mapped_column(String(20), default="OPERATOR")  # ADMIN, BATTLE_CAPTAIN, OPERATOR
    password_hash: Mapped[str] = mapped_column(String(255))

    team_id:    Mapped[int | None] = mapped_column(ForeignKey("teams.id"),    nullable=True)
    mission_id: Mapped[int | None] = mapped_column(ForeignKey("missions.id"), nullable=True)

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Account lockout (A04)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # TOTP MFA (PR.AA)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(default=False)

    team: Mapped[Team | None] = relationship(back_populates="operators")
    positions: Mapped[list["OperatorPosition"]] = relationship(
        back_populates="operator", cascade="all, delete-orphan", passive_deletes=True,
    )


class OperatorPosition(Base):
    """Time-series of every GPS fix received from an operator.

    The Operator row still holds the *current* position for fast live queries.
    This table keeps the full history for track visualisation and behaviour analytics.
    """
    __tablename__ = "operator_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), index=True,
    )
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True,
    )

    operator: Mapped["Operator"] = relationship(back_populates="positions")


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str] = mapped_column(String(80), default="image/jpeg")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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

    id:               Mapped[int]  = mapped_column(primary_key=True, default=1)
    # Map axis — what shows on the map canvas.
    tactical_objects: Mapped[bool] = mapped_column(default=True)
    operators:        Mapped[bool] = mapped_column(default=True)
    fire_missions:    Mapped[bool] = mapped_column(default=True)
    alerts:           Mapped[bool] = mapped_column(default=True)
    reports:          Mapped[bool] = mapped_column(default=True)
    cot_tracks:       Mapped[bool] = mapped_column(default=True)
    kml_layers:       Mapped[bool] = mapped_column(default=True)
    overlays:         Mapped[bool] = mapped_column(default=True)
    # Notification axis — what pops up as a toast card on the right.
    notif_chat:          Mapped[bool] = mapped_column(default=True)
    notif_fire_missions: Mapped[bool] = mapped_column(default=True)
    notif_alerts:        Mapped[bool] = mapped_column(default=True)
    notif_streams:       Mapped[bool] = mapped_column(default=True)
    updated_at:       Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow,
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
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    notes: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(20), default="COMPANY")  # TEAM, SECTION, PLATOON, COMPANY
    photo_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("photos.id"), nullable=True)
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
    affiliation: Mapped[str]           = mapped_column(String(12), default="FRIENDLY")
    mission_id:  Mapped[int | None]    = mapped_column(ForeignKey("missions.id"), nullable=True)


class CotTrack(Base):
    """Live CoT entity received via POST /cot from a non-operator (foreign) UID.

    Upserted on every receipt; ``cot_uid`` is the CoT event uid field
    (e.g. "SIM.HOT-INF-1").  Shown on the tactical map with the NATO
    mil-symbol that matches the CoT type.
    """
    __tablename__ = "cot_tracks"

    id:         Mapped[int]           = mapped_column(primary_key=True)
    cot_uid:    Mapped[str]           = mapped_column(String(120), unique=True, index=True)
    cot_type:   Mapped[str]           = mapped_column(String(40))
    callsign:   Mapped[str]           = mapped_column(String(60),  default="")
    latitude:   Mapped[float]         = mapped_column(Float)
    longitude:  Mapped[float]         = mapped_column(Float)
    hae:        Mapped[float]         = mapped_column(Float,        default=0.0)
    speed:      Mapped[float]         = mapped_column(Float,        default=0.0)
    course:     Mapped[float]         = mapped_column(Float,        default=0.0)
    team:       Mapped[str]           = mapped_column(String(60),  default="")
    last_seen:  Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # TIC, MEDICAL, EVAC, LOST_COMMS
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    status:     Mapped[str]         = mapped_column(String(20), default="ACTIVE")
    mission_id: Mapped[int | None]  = mapped_column(ForeignKey("missions.id"), nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    receiver_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    message_type: Mapped[str]         = mapped_column(String(30), default="DIRECT")
    photo_id:     Mapped[int | None]  = mapped_column(Integer, ForeignKey("photos.id"), nullable=True)
    mission_id:   Mapped[int | None]  = mapped_column(ForeignKey("missions.id"), nullable=True)


class Battle(Base):
    __tablename__ = "battles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class FireMission(Base):
    """Artillery / mortar call-for-fire request."""
    __tablename__ = "fire_missions"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    operator_id:    Mapped[int]         = mapped_column(ForeignKey("operators.id"))
    latitude:       Mapped[float]       = mapped_column(Float)
    longitude:      Mapped[float]       = mapped_column(Float)
    altitude:       Mapped[float]       = mapped_column(Float, default=0.0)   # metres MSL
    direction:      Mapped[float]       = mapped_column(Float)                # azimuth °
    mission_type:   Mapped[str]         = mapped_column(String(30))           # ADJUST_FIRE etc.
    ammunition:     Mapped[str]         = mapped_column(String(40))           # HE / ILLUM / SMOKE …
    quantity:       Mapped[int]         = mapped_column(default=1)
    description:    Mapped[str]         = mapped_column(Text, default="")
    status:         Mapped[str]         = mapped_column(String(20), default="PENDING")
    fdc_operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), nullable=True)
    timestamp:      Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=_utcnow)
    notes:          Mapped[str]         = mapped_column(Text, default="")
    mission_id:     Mapped[int | None]  = mapped_column(ForeignKey("missions.id"), nullable=True)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # CONTACT, SPOT, CASEVAC, MEDEVAC, CAS
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    payload: Mapped[str] = mapped_column(Text)  # JSON-encoded structured data
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Status lifecycle managed by BC/ADMIN; sent back to originating operator via WS
    status: Mapped[str] = mapped_column(String(20), default="RECEIVED")
    reviewer_note: Mapped[str]        = mapped_column(Text, default="")
    mission_id:    Mapped[int | None] = mapped_column(ForeignKey("missions.id"), nullable=True)


class AuditLog(Base):
    """Immutable security event log — CSF 2.0 DE.CM / GV.OV."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    outcome: Mapped[str] = mapped_column(String(10))          # SUCCESS | FAILURE
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), nullable=True)
    resource: Mapped[str | None] = mapped_column(String(120), nullable=True)  # e.g. "operator:5"
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class MapSnapshot(Base):
    """Frozen JSON snapshot of every TacticalObject at the moment of capture.

    Used by `POST /admin/map/reset` so admins can wipe the live map and
    later restore any past state with `POST /admin/map/snapshots/{id}/restore`.
    """
    __tablename__ = "map_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text)   # JSON list of TacticalObjectOut dicts


class Opord(Base):
    """Operation Order — five-paragraph NATO/US OPORD with map snapshots.

    Each paragraph block is stored as a JSON string so the doctrinal
    sub-fields (OAKOC, CDS, DRAW-D, ASCOPE, CCIR, PACE, supply classes,
    succession, etc.) can evolve without schema migrations. ``map_snapshots``
    holds a list of {id, label, bbox, center, zoom, photo_id, annotations}
    where ``photo_id`` references the existing ``photos`` table for the PNG.
    """
    __tablename__ = "opords"

    id:                Mapped[int]      = mapped_column(primary_key=True)
    title:             Mapped[str]      = mapped_column(String(200))
    opord_number:      Mapped[str]      = mapped_column(String(40), default="")
    dtg:               Mapped[str]      = mapped_column(String(40), default="")
    time_zone:         Mapped[str]      = mapped_column(String(8), default="ZULU")
    classification:    Mapped[str]      = mapped_column(String(40), default="UNCLASSIFIED")
    references:        Mapped[str]      = mapped_column(Text, default="")
    task_organization: Mapped[str]      = mapped_column(Text, default="")

    situation:      Mapped[str]         = mapped_column(Text, default="{}")     # JSON
    mission:        Mapped[str]         = mapped_column(Text, default="")
    execution:      Mapped[str]         = mapped_column(Text, default="{}")     # JSON
    sustainment:    Mapped[str]         = mapped_column(Text, default="{}")     # JSON
    command_signal: Mapped[str]         = mapped_column(Text, default="{}")     # JSON
    map_snapshots:  Mapped[str]         = mapped_column(Text, default="[]")     # JSON list

    status:        Mapped[str]          = mapped_column(String(20), default="DRAFT")  # DRAFT | PUBLISHED
    author_id:     Mapped[int]          = mapped_column(ForeignKey("operators.id"))
    battle_id:     Mapped[int | None]   = mapped_column(ForeignKey("battles.id"), nullable=True)
    recipient_ids: Mapped[str]          = mapped_column(Text, default="[]")  # JSON list of operator ids
    created_at:    Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at:    Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ApkDistConfig(Base):
    """Admin-configured location of the Android APK to distribute.

    Singleton row (id=1). The APK lives either on a locally-mounted path
    (LOCAL — covers OS-mounted NFS shares) or on an SMB server reached
    directly over the wire (SMB — requires ``smbprotocol``).
    """
    __tablename__ = "apk_dist_config"

    id:        Mapped[int]   = mapped_column(primary_key=True, default=1)
    kind:      Mapped[str]   = mapped_column(String(10), default="LOCAL")   # LOCAL | SMB
    host:      Mapped[str]   = mapped_column(String(255), default="")       # SMB only
    share:     Mapped[str]   = mapped_column(String(255), default="")       # SMB only
    path:      Mapped[str]   = mapped_column(String(1024), default="")      # LOCAL: filesystem path (file or dir); SMB: path within share
    filename:  Mapped[str]   = mapped_column(String(255), default="arrow.apk")
    username:  Mapped[str]   = mapped_column(String(255), default="")       # SMB only
    password:  Mapped[str]   = mapped_column(String(255), default="")       # SMB only (stored as-is — admin-only access)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


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

    id:          Mapped[int]      = mapped_column(primary_key=True)
    name:        Mapped[str]      = mapped_column(String(160))
    description: Mapped[str]      = mapped_column(Text, default="")
    created_by:  Mapped[int]      = mapped_column(ForeignKey("operators.id"))
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow,
    )
    object_ids:  Mapped[str]      = mapped_column(Text, default="[]")   # JSON list of int


class KmlLayer(Base):
    """Imported KML/KMZ file flattened into a JSON feature collection.

    ``features`` is a JSON string of {type, name, description, style, coords}
    entries shared verbatim by the web (Leaflet) and Android (OSMdroid)
    clients so neither needs to parse XML.
    """
    __tablename__ = "kml_layers"

    id:           Mapped[int]      = mapped_column(primary_key=True)
    name:         Mapped[str]      = mapped_column(String(160))
    description:  Mapped[str]      = mapped_column(Text, default="")
    visible:      Mapped[bool]     = mapped_column(default=True)
    uploaded_by:  Mapped[int]      = mapped_column(ForeignKey("operators.id"))
    uploaded_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    feature_count: Mapped[int]     = mapped_column(Integer, default=0)
    features:     Mapped[str]      = mapped_column(Text, default="[]")    # JSON array
    bbox:         Mapped[str]      = mapped_column(Text, default="")      # "minLon,minLat,maxLon,maxLat" or ""
    raw_kml:      Mapped[str]      = mapped_column(Text, default="")      # original XML for re-download


class SystemSetting(Base):
    """Generic admin-editable key-value store for runtime configuration.

    Keys are namespaced by convention: ``octopus.url``, ``octopus.api_key``, …
    Values stored in DB always override the same key from config.xml.
    """
    __tablename__ = "system_settings"

    key:        Mapped[str]      = mapped_column(String(120), primary_key=True)
    value:      Mapped[str]      = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class OctopusDetection(Base):
    """Detection event received from the Octopus webhook."""
    __tablename__ = "octopus_detections"

    id:           Mapped[int]   = mapped_column(primary_key=True)
    event_id:     Mapped[str]   = mapped_column(String(80), unique=True, index=True)
    stream_id:    Mapped[str]   = mapped_column(String(120), index=True)
    label:        Mapped[str]   = mapped_column(String(80))
    confidence:   Mapped[float] = mapped_column(default=0.0)
    description:  Mapped[str]   = mapped_column(Text, default="")
    bbox:         Mapped[str]   = mapped_column(Text, default="[]")   # JSON [x1,y1,x2,y2]
    snapshot_url: Mapped[str]   = mapped_column(Text, default="")
    occurred_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ExternalStream(Base):
    """Operator-registered external video stream URL.

    Types: ``mjpeg`` (HTTP MJPEG), ``hls`` (HLS .m3u8), ``video`` (direct MP4/WebM URL).
    """
    __tablename__ = "external_streams"

    id:          Mapped[int]  = mapped_column(primary_key=True)
    name:        Mapped[str]  = mapped_column(String(120))
    url:         Mapped[str]  = mapped_column(String(500))
    stream_type: Mapped[str]  = mapped_column(String(20))   # mjpeg | hls | video
    description: Mapped[str]  = mapped_column(String(300), default="")
    added_by:    Mapped[int]  = mapped_column(ForeignKey("operators.id"))
    added_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class StreamRecording(Base):
    """Persisted record of an Android-produced video stream.

    Frames are stored on disk as a single concatenated file:
        [u32_be timestamp_ms_offset][u32_be jpeg_size][jpeg_bytes]  …

    Always replayable as motion-JPEG via /streams/recordings/{id}/playback.
    """
    __tablename__ = "stream_recordings"

    id:          Mapped[int]      = mapped_column(primary_key=True)
    stream_id:   Mapped[str]      = mapped_column(String(120), index=True)
    callsign:    Mapped[str]      = mapped_column(String(40))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), nullable=True)
    started_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frame_count: Mapped[int]      = mapped_column(Integer, default=0)
    byte_size:   Mapped[int]      = mapped_column(Integer, default=0)
    file_path:   Mapped[str]      = mapped_column(String(255))
