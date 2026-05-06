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
    type: Mapped[str] = mapped_column(String(40))  # ENEMY, POI, MARKER, ROUTE, ZONE
    symbol_code: Mapped[str] = mapped_column(String(40), default="")  # MIL-STD-2525
    created_by: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    notes: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(20), default="COMPANY")  # TEAM, SECTION, PLATOON, COMPANY
    photo_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("photos.id"), nullable=True)


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


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # CONTACT, SPOT, CASEVAC, MEDEVAC, CAS
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    payload: Mapped[str] = mapped_column(Text)  # JSON-encoded structured data
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
