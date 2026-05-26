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
        # NATO affiliation (FRIENDLY/ENEMY/UNKNOWN) so every TG type can be
        # drawn as either side; color follows affiliation, not type.
        "ALTER TABLE tactical_objects ADD COLUMN affiliation VARCHAR(12) DEFAULT 'FRIENDLY'",
        # Map reset/restore snapshots — JSON-frozen list of tactical objects
        "CREATE TABLE IF NOT EXISTS map_snapshots ("
        "  id INTEGER PRIMARY KEY,"
        "  name VARCHAR(120) DEFAULT '',"
        "  created_by INTEGER REFERENCES operators(id),"
        "  created_at DATETIME,"
        "  object_count INTEGER DEFAULT 0,"
        "  payload TEXT NOT NULL"
        ")",
        # Saved overlays — reusable named bundles of TacticalObject ids
        "CREATE TABLE IF NOT EXISTS overlays ("
        "  id INTEGER PRIMARY KEY,"
        "  name VARCHAR(160) NOT NULL,"
        "  description TEXT DEFAULT '',"
        "  created_by INTEGER REFERENCES operators(id),"
        "  created_at DATETIME,"
        "  updated_at DATETIME,"
        "  object_ids TEXT DEFAULT '[]'"
        ")",
        # Imported KML layers shared between web (Leaflet) and Android (OSMdroid)
        "CREATE TABLE IF NOT EXISTS kml_layers ("
        "  id INTEGER PRIMARY KEY,"
        "  name VARCHAR(160) NOT NULL,"
        "  description TEXT DEFAULT '',"
        "  visible BOOLEAN DEFAULT 1,"
        "  uploaded_by INTEGER REFERENCES operators(id),"
        "  uploaded_at DATETIME,"
        "  feature_count INTEGER DEFAULT 0,"
        "  features TEXT DEFAULT '[]',"
        "  bbox TEXT DEFAULT '',"
        "  raw_kml TEXT DEFAULT ''"
        ")",
        # Auto-saved video stream recordings
        "CREATE TABLE IF NOT EXISTS stream_recordings ("
        "  id INTEGER PRIMARY KEY,"
        "  stream_id VARCHAR(120) NOT NULL,"
        "  callsign VARCHAR(40) NOT NULL DEFAULT '',"
        "  operator_id INTEGER REFERENCES operators(id),"
        "  started_at DATETIME NOT NULL,"
        "  ended_at DATETIME,"
        "  frame_count INTEGER DEFAULT 0,"
        "  byte_size INTEGER DEFAULT 0,"
        "  file_path VARCHAR(255) NOT NULL"
        ")",
        # Operator position history — every GPS fix saved for track replay and analytics
        "CREATE TABLE IF NOT EXISTS operator_positions ("
        "  id INTEGER PRIMARY KEY,"
        "  operator_id INTEGER NOT NULL REFERENCES operators(id) ON DELETE CASCADE,"
        "  latitude FLOAT NOT NULL,"
        "  longitude FLOAT NOT NULL,"
        "  altitude FLOAT,"
        "  recorded_at DATETIME"
        ")",
        "CREATE INDEX IF NOT EXISTS ix_op_pos_operator_id ON operator_positions(operator_id)",
        "CREATE INDEX IF NOT EXISTS ix_op_pos_recorded_at ON operator_positions(recorded_at)",
        # Map-visibility singleton — admin-controlled per-category filter
        "CREATE TABLE IF NOT EXISTS map_visibility ("
        "  id INTEGER PRIMARY KEY,"
        "  tactical_objects BOOLEAN DEFAULT 1,"
        "  operators        BOOLEAN DEFAULT 1,"
        "  fire_missions    BOOLEAN DEFAULT 1,"
        "  alerts           BOOLEAN DEFAULT 1,"
        "  reports          BOOLEAN DEFAULT 1,"
        "  cot_tracks       BOOLEAN DEFAULT 1,"
        "  kml_layers       BOOLEAN DEFAULT 1,"
        "  overlays         BOOLEAN DEFAULT 1,"
        "  updated_at       DATETIME"
        ")",
        "INSERT OR IGNORE INTO map_visibility (id, updated_at) "
        "VALUES (1, datetime('now'))",
        # Notification-axis flags — added on top of the original map-axis row
        "ALTER TABLE map_visibility ADD COLUMN notif_chat          BOOLEAN DEFAULT 1",
        "ALTER TABLE map_visibility ADD COLUMN notif_fire_missions BOOLEAN DEFAULT 1",
        "ALTER TABLE map_visibility ADD COLUMN notif_alerts        BOOLEAN DEFAULT 1",
        "ALTER TABLE map_visibility ADD COLUMN notif_streams       BOOLEAN DEFAULT 1",
        # ── Missions ──────────────────────────────────────────────────────────
        "CREATE TABLE IF NOT EXISTS missions ("
        "  id INTEGER PRIMARY KEY,"
        "  name VARCHAR(160) NOT NULL,"
        "  description TEXT DEFAULT '',"
        "  status VARCHAR(20) DEFAULT 'PLANNING',"
        "  created_by INTEGER REFERENCES operators(id),"
        "  created_at DATETIME,"
        "  started_at DATETIME,"
        "  ended_at   DATETIME,"
        "  snapshot   TEXT DEFAULT '',"
        "  snapshot_at DATETIME"
        ")",
        "ALTER TABLE tactical_objects ADD COLUMN mission_id INTEGER REFERENCES missions(id)",
        "ALTER TABLE alerts           ADD COLUMN mission_id INTEGER REFERENCES missions(id)",
        "ALTER TABLE fire_missions    ADD COLUMN mission_id INTEGER REFERENCES missions(id)",
        "ALTER TABLE messages         ADD COLUMN mission_id INTEGER REFERENCES missions(id)",
        "ALTER TABLE reports          ADD COLUMN mission_id INTEGER REFERENCES missions(id)",
        "ALTER TABLE operators        ADD COLUMN mission_id INTEGER REFERENCES missions(id)",
        "ALTER TABLE missions ADD COLUMN map_center_lat FLOAT",
        "ALTER TABLE missions ADD COLUMN map_center_lng FLOAT",
        "ALTER TABLE missions ADD COLUMN map_zoom INTEGER DEFAULT 13",
        # Single-device session enforcement
        "ALTER TABLE operators ADD COLUMN session_jti VARCHAR(36)",
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
