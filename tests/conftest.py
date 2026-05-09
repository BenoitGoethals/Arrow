"""Shared fixtures for the Arrow test suite."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator, Generator

# ── Set env vars before any backend import ───────────────────────────────────
os.environ["ARROW_INSECURE_SECRET_OK"] = "1"
os.environ["ARROW_JSON_LOGS"]          = "0"
os.environ["ARROW_ALLOWED_ORIGINS"]    = "*"

# ── Disable rate limiting globally for all tests ─────────────────────────────
# Must happen BEFORE any test runs and before the first create_app() call.
# The limiter is a module-level singleton; patching _key_func here makes every
# request use a fresh UUID as its key, so counters never accumulate.
import backend.limiter as _limiter_mod
_limiter_mod.limiter._key_func = lambda request: uuid.uuid4().hex

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient backed by a fresh in-memory SQLite DB per test."""
    from backend.main import create_app
    import backend.storage.database as _dbmod
    from backend.storage.database import Base, get_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,     # single shared connection → tables visible everywhere
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    _seed_admin(engine)           # benoit / ranger14 as ADMIN, directly in DB

    def override_get_db() -> Generator[Session, None, None]:
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    # Reset limiter storage so per-test counters start at zero
    try:
        _limiter_mod.limiter._storage.reset()
    except Exception:
        pass

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    # Some background paths (notably the stream-recording writer in
    # `backend/streams/router.py`) call `SessionLocal()` directly because
    # they're in a long-running WS handler — `Depends(get_db)` would force
    # a single session for the whole connection. Rebind the module-level
    # SessionLocal/engine so those direct calls also hit the test DB.
    saved_engine, saved_session = _dbmod.engine, _dbmod.SessionLocal
    _dbmod.engine, _dbmod.SessionLocal = engine, TestSession

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    _dbmod.engine, _dbmod.SessionLocal = saved_engine, saved_session
    engine.dispose()


def _run_migrations(engine) -> None:
    stmts = [
        "ALTER TABLE operators ADD COLUMN failed_login_count INTEGER DEFAULT 0",
        "ALTER TABLE operators ADD COLUMN locked_until DATETIME",
        "ALTER TABLE operators ADD COLUMN totp_secret VARCHAR(64)",
        "ALTER TABLE operators ADD COLUMN mfa_enabled BOOLEAN DEFAULT 0",
    ]
    with engine.begin() as conn:
        for sql in stmts:
            try:
                conn.execute(text(sql))
            except Exception:
                pass


def _seed_admin(engine) -> None:
    """Insert admin account directly — avoids the chicken-and-egg bootstrap problem."""
    from backend.auth.jwt_auth import hash_password
    pw = hash_password("ranger14")
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT id FROM operators WHERE callsign='benoit'")
        ).first()
        if not exists:
            conn.execute(text(
                "INSERT INTO operators "
                "(callsign,rank,status,role,password_hash,last_seen,"
                " failed_login_count,mfa_enabled) "
                "VALUES ('benoit','OF-3','OFFLINE','ADMIN',:pw,datetime('now'),0,0)"
            ), {"pw": pw})


# ── Shared helpers ─────────────────────────────────────────────────────────────

def admin_token(client: TestClient) -> str:
    r = client.post("/auth/login", data={"username": "benoit", "password": "ranger14"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def register(
    client: TestClient,
    role: str = "OPERATOR",
    password: str = "pw123456",
) -> tuple[str, str, int]:
    callsign = f"T-{uuid.uuid4().hex[:6].upper()}"
    if role == "OPERATOR":
        r = client.post("/auth/register",
                        json={"callsign": callsign, "password": password})
        assert r.status_code == 201, r.text
    else:
        tok = admin_token(client)
        r = client.post("/auth/register/admin",
                        json={"callsign": callsign, "password": password, "role": role},
                        headers=auth(tok))
        assert r.status_code == 201, r.text

    token = r.json()["access_token"]
    op_id = client.get("/auth/me", headers=auth(token)).json()["id"]
    return callsign, token, op_id


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
