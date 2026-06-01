"""MainWindow — full Arrow Front COP layout."""
from __future__ import annotations
import json
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QSplitter,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from front.map.view       import MapView
from front.map.symbology  import SIDC
from front.app.toolbar    import MainToolbar
from front.app.statusbar  import StatusBar
from front.panels.orbat.panel     import ORBATPanel
from front.panels.reports.panel   import ReportsPanel
from front.panels.messages.panel  import MessagesPanel
from front.panels.alerts.panel    import AlertsPanel
from front.panels.draw.panel      import DrawPanel
from front.panels.missions.panel  import MissionsPanel
from front.client.arrow_client    import ArrowClient
from front.client.ws_listener    import WSListener
from front.map.tile_server       import MBTilesServer
from front.app.collapsible_panel import CollapsibleSidePanel

CBRN_TYPES = {"CBRN_1","CBRN_2","CBRN_3","CBRN_4","CBRN_5","CBRN_6"}

_SIDC_ECH_MAP = {
    "A-": "TM", "B-": "CREW", "C-": "SQD", "D-": "SEC",
    "E-": "PLT", "F-": "COY", "G-": "BN",  "H-": "RGT",
    "I-": "BDE", "J-": "DIV", "K-": "CORPS",
}

def _sidc_echelon(sidc: str) -> str:
    """Extract echelon label from a 15-char SIDC (positions 10-11)."""
    if len(sidc) >= 12:
        return _SIDC_ECH_MAP.get(sidc[10:12], "")
    return ""


class MainWindow(QMainWindow):
    def __init__(self, server_url: str, token: str, callsign: str):
        super().__init__()
        self._server_url = server_url
        self._token      = token
        self._callsign   = callsign
        self._client     = ArrowClient(server_url, token)
        self._ws: Optional[WSListener] = None
        self._tile_server = MBTilesServer()
        self._tile_server.start()

        self._build_ui()
        self._connect_signals()
        self._start_ws()
        QTimer.singleShot(1800, self._load_all)

    # ================================================================
    # UI
    # ================================================================
    def _build_ui(self):
        mode = "READ-ONLY" if not self._token else "COP"
        self.setWindowTitle(f"ARROW FRONT  —  {self._callsign.upper()}  —  {mode}")
        self.setMinimumSize(1024, 700)
        self.resize(1600, 960)

        # ---- Toolbar --------------------------------------------------
        self._toolbar = MainToolbar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

        # ---- Panels ---------------------------------------------------
        self._orbat_panel    = ORBATPanel()
        self._reports_panel  = ReportsPanel()
        self._messages_panel = MessagesPanel()
        self._alerts_panel   = AlertsPanel()
        self._draw_panel     = DrawPanel()
        self._missions_panel = MissionsPanel()

        self._right_tabs = QTabWidget()
        self._right_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._right_tabs.setDocumentMode(True)
        self._right_tabs.addTab(self._missions_panel, "MISSIONS")
        self._right_tabs.addTab(self._reports_panel,  "REPORTS")
        self._right_tabs.addTab(self._messages_panel, "MESSAGES")
        self._right_tabs.addTab(self._alerts_panel,   "ALERTS")
        self._right_tabs.addTab(self._draw_panel,     "DRAW")

        # ---- Map ------------------------------------------------------
        self._map = MapView(self)

        # ---- Collapsible side panels ----------------------------------
        self._left_panel = CollapsibleSidePanel(
            self._orbat_panel, "ORBAT", side="left", default_width=270
        )
        self._right_panel = CollapsibleSidePanel(
            self._right_tabs, "INFO", side="right", default_width=360
        )

        # ---- Splitter (fills the whole central area) ------------------
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)  # use our own logic
        self._splitter.setHandleWidth(2)
        self._splitter.setStyleSheet("""
            QSplitter::handle { background: #21262d; }
            QSplitter::handle:hover { background: #388bfd; }
        """)
        self._splitter.addWidget(self._left_panel)
        self._splitter.addWidget(self._map)
        self._splitter.addWidget(self._right_panel)

        # Bind splitter references (needed for resize logic)
        self._left_panel.bind_splitter(self._splitter, 0)
        self._right_panel.bind_splitter(self._splitter, 2)

        # Map always stretches; panels have fixed initial sizes
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes([270, 900, 360])

        self.setCentralWidget(self._splitter)

        # ---- Status bar -----------------------------------------------
        self._statusbar = StatusBar(self)
        self.setStatusBar(self._statusbar)

        # ---- Keyboard shortcuts [ = toggle left,  ] = toggle right ---
        QShortcut(QKeySequence("["), self).activated.connect(self._left_panel.toggle)
        QShortcut(QKeySequence("]"), self).activated.connect(self._right_panel.toggle)
        QShortcut(QKeySequence("F1"), self).activated.connect(self._left_panel.toggle)
        QShortcut(QKeySequence("F2"), self).activated.connect(self._right_panel.toggle)

    # ================================================================
    # SIGNALS
    # ================================================================
    def _connect_signals(self):
        tb = self._toolbar
        tb.mode_changed.connect(self._map.set_draw_mode)
        tb.layer_toggled.connect(self._map.toggle_layer)
        tb.base_changed.connect(self._map.set_base_layer)
        tb.fit_requested.connect(self._map.fit_tracks)
        tb.alert_requested.connect(self._send_alert)
        tb.mbtiles_selected.connect(self._load_mbtiles_file)
        tb.weather_toggled.connect(self._map.set_weather_layer)
        tb.weather_fetch.connect(lambda: self._map._js("fetchWeatherAtCenter()")  )  # noqa

        self._map.bridge.coords_changed.connect(self._statusbar.update_coords)
        self._map.bridge.map_ready.connect(self._load_all)
        self._map.bridge.radial_action.connect(self._on_radial_action)
        self._map.bridge.graphic_drawn.connect(self._on_graphic_drawn)
        self._map.bridge.measure_done.connect(
            lambda d, b: self.statusBar().showMessage(f"DIST {d}  BRG {b}", 6000)
        )

        self._orbat_panel.operator_focus_requested.connect(self._focus_operator)
        self._orbat_panel.message_requested.connect(
            lambda _: self._right_tabs.setCurrentWidget(self._messages_panel)
        )
        self._reports_panel.locate_requested.connect(
            lambda lat, lon: self._map.center_on(lat, lon, zoom=14)
        )
        self._messages_panel.message_send_requested.connect(self._send_message)
        self._draw_panel.draw_mode_changed.connect(self._map.set_draw_mode)
        self._draw_panel.draw_graphic.connect(self._map.set_draw_graphic)
        self._map.bridge.symbol_selected.connect(self._on_symbol_placed)
        self._missions_panel.mission_selected.connect(self._on_mission_selected)
        self._missions_panel.mission_cleared.connect(self._on_mission_cleared)

    # ================================================================
    # WEBSOCKET
    # ================================================================
    def _start_ws(self):
        if not self._token:
            return
        ws_base = self._server_url.replace("http://", "ws://").replace("https://", "wss://")
        self._ws = WSListener(ws_base, self._token)
        self._ws.track_received.connect(self._on_track)
        self._ws.cot_received.connect(self._on_cot)
        self._ws.alert_received.connect(self._on_alert)
        self._ws.report_received.connect(self._on_report)
        self._ws.message_received.connect(self._messages_panel.add_message)
        self._ws.graphic_received.connect(self._on_tact_obj_event)
        self._ws.fire_mission_received.connect(self._on_fm_event)
        self._ws.kml_received.connect(self._on_kml_event)
        self._ws.presence_changed.connect(self._on_presence)
        self._ws.mission_received.connect(self._on_mission_event)
        self._ws.connection_changed.connect(self._statusbar.set_connected)
        self._ws.start()

    # ================================================================
    # INITIAL DATA LOAD
    # ================================================================
    _loaded = False

    def _load_all(self):
        if self._loaded:
            return
        self._loaded = True
        self._load_hierarchy()
        self._load_missions()
        self._load_live_operators()
        self._load_cot_tracks()
        self._load_tactical_objects()
        self._load_fire_missions()
        self._load_kml_layers()
        self._load_alerts()
        self._load_reports()
        self._load_messages()

    def _load_hierarchy(self):
        try:
            data = self._client.hierarchy()
            import sys
            print(f"[ORBAT] keys={list(data.keys()) if isinstance(data,dict) else type(data)}", file=sys.stderr)
            companies = data.get("companies", []) if isinstance(data, dict) else []
            print(f"[ORBAT] companies={len(companies)}, "
                  f"unassigned={len(data.get('unassigned_operators',[]))}", file=sys.stderr)
            self._orbat_panel.load_hierarchy(data)
        except Exception as e:
            import sys
            print(f"[ORBAT] error: {e}", file=sys.stderr)

    def _load_live_operators(self):
        try:
            for op in self._client.live_operators():
                if op.get("latitude") and op.get("longitude"):
                    self._push_track({
                        "id":        op.get("operator_id") or op.get("id"),
                        "callsign":  op.get("callsign", "?"),
                        "lat":       op["latitude"],
                        "lon":       op["longitude"],
                        "heading":   op.get("heading"),
                        "speed":     op.get("speed"),
                        "unit":      op.get("team", ""),
                        "online":    True,
                        "last_seen": op.get("recorded_at", ""),
                    })
        except Exception:
            pass

    def _load_cot_tracks(self):
        try:
            for t in self._client.cot_tracks():
                self._map.update_cot_track(t)
        except Exception:
            pass

    def _load_tactical_objects(self):
        try:
            for obj in self._client.tactical_objects():
                self._map.add_tactical_object(obj)
        except Exception:
            pass

    def _load_fire_missions(self):
        try:
            for fm in self._client.fire_missions():
                self._map.add_fire_mission(fm)
        except Exception:
            pass

    def _load_kml_layers(self):
        try:
            summaries = self._client.kml_layers()
            for s in summaries:
                try:
                    full = self._client.kml_layer(s["id"])
                    self._map.add_kml_layer(full)
                except Exception:
                    pass
        except Exception:
            pass

    def _load_alerts(self):
        try:
            for a in self._client.alerts():
                self._on_alert(a)
        except Exception:
            pass

    def _load_reports(self):
        try:
            rpts = self._client.reports()
            self._reports_panel.load_reports(rpts)
            for r in rpts:
                if r.get("type", "") in CBRN_TYPES:
                    p = r.get("payload", {})
                    if isinstance(p, str):
                        try:
                            p = json.loads(p)
                        except Exception:
                            p = {}
                    self._map.add_cbrn_zone({**r, "payload": p})
        except Exception:
            pass

    def _load_messages(self):
        try:
            self._messages_panel.load_messages(self._client.messages())
        except Exception:
            pass

    def _load_missions(self):
        try:
            missions = self._client.missions()
            import sys
            print(f"[MISSIONS] count={len(missions)}", file=sys.stderr)
            self._missions_panel.load_missions(missions)
        except Exception as e:
            import sys
            print(f"[MISSIONS] error: {e}", file=sys.stderr)
            self._missions_panel.load_missions([])

    # ================================================================
    # WS EVENT HANDLERS
    # ================================================================
    def _on_track(self, data: dict):
        self._push_track(data)
        self._orbat_panel.update_from_tracking(data)

    def _on_cot(self, data: dict):
        event = data.get("event", "update")
        if event == "delete":
            uid = data.get("cot_uid") or data.get("uid")
            if uid:
                self._map._js(f"removeCotTrack({json.dumps(uid)})")
        else:
            self._map.update_cot_track(data)

    def _on_alert(self, data: dict):
        self._alerts_panel.add_alert(data)
        lat = data.get("latitude") or data.get("lat")
        lon = data.get("longitude") or data.get("lon")
        if lat and lon:
            self._map.add_alert_marker({**data, "lat": lat, "lon": lon})
        idx = self._right_tabs.indexOf(self._alerts_panel)
        self._right_tabs.setTabText(idx, "ALERTS ●")
        if data.get("type") in ("TIC", "DRONE_SPOTTED"):
            self._right_tabs.setCurrentWidget(self._alerts_panel)

    def _on_report(self, data: dict):
        self._reports_panel.add_report(data)
        idx = self._right_tabs.indexOf(self._reports_panel)
        self._right_tabs.setTabText(idx, "REPORTS ●")
        if data.get("type", "") in CBRN_TYPES:
            p = data.get("payload", {})
            if isinstance(p, str):
                try:
                    p = json.loads(p)
                except Exception:
                    p = {}
            self._map.add_cbrn_zone({**data, "payload": p})

    def _on_tact_obj_event(self, data: dict):
        event = data.get("event", "created")
        if event == "deleted":
            self._map.remove_tactical_object(str(data.get("id", "")))
        else:
            self._map.add_tactical_object(data)

    def _on_fm_event(self, data: dict):
        self._map.add_fire_mission(data)

    def _on_kml_event(self, data: dict):
        event = data.get("event", "created")
        if event == "deleted":
            self._map.remove_kml_layer(str(data.get("id", "")))
        else:
            try:
                full = self._client.kml_layer(data["id"])
                self._map.add_kml_layer(full)
            except Exception:
                pass

    def _on_mission_event(self, data: dict):
        self._load_missions()

    def _on_presence(self, data: dict):
        op_id  = data.get("operator_id")
        online = data.get("online", False)
        if op_id is not None:
            self._orbat_panel.update_operator_presence(int(op_id), online)

    # ================================================================
    # RADIAL MENU ACTIONS
    # ================================================================
    def _on_mission_selected(self, mission: dict):
        mid = mission.get("id")
        self._missions_panel.set_active_mission(mission)
        name = mission.get("name", "?")
        self.setWindowTitle(
            f"ARROW FRONT  —  {self._callsign.upper()}  —  {name.upper()}"
        )
        try:
            ops = self._client.mission_operators(mid)
            self._missions_panel.load_operators(ops)
        except Exception:
            pass

    def _on_mission_cleared(self):
        mode = "READ-ONLY" if not self._token else "COP"
        self.setWindowTitle(f"ARROW FRONT  —  {self._callsign.upper()}  —  {mode}")

    def _on_symbol_placed(self, sidc: str, designation: str, lat: float, lon: float):
        """User placed a symbol via the picker — save to server as tactical object."""
        aff_map = {"F": "FRIENDLY", "H": "HOSTILE", "N": "NEUTRAL", "U": "UNKNOWN", "A": "FRIENDLY"}
        affiliation = aff_map.get(sidc[1] if len(sidc) > 1 else "U", "UNKNOWN")
        obj_type = "ENEMY" if affiliation == "HOSTILE" else "MARKER"
        echelon = _sidc_echelon(sidc)
        try:
            self._client.post_tactical_object(
                obj_type,
                {"type": "point", "coords": [[lat, lon]]},
                notes=designation or "",
                affiliation=affiliation,
                symbol_code=sidc,
                echelon=echelon,
            )
        except Exception as e:
            self.statusBar().showMessage(f"Symbol not saved: {e}", 3000)
        self._map.add_tactical_object({
            "id": f"local_{id(sidc)}",
            "type": obj_type,
            "symbol_code": sidc,
            "latitude": lat, "longitude": lon,
            "affiliation": affiliation,
            "notes": designation,
            "echelon": echelon,
        })

    def _on_radial_action(self, action: str, lat: float, lon: float):
        if action == "tic":
            self._send_alert("TIC")
            self._place_radial_marker("HOSTILE", lat, lon, notes="TIC", affiliation="HOSTILE")
        elif action in ("enemy", "hostile"):
            pass  # symbol picker handles placement
        elif action in ("friendly",):
            pass  # symbol picker handles placement
        elif action == "medevac":
            self._right_tabs.setCurrentWidget(self._reports_panel)
            self._place_radial_marker("MARKER", lat, lon, notes="MEDEVAC", affiliation="FRIENDLY")
        elif action == "poi":
            self._place_radial_marker("POI", lat, lon, notes="POI", affiliation="NEUTRAL")
        elif action == "fire":
            self._right_tabs.setCurrentWidget(self._draw_panel)
        elif action == "report":
            self._right_tabs.setCurrentWidget(self._reports_panel)

    def _place_radial_marker(self, obj_type: str, lat: float, lon: float,
                             notes: str = "", affiliation: str = "UNKNOWN"):
        from front.map.symbology import build as build_sidc
        aff_sidc = {"FRIENDLY": "F", "HOSTILE": "H", "NEUTRAL": "N"}.get(affiliation, "U")
        type_func = {
            "HOSTILE": "infantry", "ENEMY": "infantry",
            "MARKER": "unit", "POI": "observer",
        }.get(obj_type, "unit")
        sidc = build_sidc(aff_sidc, type_func, "none")
        try:
            self._client.post_tactical_object(
                obj_type, {"type": "point", "coords": [[lat, lon]]},
                notes=notes, affiliation=affiliation,
                symbol_code=sidc,
            )
        except Exception:
            pass
        self._map.add_tactical_object({
            "id": f"radial_{notes}_{lat:.4f}_{lon:.4f}",
            "type": obj_type,
            "symbol_code": sidc,
            "latitude": lat, "longitude": lon,
            "affiliation": affiliation,
            "notes": notes,
        })

    # ================================================================
    # TOOLBAR HANDLERS
    # ================================================================
    def _send_alert(self, alert_type: str):
        try:
            self._client.send_alert(alert_type)
        except Exception as e:
            self.statusBar().showMessage(f"Alert failed: {e}", 3000)

    def _send_message(self, content: str):
        try:
            self._client.send_message(content)
        except Exception as e:
            self.statusBar().showMessage(f"Message failed: {e}", 3000)

    def _load_mbtiles_file(self, path: str):
        tile_url = self._tile_server.load(path)
        db = self._tile_server.db
        self._map.load_mbtiles(tile_url, db.min_zoom, db.max_zoom)
        self.statusBar().showMessage(f"MBTiles: {db.name}", 3000)

    def _on_graphic_drawn(self, gtype: str, geojson_str: str):
        try:
            geom = json.loads(geojson_str)
            self._client.post_tactical_object(gtype, geom)
        except Exception:
            pass

    def _focus_operator(self, operator_id: int):
        try:
            for op in self._client.live_operators():
                oid = op.get("operator_id") or op.get("id")
                if oid == operator_id and op.get("latitude") and op.get("longitude"):
                    self._map.center_on(op["latitude"], op["longitude"], zoom=15)
                    return
        except Exception:
            pass

    # ================================================================
    # HELPERS
    # ================================================================
    def _push_track(self, data: dict):
        op_id    = data.get("operator_id") or data.get("id")
        callsign = data.get("callsign") or data.get("name") or str(op_id)
        lat      = data.get("lat") or data.get("latitude")
        lon      = data.get("lon") or data.get("longitude")
        if not lat or not lon:
            return
        role  = data.get("role", "OPERATOR")
        sidc  = SIDC.from_operator_role(role)
        unit  = next((data.get(k) for k in ("team", "team_name", "section_name") if data.get(k)), "")
        self._map.update_track({
            "id":        str(op_id),
            "callsign":  callsign,
            "lat":       float(lat),
            "lon":       float(lon),
            "heading":   data.get("heading") or data.get("course"),
            "speed":     data.get("speed"),
            "sidc":      sidc,
            "unit":      unit,
            "online":    data.get("online", True),
            "last_seen": data.get("last_seen") or data.get("recorded_at", ""),
            "affiliation": "FRIENDLY",
        })

    # ================================================================
    # CLOSE
    # ================================================================
    def closeEvent(self, event):
        if self._ws:
            self._ws.stop()
            self._ws.wait(2000)
        event.accept()
