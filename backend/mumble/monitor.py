"""Mumble observer bot — connects to a Mumble server, maintains channel/user state.

Runs as a daemon thread inside the FastAPI process. No audio captured or sent;
it is a silent spectator that lets the web dashboard show who is in each channel.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CONFIG_PATH = Path("data/mumble_config.json")

import backend.mumble.opus_fix as _opus_fix  # patches ctypes + ssl before opuslib loads

try:
    import pymumble_py3 as pymumble
    from pymumble_py3.callbacks import (
        PYMUMBLE_CLBK_CONNECTED,
        PYMUMBLE_CLBK_DISCONNECTED,
        PYMUMBLE_CLBK_SOUNDRECEIVED,
    )
    _AVAILABLE = True
    _ERR = ""
except Exception as _e:
    _AVAILABLE = False
    hint = _opus_fix.OPUS_INSTALL_HINT
    _ERR = f"{_e}" + (f" — {hint}" if hint else "")
    log.warning("Mumble not available: %s", _ERR)


# ─────────────────────────────────────────────────────────────────────────────

class MumbleMonitor:
    """Thread-safe Mumble presence observer."""

    def __init__(self):
        self._lock    = threading.Lock()
        self._mumble  = None
        self._thread: threading.Thread | None = None
        self._stop    = threading.Event()
        self._config: dict = {}
        self._state: dict  = {
            "connected": False,
            "error": "",
            "channels": [],
            "users": [],
        }

    # ── Config persistence ───────────────────────────────────────────────────

    def load_config(self):
        try:
            if CONFIG_PATH.exists():
                self._config = json.loads(CONFIG_PATH.read_text())
                if self._config.get("host"):
                    self._start()
        except Exception as exc:
            log.warning("Mumble config load error: %s", exc)

    def save_config(self, cfg: dict):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
        self._config = cfg

    def get_config_public(self) -> dict:
        """Return config with password masked."""
        c = dict(self._config)
        if c.get("password"):
            c["password"] = "••••••••"
        return c

    def clear_config(self):
        self._stop_connection()
        self._config = {}
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()

    # ── Connection lifecycle ─────────────────────────────────────────────────

    def apply_config(self, cfg: dict):
        self.save_config(cfg)
        self._stop_connection()
        if cfg.get("host"):
            self._start()

    def _start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mumble-monitor")
        self._thread.start()

    def _stop_connection(self):
        self._stop.set()
        if self._mumble:
            try:
                self._mumble.stop()
            except Exception:
                pass
            self._mumble = None
        if self._thread:
            self._thread.join(timeout=4)
            self._thread = None
        with self._lock:
            self._state = {"connected": False, "error": "", "channels": [], "users": []}

    def stop(self):
        self._stop_connection()

    # ── Background thread ────────────────────────────────────────────────────

    def _run(self):
        if not _AVAILABLE:
            with self._lock:
                self._state["error"] = f"pymumble not available: {_ERR}"
            return

        cfg = self._config
        host     = cfg.get("host", "")
        port     = int(cfg.get("port", 64738))
        username = cfg.get("username", "ArrowBot")
        password = cfg.get("password", "")

        while not self._stop.is_set():
            try:
                log.info("Mumble monitor: connecting to %s:%s as %s", host, port, username)
                m = pymumble.Mumble(host, username, password=password, port=port, reconnect=False)
                m.set_application_string("Arrow Monitor")
                m.start()
                m.is_ready()
                self._mumble = m
                with self._lock:
                    self._state["connected"] = True
                    self._state["error"]     = ""
                log.info("Mumble monitor: connected")

                # Poll loop
                while not self._stop.is_set():
                    time.sleep(2)
                    try:
                        channels, users = self._snapshot(m)
                        with self._lock:
                            self._state["channels"] = channels
                            self._state["users"]    = users
                    except Exception as exc:
                        log.debug("Mumble snapshot error: %s", exc)

            except Exception as exc:
                msg = str(exc)
                if "ConnectionRejectedError" in type(exc).__name__:
                    msg = "Server rejected connection — check host/port/password"
                log.warning("Mumble monitor: connection failed — %s", msg)
                with self._lock:
                    self._state["connected"] = False
                    self._state["error"]     = msg
                self._mumble = None

            if self._stop.is_set():
                break
            # Back-off before retry
            for _ in range(15):
                if self._stop.is_set():
                    break
                time.sleep(1)

        with self._lock:
            self._state["connected"] = False

    @staticmethod
    def _snapshot(m) -> tuple[list[dict], list[dict]]:
        channels = []
        for cid, ch in m.channels.items():
            channels.append({
                "id":        cid,
                "name":      ch.get("name", "?"),
                "parent_id": ch.get("parent", -1),
            })
        users = []
        for session, u in m.users.items():
            users.append({
                "session":    session,
                "name":       u.get("name", "?"),
                "channel_id": u.get("channel_id", 0),
                "muted":      bool(u.get("mute") or u.get("self_mute")),
                "deafened":   bool(u.get("deaf") or u.get("self_deaf")),
            })
        return channels, users

    # ── Status ───────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)


# ── Module-level singleton ────────────────────────────────────────────────────

monitor = MumbleMonitor()
