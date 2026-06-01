"""WebSocket listener — all broadcast channels handled."""
import asyncio
import json
import websockets
from PyQt6.QtCore import QThread, pyqtSignal


class WSListener(QThread):
    # Operator / CoT
    track_received     = pyqtSignal(dict)
    cot_received       = pyqtSignal(dict)
    presence_changed   = pyqtSignal(dict)
    # Reports / Alerts
    alert_received     = pyqtSignal(dict)
    report_received    = pyqtSignal(dict)
    # Messaging
    message_received   = pyqtSignal(dict)
    # Tactical objects / graphics
    graphic_received   = pyqtSignal(dict)
    # Fire missions
    fire_mission_received = pyqtSignal(dict)
    # KML layers
    kml_received       = pyqtSignal(dict)
    # Overlays
    overlay_received   = pyqtSignal(dict)
    # Missions
    mission_received        = pyqtSignal(dict)
    strike_package_received = pyqtSignal(dict)
    stream_received         = pyqtSignal(dict)
    # Connection
    connection_changed = pyqtSignal(bool)

    def __init__(self, ws_base_url: str, token: str):
        super().__init__()
        self._url  = f"{ws_base_url}/ws?token={token}"
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
                async with websockets.connect(self._url, ping_interval=20) as ws:
                    self.connection_changed.emit(True)
                    backoff = 2
                    async for raw in ws:
                        if self._stop:
                            break
                        try:
                            self._dispatch(json.loads(raw))
                        except Exception:
                            pass
            except Exception:
                self.connection_changed.emit(False)
                if not self._stop:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    def _dispatch(self, msg: dict):
        ch   = msg.get("channel", "")
        data = msg.get("data", {})
        routing = {
            "tracking":        self.track_received,
            "cot-track":       self.cot_received,
            "presence":        self.presence_changed,
            "alert":           self.alert_received,
            "report":          self.report_received,
            "chat":            self.message_received,
            "tactical-object": self.graphic_received,
            "fire-mission":    self.fire_mission_received,
            "kml-layer":       self.kml_received,
            "overlay":         self.overlay_received,
            "mission":         self.mission_received,
            "strike-package":  self.strike_package_received,
            "stream":          self.stream_received,
        }
        if sig := routing.get(ch):
            sig.emit(data)
