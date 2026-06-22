"""Persistent bridge configuration stored in tak_bridge_config.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from pydantic import BaseModel

log = logging.getLogger("tak_bridge.config")
_CONFIG_PATH = Path("data/tak_bridge_config.json")


class TakBridgeConfig(BaseModel):
    # ── Arrow backend ─────────────────────────────────────────────────────────
    arrow_url: str = "http://localhost:6001"
    arrow_callsign: str = "benoit"
    arrow_password: str = "ranger14"

    # ── TAK server (optional — leave empty to disable) ────────────────────────
    tak_host: str = ""  # e.g. "192.168.1.100"
    tak_port: int = 8087  # 8087 TCP plain, 8088 SSL, 8089 WS
    tak_ssl: bool = False
    tak_callsign: str = "ARROW-BRIDGE"

    # ── CoT TCP server (ATAK devices connect here) ────────────────────────────
    cot_server_host: str = "0.0.0.0"
    cot_server_port: int = 8087  # standard ATAK TCP port

    # ── Sync behaviour ────────────────────────────────────────────────────────
    sync_interval_s: float = 5.0  # how often to push Arrow→TAK
    stale_track_purge_s: int = 300  # drop TAK contacts not seen in N secs
    push_arrow_operators: bool = True  # push Arrow operators to TAK
    push_arrow_tac_objects: bool = True  # push Arrow tactical objects to TAK
    pull_tak_contacts: bool = True  # pull TAK contacts into Arrow CotTrack


def load_config() -> TakBridgeConfig:
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        return TakBridgeConfig(**data)
    except Exception:
        return TakBridgeConfig()


def save_config(cfg: TakBridgeConfig) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(cfg.model_dump_json(indent=2))
    log.info("config saved to %s", _CONFIG_PATH)
