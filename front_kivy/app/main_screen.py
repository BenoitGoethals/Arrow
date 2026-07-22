"""Main shell screen — Kivy port of the walking-skeleton slice of
front/app/main_window.py: owns the map (via MapHandle, a separate pywebview
process) and the WS listener, and pushes live operator tracks onto the map.

This is intentionally a minimal shell (Phase 1 of the Kivy port plan) — the
18 feature panels from front/panels/ are ported incrementally afterward, not
here.
"""

from __future__ import annotations

import logging

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

from front.client.arrow_client import ArrowClient
from front.map.symbology import SIDC
from front_kivy.client.ws_listener import WSListener
from front_kivy.map.view import MapHandle

log = logging.getLogger(__name__)

_TOPBAR_HEIGHT = 36


class MainScreen(Screen):
    def __init__(self, server_url: str, token: str, callsign: str, **kwargs):
        super().__init__(**kwargs)
        self.server_url = server_url
        self.token = token
        self.callsign = callsign
        self.client = ArrowClient(server_url, token or None)

        self._map: MapHandle | None = None
        self._ws: WSListener | None = None

        self._build_ui()
        Clock.schedule_once(lambda dt: self._start(), 0)

    # ---- UI -----------------------------------------------------------

    def _build_ui(self):
        root = BoxLayout(orientation="vertical")
        topbar = BoxLayout(size_hint_y=None, height=_TOPBAR_HEIGHT, padding=(8, 0))
        self._status_label = Label(text=f"{self.callsign} — connecting…", halign="left")
        topbar.add_widget(self._status_label)
        root.add_widget(topbar)
        # The map itself renders in a separate OS window (see MapHandle /
        # front_kivy/map/map_process.py) kept positioned over this area —
        # this placeholder just reserves + labels the space in the Kivy layout.
        self._map_area = Label(text="", size_hint_y=1)
        root.add_widget(self._map_area)
        self.add_widget(root)

    # ---- lifecycle ------------------------------------------------------

    def _start(self):
        map_x, map_y, map_w, map_h = self._map_geometry()
        self._map = MapHandle(map_x, map_y, map_w, map_h)
        self._map.bind(on_map_ready=lambda *_: self._on_map_ready())
        self._map.bind(
            on_track_clicked=lambda inst, data: log.info("track clicked: %s", data)
        )

        Window.bind(on_move=self._sync_map_geometry, size=self._sync_map_geometry)

        self._ws = WSListener(self.server_url.replace("http", "ws", 1), self.token)
        self._ws.bind(on_track_received=lambda inst, data: self._push_track(data))
        self._ws.bind(
            on_connection_changed=lambda inst, connected: self._on_connection_changed(
                connected
            )
        )
        self._ws.start()

    def stop(self):
        if self._ws:
            self._ws.stop()
        if self._map:
            self._map.stop()

    # ---- map window geometry sync ---------------------------------------

    def _map_geometry(self) -> tuple[int, int, int, int]:
        x = Window.left
        y = Window.top + _TOPBAR_HEIGHT
        w = Window.width
        h = Window.height - _TOPBAR_HEIGHT
        return x, y, w, h

    def _sync_map_geometry(self, *args):
        if not self._map:
            return
        x, y, w, h = self._map_geometry()
        self._map.move(x, y)
        self._map.resize(w, h)

    def _on_map_ready(self):
        log.info("map ready")
        self._map.fit_tracks()

    def _on_connection_changed(self, connected: bool):
        state = "connected" if connected else "disconnected"
        self._status_label.text = f"{self.callsign} — {state}"

    # ---- track push (mirrors front/app/main_window.py:_push_track) ------

    def _push_track(self, data: dict):
        if not self._map:
            return
        op_id = data.get("operator_id") or data.get("id")
        callsign = data.get("callsign") or data.get("name") or str(op_id)
        lat = data.get("lat") or data.get("latitude")
        lon = data.get("lon") or data.get("longitude")
        if not lat or not lon:
            return
        role = data.get("role", "OPERATOR")
        sidc = SIDC.from_operator_role(role)
        unit = next(
            (data.get(k) for k in ("team", "team_name", "section_name") if data.get(k)),
            "",
        )
        self._map.update_track(
            {
                "id": str(op_id),
                "callsign": callsign,
                "lat": float(lat),
                "lon": float(lon),
                "heading": data.get("heading") or data.get("course"),
                "speed": data.get("speed"),
                "sidc": sidc,
                "unit": unit,
                "online": data.get("online", True),
                "last_seen": data.get("last_seen") or data.get("recorded_at", ""),
                "affiliation": "FRIENDLY",
                "position_source": data.get("position_source"),
            }
        )
