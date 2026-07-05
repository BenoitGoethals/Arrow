"""Qt wrapper around the native JDSS protocol core (``front.jdss.direct``).

``JdssDirectClient`` connects a Front operator straight to a JDSSArrow gateway:

* Inbound — a ``QThread`` consumes the gateway's ``/ws/events`` stream, filters to
  coalition traffic, and emits a normalised dict per message (``message`` signal).
* Outbound — ``publish_presence`` / ``publish_contact`` / ``publish_chat`` POST to
  the gateway's ``/api/publish/*`` endpoints (synchronous httpx; called from test
  buttons or a background position feed).

This bypasses the Arrow backend entirely, so it is meant for standalone / backend-
down use and is only active while explicitly connected.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import websockets
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from front.jdss import direct

log = logging.getLogger(__name__)


class _WsThread(QThread):
    """Background ``/ws/events`` consumer with auto-reconnect."""

    connected = pyqtSignal(bool)
    inbound = pyqtSignal(dict)

    def __init__(self, base_url: str, own_node_id: str | None = None):
        super().__init__()
        self._ws_url = direct.ws_url(base_url)
        self._own_node_id = own_node_id
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._listen())
        finally:
            loop.close()

    async def _listen(self) -> None:
        backoff = 2
        while not self._stop:
            try:
                async with websockets.connect(self._ws_url, ping_interval=20) as ws:
                    self.connected.emit(True)
                    backoff = 2
                    async for raw in ws:
                        if self._stop:
                            break
                        try:
                            evt = json.loads(raw)
                        except Exception:
                            continue
                        # Learn our own node id from the priming snapshot so the
                        # echo guard works even if it wasn't known at connect time.
                        if evt.get("direction") == "snapshot":
                            nid = (evt.get("snapshot") or {}).get("node_id")
                            if nid:
                                self._own_node_id = nid
                            continue
                        if direct.is_inbound(evt, self._own_node_id):
                            norm = direct.normalize_event(evt)
                            if norm:
                                self.inbound.emit(norm)
            except Exception as exc:
                self.connected.emit(False)
                if self._stop:
                    break
                log.info("JDSS direct WS down (%s) — retry in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


class JdssDirectClient(QObject):
    """Native, backend-independent JDSS gateway client (bi-directional)."""

    connected = pyqtSignal(bool)
    message = pyqtSignal(dict)  # normalised inbound coalition message

    def __init__(self, base_url: str, parent: QObject | None = None):
        super().__init__(parent)
        self._base = base_url.rstrip("/")
        self._own_node_id: str | None = None
        self._ws: _WsThread | None = None
        self.rx = 0
        self.tx = 0

    @property
    def base_url(self) -> str:
        return self._base

    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.isRunning()

    def start(self) -> None:
        if self._ws is not None:
            return
        # Best-effort: fetch our own node id up front for the echo guard.
        try:
            snap = httpx.get(f"{self._base}/api/monitor/snapshot", timeout=4.0).json()
            self._own_node_id = snap.get("node_id")
        except Exception:
            self._own_node_id = None
        self._ws = _WsThread(self._base, self._own_node_id)
        self._ws.connected.connect(self.connected)
        self._ws.inbound.connect(self._on_inbound)
        self._ws.start()

    def stop(self) -> None:
        if self._ws is not None:
            self._ws.stop()
            self._ws.wait(2000)
            self._ws = None
        self.connected.emit(False)

    def _on_inbound(self, norm: dict) -> None:
        self.rx += 1
        self.message.emit(norm)

    # ── Outbound (Front → JDSS) — synchronous, short-timeout ──────────────────
    def _post(self, path: str, payload: dict) -> str | None:
        try:
            r = httpx.post(f"{self._base}{path}", json=payload, timeout=6.0)
            r.raise_for_status()
            self.tx += 1
            return r.json().get("message_id")
        except Exception as exc:
            log.warning("JDSS direct publish %s failed: %s", path, exc)
            return None

    def publish_presence(
        self,
        lat: float,
        lon: float,
        callsign: str,
        identity: int = direct.IDENTITY_FRIEND,
    ) -> str | None:
        return self._post(
            "/api/publish/presence",
            direct.presence_payload(lat, lon, callsign, identity=identity),
        )

    def publish_contact(
        self,
        lat: float,
        lon: float,
        description: str,
        identity: int,
        callsign: str | None = None,
        sidc: str | None = None,
    ) -> str | None:
        return self._post(
            "/api/publish/contact",
            direct.contact_payload(
                lat, lon, description, identity=identity, callsign=callsign, sidc=sidc
            ),
        )

    def publish_chat(self, text: str, recipient: str = "all") -> str | None:
        return self._post("/api/publish/chat", direct.chat_payload(text, recipient))
