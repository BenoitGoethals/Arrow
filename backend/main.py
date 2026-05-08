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
from backend.streams.router import router as streams_router
from backend.fire_missions.router import router as fire_missions_router
from backend.cot.router import router as cot_router
from backend.photos.router import router as photos_router
from backend.api.companies import router as companies_router
from backend.api.hierarchy import router as hierarchy_router
from backend.api.operators import router as operators_router
from backend.api.platoons import router as platoons_router
from backend.api.sections import router as sections_router
from backend.api.tactical_objects import router as tactical_objects_router
from backend.api.teams import router as teams_router
from backend.auth.router import router as auth_router
from backend.battle_management.router import router as battles_router
from backend.config.xml_config import load_config
from backend.limiter import limiter
from backend.map.router import router as map_router
from backend.messaging.router import router as messaging_router
from backend.reports.router import router as reports_router
from backend.storage.database import init_db
from backend.storage.seed import seed as seed_db
from backend.tracking.router import router as tracking_router
from backend.websocket.router import router as ws_router

_WEAK_SECRET = "change-me-in-production"


def _configure_logging() -> None:
    """Structured JSON logging for log aggregation (Loki / CloudWatch / ELK)."""
    use_json = os.environ.get("ARROW_JSON_LOGS", "1") == "1"
    if use_json:
        from pythonjsonlogger.json import JsonFormatter
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"asctime": "ts", "name": "logger", "levelname": "level"},
        ))
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
    logging.getLogger("arrow.security").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    cfg = load_config()
    if cfg.auth.secret == _WEAK_SECRET and not os.environ.get("ARROW_INSECURE_SECRET_OK"):
        raise RuntimeError(
            "JWT secret is the default weak value. "
            "Set <secret> in config.xml or ARROW_INSECURE_SECRET_OK=1 for dev."
        )
    app.state.config = cfg
    init_db()
    seed_db()

    # Token revocation blacklist (Redis, falls back to in-memory)
    from backend import token_blacklist
    token_blacklist.init(os.environ.get("ARROW_REDIS_URL"))

    yield


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
    app.include_router(cot_router)
    app.include_router(auth_router)
    app.include_router(operators_router)
    app.include_router(teams_router)
    app.include_router(sections_router)
    app.include_router(platoons_router)
    app.include_router(companies_router)
    app.include_router(hierarchy_router)
    app.include_router(tactical_objects_router)
    app.include_router(alerts_router)
    app.include_router(messaging_router)
    app.include_router(tracking_router)
    app.include_router(battles_router)
    app.include_router(map_router)
    app.include_router(reports_router)
    app.include_router(fire_missions_router)
    app.include_router(streams_router)
    app.include_router(photos_router)
    app.include_router(ws_router)

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
