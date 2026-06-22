"""WebSocket listener — all broadcast channels handled."""

import asyncio
import json
import logging
import ssl
import websockets
from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)

# Accept self-signed certs (production uses a self-signed cert)
_SSL_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


class WSListener(QThread):
    # Operator / CoT
    track_received = pyqtSignal(dict)
    cot_received = pyqtSignal(dict)
    presence_changed = pyqtSignal(dict)
    cot_presence_changed = pyqtSignal(dict)  # ATAK TCP client connect/disconnect
    # Reports / Alerts
    alert_received = pyqtSignal(dict)
    report_received = pyqtSignal(dict)
    # Messaging
    message_received = pyqtSignal(dict)
    # Tactical objects / graphics
    graphic_received = pyqtSignal(dict)
    # Vehicles
    vehicle_received = pyqtSignal(dict)
    # Fire missions
    fire_mission_received = pyqtSignal(dict)
    # KML layers
    kml_received = pyqtSignal(dict)
    # Overlays
    overlay_received = pyqtSignal(dict)
    # Missions
    mission_received = pyqtSignal(dict)
    strike_package_received = pyqtSignal(dict)
    stream_received = pyqtSignal(dict)
    # Connection
    connection_changed = pyqtSignal(bool)

    def __init__(self, ws_base_url: str, token: str):
        super().__init__()
        self._url = f"{ws_base_url}/ws?token={token}"
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._listen())
        loop.close()

    async def _listen(self):
        backoff = 2
        while not self._stop:
            try:
                ssl_ctx = _SSL_CTX if self._url.startswith("wss://") else None
                url_log = self._url.split("?")[0]
                log.info("WS connecting → %s", url_log)
                async with websockets.connect(
                    self._url, ping_interval=20, ssl=ssl_ctx
                ) as ws:
                    log.info("WS connected")
                    self.connection_changed.emit(True)
                    backoff = 2
                    async for raw in ws:
                        if self._stop:
                            break
                        try:
                            self._dispatch(json.loads(raw))
                        except Exception as exc:
                            log.warning("WS dispatch error: %s", exc)
            except Exception as exc:
                log.warning("WS disconnected: %s", exc)
                self.connection_changed.emit(False)
                if not self._stop:
                    log.info("WS retry in %ds", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    def _dispatch(self, msg: dict):
        ch = msg.get("channel", "")
        data = msg.get("data", {})
        routing = {
            "tracking": self.track_received,
            "cot-track": self.cot_received,
            "presence": self.presence_changed,
            "cot-presence": self.cot_presence_changed,
            "alert": self.alert_received,
            "report": self.report_received,
            "chat": self.message_received,
            "tactical-object": self.graphic_received,
            "vehicle": self.vehicle_received,
            "fire-mission": self.fire_mission_received,
            "kml-layer": self.kml_received,
            "overlay": self.overlay_received,
            "mission": self.mission_received,
            "strike-package": self.strike_package_received,
            "stream": self.stream_received,
        }
        if sig := routing.get(ch):
            sig.emit(data)
