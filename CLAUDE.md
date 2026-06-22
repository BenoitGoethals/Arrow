# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Arrow is a TAK-style situational awareness platform (see `README.md` for the full spec).
The repo contains two Python apps that share a single `pyproject.toml`:

- `backend/` — **FastAPI** REST + WebSocket services, SQLAlchemy on PostgreSQL 16 + PostGIS 3.4, JWT auth, CoT messaging. MapServer serves OGC WMS/WFS from PostGIS views (`ms_*`).
- `web/` — **Flask** operational dashboard (Battle Captain / Admin UI) that talks to the backend over HTTP/WS.
- `android/` — **Kotlin / Jetpack Compose** tactical operator client. Standalone Gradle project (open `android/` in Android Studio, or run `gradle wrapper && ./gradlew :app:assembleDebug`). Uses OkHttp + kotlinx.serialization, OSMdroid for the map, Fused Location Provider in a foreground service. Module split mirrors §12 (`auth/`, `tracking/`, `map/`, `messaging/`, `alerts/`, `reports/`, `cot/`, `offline/`, `settings/`). Composition root is `di/AppContainer.kt`.

Top-level config lives in `config.xml` and is parsed by `backend/config/xml_config.py`.

## Commands

```bash
# Install (Python 3.14+, uv)
uv sync

# Run BOTH services (Flask :6002 + FastAPI :6001) in one command
uv run python run.py
# or
uv run arrow

# Run individually
uv run arrow-backend     # FastAPI on :6001 (OpenAPI at /docs)
uv run arrow-web         # Flask dashboard on :6002

# Tests
uv run pytest
uv run pytest tests/test_cot.py::test_cot_roundtrip   # single test
```

The web app reads the backend URL from the `ARROW_BACKEND_URL` env var (default `http://localhost:6001`). The backend port comes from `config.xml` → `<server><port>`.

## Architecture

### Backend module layout
The backend follows the module split suggested in §12 of the README. Each domain module has its own
APIRouter and is wired into `backend.main:create_app`:

| Module | Responsibility |
| --- | --- |
| `api/` | CRUD routers for hierarchy (companies → platoons → sections → teams → operators) and tactical objects. Pydantic schemas live in `api/schemas.py`. `api/hierarchy.py` exposes `GET /hierarchy` — returns the full Company → Platoon → Section → Team → Operator tree with computed `online` flags (90 s heartbeat window). The web map calls this for the sidebar tree. |
| `auth/` | JWT issuance/validation (`jwt_auth.py`), `/auth/register`, `/auth/login`, `/auth/me`. `require_role(...)` dependency gates admin/battle-captain endpoints. |
| `websocket/` | `ConnectionManager` (`manager.py`) is the single in-process pub/sub broadcaster. All real-time channels (`tracking`, `tactical-object`, `alert`, `chat`, `report`, `presence`) flow through `broadcaster.broadcast(...)`. The `/ws?token=...` endpoint authenticates with the same JWT. |
| `tracking/` | Operator GPS updates → persisted on `Operator` row + broadcast on `tracking` channel. |
| `alerts/` | Emergency alert button (TIC / MEDICAL / EVAC / LOST_COMMS); broadcasts on `alert` channel. |
| `reports/` | Structured tactical reports incl. 9-liners (CASEVAC / MEDEVAC / CAS), payload stored as JSON text. |
| `messaging/` | Direct/group/broadcast chat, persisted + broadcast. |
| `battle_management/` | Battle lifecycle (admin/battle-captain only). |
| `map/` | Tile-source config and offline-zone manifests. |
| `cot/` | Minimal Cursor-on-Target XML encoder/decoder (`cot.py`) for ATAK interoperability. |
| `storage/` | SQLAlchemy `Base`, engine/`SessionLocal`, `init_db`, ORM models for all entities in §13 of the README. |
| `config/` | XML config parser; produces a frozen `AppConfig` dataclass tree. |

### Key cross-cutting patterns

- **Single broadcaster instance.** `backend.websocket.manager.broadcaster` is imported by every router that emits realtime events. If you swap it for a Redis/NATS backend, keep the `connect / disconnect / broadcast` interface so callers don't change (SOLID/pluggable per §11).
- **Auth dependency chain.** `get_current_operator` resolves the JWT → DB-loaded `Operator`. `require_role("ADMIN", ...)` wraps it for role-gated endpoints. Any new endpoint that needs auth should depend on one of these, never decode tokens itself.
- **DB session lifecycle.** Use `Depends(get_db)` in routes; never instantiate `SessionLocal` directly inside handlers. `init_db` is called once from the FastAPI lifespan.
- **Config is read at import time** in `storage/database.py` and `auth/jwt_auth.py` (module-level `load_config()`). When changing `config.xml` during development, restart the process.
- **Pydantic v2 schemas** with `ConfigDict(from_attributes=True)` — return ORM objects directly from routes, FastAPI serialises through the `response_model`.

### Web (Flask) layout
`web/app.py` is the app factory. Each capability area (`dashboard/`, `tactical_map/`, `admin/`) is a Blueprint with its own `routes.py`. The frontend stores the JWT in `localStorage.arrow_token` and calls the backend directly from the browser; the Flask side serves only HTML/CSS/JS shells. The tactical map uses Leaflet (CDN) and opens a single WebSocket to `/ws` for live updates.

## Conventions

- Imports are absolute from the project root (`from backend.xxx import ...`, `from web.xxx import ...`). Don't introduce relative imports — the `pyproject.toml` declares both `backend` and `web` as wheel packages.
- The `Report.payload` column stores JSON as text; serialise with `json.dumps` on write and parse on read.
- New realtime events: emit via `broadcaster.broadcast({"channel": "...", "event": "...", "data": {...}})`. Existing channels: `presence`, `tracking`, `tactical-object`, `alert`, `chat`, `report`.
- New roles must be added to the `Operator.role` set used by `require_role` callers (`ADMIN`, `BATTLE_CAPTAIN`, `OPERATOR`).

## Project Conventions

- Run modules via their package (`python -m backend.storage.seed`), never by file path. File-path execution breaks absolute imports.
- Avoid relative imports — both `backend` and `web` are installed wheel packages; relative imports break `python -m` invocation.

## SQL & Database Conventions

- Before writing any SQL file or production DB artifact, confirm whether the user wants a **full schema + creation script** (DDL for all tables, indexes, extensions) or a **seed-only / generator script**. These are different deliverables; defaulting to the wrong one costs iterations.
- Use ANSI SQL (`CURRENT_TIMESTAMP`, `ON CONFLICT … DO NOTHING`) in migration statements so they work in both the SQLite test fixture and PostgreSQL production. Never use dialect-specific functions (`NOW()`, `datetime('now')`) in shared migration code.

## Testing

- Always run the full test suite (`uv run pytest`) after any database or schema change and confirm all tests pass before declaring the work complete.
- The test fixture in `tests/conftest.py` overrides `_dbmod.engine` and `_dbmod.SessionLocal` with a StaticPool in-memory SQLite engine. Any module that captures `SessionLocal` at import time (e.g. `from backend.storage.database import SessionLocal`) will bypass this override and connect to the wrong database. Always import via the module (`import backend.storage.database as _db; _db.SessionLocal()`), never bind it at module level in production code.
- `seed_db` is stubbed out in tests — do not rely on seeded accounts; use `_seed_admin()` and `register()` from `conftest.py` to set up test data explicitly.

## Code Quality

- Before finishing any task, run `uv run ruff check --fix .`, `uv run black .`, and `uv run mypy .` and ensure zero errors, then run `uv run pytest` and confirm all tests pass. Do not declare a task complete while any of these are red.

## Debugging UI Issues

- When fixing a UI bug (especially the recurring Leaflet map blackout), **set up real diagnostics first**: open the browser console, capture network logs, or drive a headless browser to reproduce the failure before touching any code.
- Common root causes to check before guessing: missing `maxZoom` on the Leaflet `TileLayer`, a blanket `select` override in `military.css` that silently swallows CSS, and Metal/GPU layer promotion caused by overlay `display` toggling (fix: toggle `visibility`, not `display`).
- Never make more than one speculative CSS/repaint fix without a confirmed reproduction. If the first blind fix doesn't resolve it, stop and reproduce.
