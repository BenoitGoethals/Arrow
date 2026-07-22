"""WebSocket listener — Kivy port of front/client/ws_listener.py.

Same reconnect/backoff logic and channel routing as the PyQt6 version, but
runs on a plain threading.Thread (with its own asyncio loop) instead of
QThread, and delivers events as EventDispatcher events on Kivy's Clock
instead of pyqtSignal — the same background-thread -> Clock.schedule_once
marshaling pattern used by front_kivy/map/view.py's MapHandle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading

import websockets
from kivy.clock import Clock
from kivy.event import EventDispatcher

log = logging.getLogger(__name__)

_SSL_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# WS channel name -> EventDispatcher event name
_ROUTING = {
    "tracking": "on_track_received",
    "cot-track": "on_cot_received",
    "presence": "on_presence_changed",
    "cot-presence": "on_cot_presence_changed",
    "alert": "on_alert_received",
    "report": "on_report_received",
    "chat": "on_message_received",
    "tactical-object": "on_graphic_received",
    "vehicle": "on_vehicle_received",
    "fire-mission": "on_fire_mission_received",
    "kml-layer": "on_kml_received",
    "overlay": "on_overlay_received",
    "mission": "on_mission_received",
    "strike-package": "on_strike_package_received",
    "stream": "on_stream_received",
}


class WSListener(EventDispatcher):
    __events__ = tuple(_ROUTING.values()) + ("on_connection_changed",)

    def __init__(self, ws_base_url: str, token: str, **kwargs):
        super().__init__(**kwargs)
        self._url = f"{ws_base_url}/ws?token={token}"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def join(self, timeout: float | None = None):
        self._thread.join(timeout=timeout)

    # ---- background thread -------------------------------------------------

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._listen())
        loop.close()

    async def _listen(self):
        backoff = 2
        while not self._stop.is_set():
            try:
                ssl_ctx = _SSL_CTX if self._url.startswith("wss://") else None
                url_log = self._url.split("?")[0]
                log.info("WS connecting → %s", url_log)
                async with websockets.connect(
                    self._url, ping_interval=20, ssl=ssl_ctx
                ) as ws:
                    log.info("WS connected")
                    self._emit("on_connection_changed", True)
                    backoff = 2
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            self._dispatch(json.loads(raw))
                        except Exception as exc:
                            log.warning("WS dispatch error: %s", exc)
            except Exception as exc:
                log.warning("WS disconnected: %s", exc)
                self._emit("on_connection_changed", False)
                if not self._stop.is_set():
                    log.info("WS retry in %ds", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    def _dispatch(self, msg: dict):
        ch = msg.get("channel", "")
        data = msg.get("data", {})
        ev_name = _ROUTING.get(ch)
        if ev_name:
            self._emit(ev_name, data)

    def _emit(self, ev_name: str, payload):
        # Marshal onto the Kivy main thread — dispatch() must not run here,
        # this method runs on the WS background thread.
        Clock.schedule_once(lambda dt: self.dispatch(ev_name, payload), 0)

    # required no-op default handlers for each declared event
    def on_track_received(self, *a):
        pass

    def on_cot_received(self, *a):
        pass

    def on_presence_changed(self, *a):
        pass

    def on_cot_presence_changed(self, *a):
        pass

    def on_alert_received(self, *a):
        pass

    def on_report_received(self, *a):
        pass

    def on_message_received(self, *a):
        pass

    def on_graphic_received(self, *a):
        pass

    def on_vehicle_received(self, *a):
        pass

    def on_fire_mission_received(self, *a):
        pass

    def on_kml_received(self, *a):
        pass

    def on_overlay_received(self, *a):
        pass

    def on_mission_received(self, *a):
        pass

    def on_strike_package_received(self, *a):
        pass

    def on_stream_received(self, *a):
        pass

    def on_connection_changed(self, *a):
        pass
