import logging
import logging.config
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.admin.router import router as admin_api_router
from backend.alerts.router import router as alerts_router
from backend.apk.router import router as apk_router
from backend.streams.router import router as streams_router
from backend.octopus.router import router as octopus_router
from backend.fire_missions.router import router as fire_missions_router
from backend.history.router import router as history_router
from backend.cot.router import router as cot_router
from backend.photos.router import router as photos_router
from backend.api.companies import router as companies_router
from backend.api.exports import router as exports_router
from backend.api.hierarchy import router as hierarchy_router
from backend.api.imports import router as imports_router
from backend.api.operators import router as operators_router
from backend.api.platoons import router as platoons_router
from backend.api.sections import router as sections_router
from backend.api.tactical_objects import router as tactical_objects_router
from backend.api.teams import router as teams_router
from backend.auth.router import router as auth_router
from backend.battle_management.router import router as battles_router
from backend.strike_packages.router import router as strike_packages_router
from backend.config.xml_config import load_config
from backend.limiter import limiter
from backend.kml.router import router as kml_router
from backend.map.router import router as map_router
from backend.overlays.router import router as overlays_router
from backend.messaging.router import router as messaging_router
from backend.missions.router import router as missions_router
from backend.opord.router import router as opord_router
from backend.reports.router import router as reports_router
from backend.cas.router import router as cas_router
from backend.cop.router import router as cop_router
from backend.logcop.router import router as logcop_router
from backend.storage.database import init_db
from backend.storage.seed import seed as seed_db
from backend.tracking.router import router as tracking_router
from backend.vehicles.router import router as vehicles_router
from backend.websocket.router import router as ws_router
from backend.mumble.router import router as mumble_router

_WEAK_SECRET = "change-me-in-production"
_SECRET_FILE = "data/jwt_secret.key"


def _resolve_jwt_secret(cfg_secret: str) -> str:
    """Return a strong JWT secret, auto-generating one on first boot if needed.

    Priority order:
      1. ARROW_JWT_SECRET env var (production .env / Kubernetes secret)
      2. config.xml <secret> if it is not the default weak value
      3. Persisted auto-generated secret from data/jwt_secret.key
      4. Generate a new secret, persist it, log it prominently, and use it
    """
    import secrets as _secrets
    from pathlib import Path

    # 1. Explicit env var always wins
    env_secret = os.environ.get("ARROW_JWT_SECRET", "").strip()
    if env_secret and env_secret != _WEAK_SECRET:
        return env_secret

    # 2. config.xml has a real secret
    if cfg_secret != _WEAK_SECRET:
        return cfg_secret

    # 3. Already auto-generated on a previous boot
    key_path = Path(_SECRET_FILE)
    if key_path.exists():
        saved = key_path.read_text().strip()
        if saved:
            return saved

    # 4. First boot with default secret → generate, persist, warn loudly
    new_secret = _secrets.token_hex(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(new_secret)
    key_path.chmod(0o600)
    log = logging.getLogger(__name__)
    log.warning(
        "SECURITY: JWT secret was the default weak value. "
        "A random secret has been generated and saved to %s. "
        "To use a fixed secret set ARROW_JWT_SECRET env var or <secret> in config.xml.",
        _SECRET_FILE,
    )
    return new_secret


def _configure_logging() -> None:
    """Structured JSON logging for log aggregation (Loki / CloudWatch / ELK)."""
    level_name = os.environ.get("ARROW_LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)

    use_json = os.environ.get("ARROW_JSON_LOGS", "1") == "1"
    if use_json:
        from pythonjsonlogger.json import JsonFormatter
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"asctime": "ts", "name": "logger", "levelname": "level"},
        ))
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        ))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Arrow domain loggers — all at the configured level
    for ns in (
        "backend",
        "backend.octopus",
        "backend.streams",
        "backend.websocket",
        "backend.tracking",
        "backend.alerts",
        "backend.messaging",
        "backend.auth",
        "arrow.security",
    ):
        logging.getLogger(ns).setLevel(level)

    # Suppress noisy third-party loggers that flood output at DEBUG
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    cfg = load_config()

    # Resolve JWT secret (auto-generates on first boot if config still has the default)
    resolved_secret = _resolve_jwt_secret(cfg.auth.secret)
    from backend.auth.infrastructure import token_service as _token_service
    _token_service._cfg = type(_token_service._cfg)(
        secret=resolved_secret,
        algorithm=cfg.auth.algorithm,
        token_expire_minutes=cfg.auth.token_expire_minutes,
    )

    app.state.config = cfg
    init_db()
    seed_db()

    # Token revocation blacklist (Redis, falls back to in-memory)
    from backend import token_blacklist
    token_blacklist.init(os.environ.get("ARROW_REDIS_URL"))

    # Mumble observer bot — loads saved config and connects if configured
    from backend.mumble.monitor import monitor as _mumble_monitor
    _mumble_monitor.load_config()

    yield

    # Graceful Mumble shutdown
    _mumble_monitor.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Arrow — Soldier System Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS
    _raw_origins = os.environ.get("ARROW_ALLOWED_ORIGINS", "http://localhost:6002")
    _allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(admin_api_router)
    app.include_router(apk_router)
    app.include_router(cot_router)
    app.include_router(auth_router)
    app.include_router(operators_router)
    app.include_router(teams_router)
    app.include_router(sections_router)
    app.include_router(platoons_router)
    app.include_router(companies_router)
    app.include_router(hierarchy_router)
    app.include_router(imports_router)
    app.include_router(exports_router)
    app.include_router(missions_router)
    app.include_router(tactical_objects_router)
    app.include_router(alerts_router)
    app.include_router(messaging_router)
    app.include_router(tracking_router)
    app.include_router(battles_router)
    app.include_router(strike_packages_router)
    app.include_router(vehicles_router)
    app.include_router(map_router)
    app.include_router(kml_router)
    app.include_router(overlays_router)
    app.include_router(reports_router)
    app.include_router(cas_router)
    app.include_router(cop_router)
    app.include_router(logcop_router)
    app.include_router(opord_router)
    app.include_router(fire_missions_router)
    app.include_router(history_router)
    app.include_router(streams_router)
    app.include_router(octopus_router)
    app.include_router(photos_router)
    app.include_router(ws_router)
    app.include_router(mumble_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


def run() -> None:
    import uvicorn
    cfg = load_config()
    uvicorn.run("backend.main:app", host=cfg.server.host, port=cfg.server.port, reload=True)


if __name__ == "__main__":
    run()
