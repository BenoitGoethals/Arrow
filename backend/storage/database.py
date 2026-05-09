from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config.xml_config import load_config

_cfg = load_config()
engine = create_engine(
    _cfg.database.url,
    connect_args={"check_same_thread": False} if _cfg.database.url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _migrate(conn: object) -> None:
    """Apply additive schema migrations that create_all cannot handle."""
    migrations = [
        "CREATE TABLE IF NOT EXISTS photos ("
        "  id INTEGER PRIMARY KEY, filename VARCHAR(255) NOT NULL,"
        "  original_name VARCHAR(255) DEFAULT '',"
        "  mime_type VARCHAR(80) DEFAULT 'image/jpeg',"
        "  uploaded_by INTEGER REFERENCES operators(id),"
        "  timestamp DATETIME"
        ")",
        "ALTER TABLE messages ADD COLUMN photo_id INTEGER REFERENCES photos(id)",
        "ALTER TABLE tactical_objects ADD COLUMN photo_id INTEGER REFERENCES photos(id)",
        # account lockout
        "ALTER TABLE operators ADD COLUMN failed_login_count INTEGER DEFAULT 0",
        "ALTER TABLE operators ADD COLUMN locked_until DATETIME",
        # TOTP MFA
        "ALTER TABLE operators ADD COLUMN totp_secret VARCHAR(64)",
        "ALTER TABLE operators ADD COLUMN mfa_enabled BOOLEAN DEFAULT 0",
        # Report status lifecycle
        "ALTER TABLE reports ADD COLUMN status VARCHAR(20) DEFAULT 'RECEIVED'",
        "ALTER TABLE reports ADD COLUMN reviewer_note TEXT DEFAULT ''",
        # Tactical control graphics — rotation for point symbols, full geometry
        # for lines/polygons (FLET, FLOT, boundaries, AOs, etc.)
        "ALTER TABLE tactical_objects ADD COLUMN rotation FLOAT DEFAULT 0",
        "ALTER TABLE tactical_objects ADD COLUMN geometry TEXT DEFAULT ''",
        # NATO echelon designator (TM/SEC/PL/COY/BN/BDE) for tactical graphics
        "ALTER TABLE tactical_objects ADD COLUMN echelon VARCHAR(8) DEFAULT ''",
        # Map reset/restore snapshots — JSON-frozen list of tactical objects
        "CREATE TABLE IF NOT EXISTS map_snapshots ("
        "  id INTEGER PRIMARY KEY,"
        "  name VARCHAR(120) DEFAULT '',"
        "  created_by INTEGER REFERENCES operators(id),"
        "  created_at DATETIME,"
        "  object_count INTEGER DEFAULT 0,"
        "  payload TEXT NOT NULL"
        ")",
    ]
    for sql in migrations:
        try:
            conn.execute(__import__("sqlalchemy").text(sql))
        except Exception:
            pass  # column/table already exists — safe to skip


def init_db() -> None:
    from backend.storage import models  # noqa: F401  — register mappers

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _migrate(conn)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
