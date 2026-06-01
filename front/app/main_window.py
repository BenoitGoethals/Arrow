"""MainWindow — full Arrow Front COP layout."""
from __future__ import annotations
import json
from typing import Optional

import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QMessageBox,
)
from front.app.right_info_panel import RightInfoPanel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut, QAction

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
from front.panels.strike.panel    import StrikePackagePanel
from front.windows.strike_planner import StrikePlannerWindow
from front.client.arrow_client    import ArrowClient
from front.client.ws_listener    import WSListener
from front.map.tile_server       import MBTilesServer
from front.app.collapsible_panel import CollapsibleSidePanel
from front.app.toast_manager     import ToastManager

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
        self._role       = "OPERATOR"
        self._ws: Optional[WSListener] = None
        self._toasts     = ToastManager(self)
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
        self._strike_panel   = StrikePackagePanel()
        self._planner_windows: list[StrikePlannerWindow] = []

        self._info = RightInfoPanel()
        self._info.add_panel("missions", "◈",  "MISS",   self._missions_panel, "1")
        self._info.add_panel("strike",   "◆",  "STRK",   self._strike_panel,   "2")
        self._info.add_panel("reports",  "≡",  "RPTS",   self._reports_panel,  "3")
        self._info.add_panel("messages", "◎",  "MSG",    self._messages_panel, "4")
        self._info.add_panel("alerts",   "⚡", "ALRT",   self._alerts_panel,   "5")
        self._info.add_panel("draw",     "✚",  "DRAW",   self._draw_panel,     "6")

        # ---- Map ------------------------------------------------------
        self._map = MapView(self)

        # ---- Collapsible side panels ----------------------------------
        self._left_panel = CollapsibleSidePanel(
            self._orbat_panel, "ORBAT", side="left", default_width=270
        )
        self._right_panel = CollapsibleSidePanel(
            self._info, "INFO", side="right", default_width=360
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

        # Defer collapse until after window is shown and splitter has real px dimensions
        QTimer.singleShot(0, self._right_panel.collapse)

        # Map always stretches; panels have fixed initial sizes
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes([270, 900, 360])

        self.setCentralWidget(self._splitter)

        # ---- Status bar -----------------------------------------------
        self._statusbar = StatusBar(self)
        self.setStatusBar(self._statusbar)

        # ---- Menu bar (after all widgets exist) -----------------------
        self._build_menu()

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
            lambda _: self._info.activate("messages")
        )
        self._reports_panel.locate_requested.connect(
            lambda lat, lon: self._map.center_on(lat, lon, zoom=14)
        )
        self._messages_panel.message_send_requested.connect(self._send_message_scoped)
        self._draw_panel.draw_mode_changed.connect(self._map.set_draw_mode)
        self._draw_panel.draw_graphic.connect(self._map.set_draw_graphic)
        self._map.bridge.symbol_selected.connect(self._on_symbol_placed)
        self._missions_panel.mission_selected.connect(self._on_mission_selected)
        self._missions_panel.mission_cleared.connect(self._on_mission_cleared)
        self._missions_panel.refresh_requested.connect(self._load_missions)
        self._missions_panel.delete_all_requested.connect(self._on_delete_all_missions)

        self._strike_panel.refresh_requested.connect(self._load_strike_packages)
        self._strike_panel.package_selected.connect(self._on_strike_selected)
        self._strike_panel.package_cleared.connect(self._on_strike_cleared)
        self._strike_panel.overlay_requested.connect(self._on_strike_overlay)
        self._strike_panel.planner_requested.connect(self._on_strike_planner)

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
        self._ws.message_received.connect(self._on_message)
        self._ws.graphic_received.connect(self._on_tact_obj_event)
        self._ws.fire_mission_received.connect(self._on_fm_event)
        self._ws.kml_received.connect(self._on_kml_event)
        self._ws.presence_changed.connect(self._on_presence)
        self._ws.mission_received.connect(self._on_mission_event)
        self._ws.strike_package_received.connect(self._on_strike_ws)
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
        self._resolve_role()
        self._load_hierarchy()
        self._load_missions()
        self._load_strike_packages()
        self._load_live_operators()
        self._load_cot_tracks()
        self._load_tactical_objects()
        self._load_fire_missions()
        self._load_kml_layers()
        self._load_alerts()
        self._load_reports()
        self._load_messages()

    # ================================================================
    # MENU BAR
    # ================================================================

    def _build_menu(self):
        mb = self.menuBar()

        # ── File ────────────────────────────────────────────────────
        file_menu = mb.addMenu("File")
        act_exit = QAction("Exit Arrow Front", self)
        act_exit.triggered.connect(self._confirm_exit)
        file_menu.addAction(act_exit)

        # ── View ────────────────────────────────────────────────────
        view_menu = mb.addMenu("View")

        act_left = QAction("Toggle ORBAT Panel  [ F1 ]", self)
        act_left.triggered.connect(lambda: self._left_panel.toggle())
        view_menu.addAction(act_left)

        act_right = QAction("Toggle Info Panel  [ F2 ]", self)
        act_right.triggered.connect(lambda: self._right_panel.toggle())
        view_menu.addAction(act_right)

        view_menu.addSeparator()

        act_fit = QAction("Fit Tracks on Map  [ Ctrl+F ]", self)
        act_fit.triggered.connect(lambda: self._map.fit_tracks())
        view_menu.addAction(act_fit)

        view_menu.addSeparator()

        for name, panel in [
            ("Missions",         "missions"),
            ("Strike Packages",  "strike"),
            ("Reports",          "reports"),
            ("Messages",         "messages"),
            ("Alerts",           "alerts"),
            ("Draw",             "draw"),
        ]:
            act = QAction(name, self)
            act.triggered.connect(
                lambda _, p=panel: (self._right_panel.expand(), self._info.activate(p))
            )
            view_menu.addAction(act)

        # ── Admin ───────────────────────────────────────────────────
        self._admin_menu = mb.addMenu("Admin")
        self._admin_menu.setEnabled(False)   # unlocked after role resolved

        act_del_missions = QAction("Delete All Missions…", self)
        act_del_missions.setStatusTip("Permanently delete every mission from the server (ADMIN only)")
        act_del_missions.triggered.connect(self._confirm_delete_all_missions)
        self._admin_menu.addAction(act_del_missions)

        act_del_packages = QAction("Delete All Strike Packages…", self)
        act_del_packages.setStatusTip("Permanently delete all strike packages (ADMIN only)")
        act_del_packages.triggered.connect(self._confirm_delete_all_packages)
        self._admin_menu.addAction(act_del_packages)

        self._admin_menu.addSeparator()

        act_reload = QAction("Reload All Data", self)
        act_reload.triggered.connect(self._reload_all)
        self._admin_menu.addAction(act_reload)

        # ── Help ────────────────────────────────────────────────────
        help_menu = mb.addMenu("Help")
        act_about = QAction("About Arrow Front", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _unlock_admin_menu(self):
        if self._role in ("ADMIN", "BATTLE_CAPTAIN"):
            self._admin_menu.setEnabled(True)

    # ── Menu actions ────────────────────────────────────────────────

    def _confirm_exit(self):
        ans = QMessageBox.question(
            self, "Exit", "Exit Arrow Front?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Yes:
            sys.exit(0)

    def _confirm_delete_all_missions(self):
        missions = []
        try:
            missions = self._client.missions()
        except Exception:
            pass
        n = len(missions)
        if n == 0:
            QMessageBox.information(self, "Delete Missions", "No missions on server.")
            return
        ans = QMessageBox.question(
            self,
            "Delete All Missions",
            f"Permanently delete ALL {n} mission{'s' if n!=1 else ''} from the server?\n\n"
            f"This cannot be undone. Requires ADMIN role.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._on_delete_all_missions()

    def _confirm_delete_all_packages(self):
        pkgs = []
        try:
            pkgs = self._client.strike_packages()
        except Exception:
            pass
        n = len(pkgs)
        if n == 0:
            QMessageBox.information(self, "Delete Strike Packages", "No packages on server.")
            return
        ans = QMessageBox.question(
            self,
            "Delete All Strike Packages",
            f"Permanently delete ALL {n} strike package{'s' if n!=1 else ''}?\n\n"
            f"This cannot be undone. Requires ADMIN role.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Yes:
            failed = 0
            for p in pkgs:
                try:
                    import httpx
                    httpx.delete(
                        f"{self._server_url}/strike-packages/{p['id']}",
                        headers={"Authorization": f"Bearer {self._token}"},
                        timeout=8.0,
                    ).raise_for_status()
                except Exception:
                    failed += 1
            self._load_strike_packages()
            if failed:
                self.statusBar().showMessage(
                    f"Deleted {n-failed}/{n} packages — {failed} failed", 5000)
            else:
                self._toasts.show("info", "PACKAGES DELETED", f"{n} removed")

    def _reload_all(self):
        self._loaded = False
        self._load_all()
        self.statusBar().showMessage("Data reloaded", 3000)

    def _show_about(self):
        QMessageBox.about(
            self,
            "Arrow Front",
            "<b>Arrow Front</b> — Tactical Desktop COP<br><br>"
            "Common Operational Picture client for the Arrow platform.<br>"
            "Built with PyQt6 · Leaflet · milsymbol.js<br><br>"
            "<small style='color:#6e7681'>Press F5 to reload all data<br>"
            "[ / ] or F1 / F2 to toggle panels</small>",
        )

    def _resolve_role(self):
        try:
            me = self._client.me()
            self._role     = me.get("role", "OPERATOR")
            self._callsign = me.get("callsign", self._callsign)
            self._messages_panel.set_my_callsign(self._callsign)
            self._unlock_admin_menu()
            mode = "READ-ONLY" if not self._token else "COP"
            self.setWindowTitle(
                f"ARROW FRONT  —  {self._callsign.upper()}"
                f"  [{self._role}]  —  {mode}"
            )
        except Exception:
            pass

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
            ops = self._client.live_operators()
            self._messages_panel.set_operators(ops)
            for op in ops:
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
            print(f"[MISSIONS] role={self._role} count={len(missions)}", file=sys.stderr)
            self._missions_panel.load_missions(missions, self._role)
            self._messages_panel.set_missions(missions)
        except Exception as e:
            import sys
            print(f"[MISSIONS] error: {e}", file=sys.stderr)
            self._missions_panel.load_missions([], self._role)

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
        self._info.inc_badge("alerts")
        alert_type = data.get("type", "ALERT")
        operator   = data.get("operator") or data.get("callsign") or ""
        self._toasts.alert(alert_type, operator)
        if alert_type in ("TIC", "DRONE_SPOTTED"):
            self._right_panel.expand()
            self._info.activate("alerts")

    def _on_report(self, data: dict):
        self._reports_panel.add_report(data)
        self._info.inc_badge("reports")
        rtype  = data.get("type", "REPORT")
        sender = data.get("sender") or data.get("callsign") or ""
        self._toasts.report(rtype, sender)
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

    def _on_message(self, data: dict):
        self._messages_panel.add_message(data)
        sender = data.get("sender") or data.get("callsign") or "?"
        if sender != self._callsign:
            preview = (data.get("content") or "")[:60]
            self._toasts.message(sender, preview)
            self._info.inc_badge("messages")

    def _load_strike_packages(self):
        try:
            pkgs = self._client.strike_packages()
            self._strike_panel.load_packages(pkgs)
            # Badge if any ACTIVE package exists
            active = sum(1 for p in pkgs if p.get("status") == "ACTIVE")
            if active:
                self._info.set_badge("strike", active)
        except Exception as e:
            import sys
            print(f"[STRIKE] error: {e}", file=sys.stderr)

    def _on_strike_selected(self, pkg: dict):
        """Fetch full bundle and show detail."""
        try:
            bundle = self._client.strike_package_bundle(pkg["id"])
            self._strike_panel.update_package(bundle)
        except Exception:
            self._strike_panel.update_package(pkg)

    def _on_strike_cleared(self):
        pass

    def _on_strike_overlay(self, pkg: dict):
        """Load all tactical objects from the strike package onto the map."""
        try:
            bundle = self._client.strike_package_bundle(pkg["id"])
        except Exception:
            bundle = pkg
        tact_objs = bundle.get("_tactical_objects_expanded", [])
        for obj in tact_objs:
            self._map.add_tactical_object(obj)
        # Center map on target if available
        tlat = bundle.get("target_lat")
        tlon = bundle.get("target_lon")
        if tlat and tlon:
            self._map.center_on(float(tlat), float(tlon), zoom=13)
        name = bundle.get("name", "package")
        self._toasts.show("mission", f"OVERLAY LOADED", name.upper())

    def _on_strike_planner(self, pkg: dict):
        """Open the Strike Package planning window."""
        try:
            bundle = self._client.strike_package_bundle(pkg["id"])
        except Exception:
            bundle = pkg
        win = StrikePlannerWindow(bundle, parent=self)
        win.overlay_load_requested.connect(self._on_strike_overlay)
        win.show()
        self._planner_windows.append(win)

    def _on_strike_ws(self, data: dict):
        self._load_strike_packages()
        event = data.get("event", "")
        name  = data.get("name", "Strike package")
        if event in ("activated",):
            self._toasts.show("mission", "STRIKE PKG ACTIVATED", name.upper())
        elif event in ("created",):
            self._toasts.show("info", "NEW STRIKE PKG", name.upper())

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

    def _on_delete_all_missions(self):
        missions = self._client.missions() if self._token else []
        failed = 0
        for m in missions:
            try:
                self._client.delete_mission(m["id"])
            except Exception:
                failed += 1
        self._missions_panel.set_active_mission(None)
        self._load_missions()
        if failed:
            self.statusBar().showMessage(
                f"Deleted {len(missions)-failed}/{len(missions)} missions"
                f" — {failed} failed (ADMIN required)", 6000
            )
        else:
            self._toasts.show("info", "ALL MISSIONS DELETED",
                              f"{len(missions)} mission{'s' if len(missions)!=1 else ''} removed")

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
            self._right_panel.expand()
            self._info.activate("reports")
            self._place_radial_marker("MARKER", lat, lon, notes="MEDEVAC", affiliation="FRIENDLY")
        elif action == "poi":
            self._place_radial_marker("POI", lat, lon, notes="POI", affiliation="NEUTRAL")
        elif action == "fire":
            self._right_panel.expand()
            self._info.activate("draw")
        elif action == "report":
            self._right_panel.expand()
            self._info.activate("reports")

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

    def _send_message_scoped(self, content: str, scope: str,
                             receiver_id: object, mission_id: object):
        try:
            if scope == "DIRECT" and receiver_id is not None:
                self._client.send_message(content, receiver_id=int(receiver_id))
            elif scope == "MISSION" and mission_id is not None:
                # Mission-scoped: send as group message using mission_id as group_id
                self._client.send_message_group(content, group_id=int(mission_id))
            else:
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
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._toasts.restack()

    def closeEvent(self, event):
        if self._ws:
            self._ws.stop()
            self._ws.wait(2000)
        event.accept()
