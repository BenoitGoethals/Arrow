from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.alerts.router import router as alerts_router
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
from backend.map.router import router as map_router
from backend.messaging.router import router as messaging_router
from backend.reports.router import router as reports_router
from backend.storage.database import init_db
from backend.storage.seed import seed as seed_db
from backend.tracking.router import router as tracking_router
from backend.websocket.router import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config = load_config()
    init_db()
    seed_db()  # no-op if operators already exist
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Arrow — Soldier System Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    uvicorn.run(
        "backend.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
