from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.storage.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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

    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)

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


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str] = mapped_column(String(80), default="image/jpeg")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # TIC, MEDICAL, EVAC, LOST_COMMS
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE, ACKNOWLEDGED, CLOSED


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    receiver_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    message_type: Mapped[str] = mapped_column(String(30), default="DIRECT")  # DIRECT, GROUP, BROADCAST
    photo_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("photos.id"), nullable=True)


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


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # CONTACT, SPOT, CASEVAC, MEDEVAC, CAS
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    payload: Mapped[str] = mapped_column(Text)  # JSON-encoded structured data
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # Status lifecycle managed by BC/ADMIN; sent back to originating operator via WS
    status: Mapped[str] = mapped_column(String(20), default="RECEIVED")
    reviewer_note: Mapped[str] = mapped_column(Text, default="")


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
