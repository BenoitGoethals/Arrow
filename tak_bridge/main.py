"""TAK Bridge — FastAPI REST API + asyncio CoT TCP server.

Endpoints
---------
GET  /status           bridge stats (connections, messages, sync)
GET  /config           current configuration
PUT  /config           update configuration (restarts bridge if needed)
POST /start            start TCP server + sync loop
POST /stop             stop everything
GET  /contacts         list of known TAK/ATAK contacts seen by bridge
POST /sync             trigger an immediate Arrow → TAK push
POST /cot              inject a CoT XML event manually (test/debug)
DELETE /contacts/{uid} remove a cached contact

Run
---
    uv run tak-bridge
    uv run uvicorn tak_bridge.main:app --host 0.0.0.0 --port 8099 --reload
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from tak_bridge.bridge import BridgeManager
from tak_bridge.config import TakBridgeConfig, load_config, save_config
from tak_bridge.cot_stream import CotEvent, parse_cot

log = logging.getLogger("tak_bridge")

# ── Global bridge instance ────────────────────────────────────────────────────

_cfg: TakBridgeConfig | None = None
_bridge: BridgeManager | None = None

# In-memory contact registry: uid → last CotEvent
_contacts: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cfg, _bridge
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    _cfg = load_config()
    _bridge = BridgeManager(_cfg)
    await _bridge.start()
    log.info("TAK Bridge REST API ready on :8099")
    yield
    if _bridge:
        await _bridge.stop()


app = FastAPI(
    title="Arrow TAK Bridge",
    description=(
        "Bidirectional CoT/ATAK ↔ Arrow sync service.\n\n"
        "Runs a TCP CoT server (default :8087) that ATAK devices connect to, "
        "optionally connects upstream to a TAK server, and syncs Arrow operator "
        "positions and tactical objects in both directions."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Status & health ───────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "tak-bridge"}


@app.get("/status")
def bridge_status() -> dict:
    if not _bridge:
        return {"running": False}
    stats = _bridge.stats.to_dict()
    stats["running"] = _bridge._running
    stats["contacts_known"] = len(_contacts)
    stats["cot_server"] = (
        f"{_cfg.cot_server_host}:{_cfg.cot_server_port}" if _cfg else ""
    )
    stats["tak_server"] = (
        f"{_cfg.tak_host}:{_cfg.tak_port}"
        if _cfg and _cfg.tak_host
        else "not configured"
    )
    return stats


# ── Configuration ─────────────────────────────────────────────────────────────


@app.get("/config", response_model=TakBridgeConfig)
def get_config() -> TakBridgeConfig:
    return _cfg or TakBridgeConfig()


@app.put("/config")
async def update_config(body: TakBridgeConfig) -> dict:
    global _cfg
    _cfg = body
    save_config(_cfg)
    if _bridge:
        _bridge.reconfigure(_cfg)
    return {"status": "saved", "message": "Config updated. Bridge reconfigured."}


# ── Lifecycle control ─────────────────────────────────────────────────────────


@app.post("/start")
async def start_bridge() -> dict:
    if not _bridge:
        raise HTTPException(503, "Bridge not initialised")
    if _bridge._running:
        return {"status": "already_running"}
    await _bridge.start()
    return {"status": "started"}


@app.post("/stop")
async def stop_bridge() -> dict:
    if not _bridge:
        raise HTTPException(503, "Bridge not initialised")
    await _bridge.stop()
    return {"status": "stopped"}


# ── Manual sync ───────────────────────────────────────────────────────────────


@app.post("/sync")
async def manual_sync() -> dict:
    if not _bridge or not _bridge._running:
        raise HTTPException(503, "Bridge is not running")
    await _bridge._do_sync()
    return {
        "status": "ok",
        "sent": _bridge.stats.cot_sent,
        "pushed": _bridge.stats.arrow_pushed,
        "at": datetime.now(timezone.utc).isoformat(),
    }


# ── CoT injection (test/debug) ────────────────────────────────────────────────


@app.post("/cot", status_code=status.HTTP_202_ACCEPTED)
async def inject_cot(request: Request) -> dict:
    """Accept raw CoT XML (application/xml) and inject it into the bridge."""
    body = await request.body()
    if not body:
        raise HTTPException(400, "Empty body")

    evt = parse_cot(body)
    if not evt:
        raise HTTPException(422, "Invalid CoT XML")

    _contacts[evt.uid] = _contact_dict(evt)

    if _bridge and _bridge._running:
        # Broadcast to all ATAK clients
        await _bridge._pool.broadcast(body)
        # Push to Arrow
        if _cfg and _cfg.pull_tak_contacts:
            await _bridge._arrow.push_cot_track(evt)

    return {
        "status": "injected",
        "uid": evt.uid,
        "cot_type": evt.cot_type,
        "callsign": evt.callsign,
    }


# ── Contact registry ──────────────────────────────────────────────────────────


@app.get("/contacts")
def list_contacts() -> list[dict]:
    """List all TAK/ATAK contacts seen by the bridge."""
    now = time.time()
    stale_s = _cfg.stale_track_purge_s if _cfg else 300
    return [c for c in _contacts.values() if (now - c.get("last_seen_ts", 0)) < stale_s]


@app.delete("/contacts/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(uid: str) -> Response:
    _contacts.pop(uid, None)
    return Response(status_code=204)


# ── CoT test builder ──────────────────────────────────────────────────────────


@app.post("/test/cot")
async def send_test_cot(
    lat: float = 52.1228,
    lon: float = 5.2825,
    callsign: str = "TEST-1",
    cot_type: str = "a-f-G-U-C",
) -> dict:
    """Generate and broadcast a test CoT event (for ATAK connection testing)."""
    evt = CotEvent(
        uid=f"ARROW.TEST.{callsign}",
        cot_type=cot_type,
        lat=lat,
        lon=lon,
        callsign=callsign,
        platform="ARROW-BRIDGE-TEST",
    )
    xml = evt.to_xml()
    clients = 0
    if _bridge and _bridge._running:
        clients = await _bridge._pool.broadcast(xml)
    return {
        "status": "sent",
        "uid": evt.uid,
        "callsign": callsign,
        "lat": lat,
        "lon": lon,
        "clients": clients,
        "xml": xml.decode(),
    }


# ── Helper ────────────────────────────────────────────────────────────────────


def _contact_dict(evt: CotEvent) -> dict:
    return {
        "uid": evt.uid,
        "cot_type": evt.cot_type,
        "callsign": evt.callsign or evt.uid,
        "affiliation": evt.affiliation,
        "lat": evt.lat,
        "lon": evt.lon,
        "hae": evt.hae,
        "speed": evt.speed,
        "course": evt.course,
        "team": evt.team,
        "platform": evt.platform,
        "last_seen": datetime.now(timezone.utc).isoformat(),
        "last_seen_ts": time.time(),
    }
