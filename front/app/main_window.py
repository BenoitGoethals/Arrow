"""MainWindow — full Arrow Front COP layout."""

from __future__ import annotations
import json
import logging
from typing import Optional

import sys

log = logging.getLogger(__name__)
from PyQt6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QMessageBox,
    QFileDialog,
    QLabel,
)
from front.app.activity_panel import ActivityPanel
from PyQt6.QtCore import Qt, QTimer, QSettings, QProcess
from PyQt6.QtGui import QKeySequence, QShortcut, QAction

from front.map.view import MapView
from front.map.symbology import SIDC
from front.app.toolbar import MainToolbar
from front.app.statusbar import StatusBar
from front.panels.orbat.panel import ORBATPanel
from front.panels.devices.panel import DevicesPanel
from front.panels.firemissions.panel import FireMissionsPanel
from front.panels.reports.panel import ReportsPanel
from front.panels.messages.panel import MessagesPanel
from front.panels.messages.room_manager import RoomManagerDialog
from front.panels.alerts.panel import AlertsPanel
from front.panels.draw.panel import DrawPanel
from front.panels.log.panel import LogPanel
from front.mumble.panel import MumblePanel
from front.panels.missions.panel import MissionsPanel
from front.panels.strike.panel import StrikePackagePanel
from front.panels.opord.panel import OpordPanel
from front.panels.streams.panel import StreamsPanel
from front.panels.media.panel import MediaPanel
from front.windows.strike_planner import StrikePlannerWindow
from front.windows.opord_window import OpordWindow
from front.windows.stream_viewer import StreamViewerWindow
from front.windows.medevac_window import MedevacWindow
from front.windows.fire_mission_dialog import FireMissionDialog
from front.client.arrow_client import ArrowClient
from front.client.ws_listener import WSListener
from front.map.tile_server import MBTilesServer
from front.app.toast_manager import ToastManager
from front.app.settings_dialog import (
    ConfigDialog,
    read_gps_config,
    load as _settings_load,
    _bool as _settings_bool,
)
from front.app.voice_alerts import VoiceAlertPlayer
from front.utils.location_provider import (
    LocationProvider,
    is_supported as _native_loc_supported,
)
from front.panels.mbtiles.dialog import MBTilesDialog
from front.panels.routes.panel import RoutesPanel, RoutePropertiesDialog
from front.storage.local_store import LocalStore

CBRN_TYPES = {"CBRN_1", "CBRN_2", "CBRN_3", "CBRN_4", "CBRN_5", "CBRN_6"}

# Echelon letter sits at SIDC index 11 (milsymbol reads charAt(11)); index 10 is
# the HQ/mobility modifier. Keys are "-<letter>" to match MIL-STD-2525B / the web.
_SIDC_ECH_MAP = {
    "-A": "TM",
    "-B": "SQD",
    "-C": "SEC",
    "-D": "PLT",
    "-E": "COY",
    "-F": "BN",
    "-G": "RGT",
    "-H": "BDE",
    "-I": "DIV",
    "-J": "CORPS",
    "-K": "ARMY",
}


def _sidc_echelon(sidc: str) -> str:
    """Extract echelon label from a 15-char SIDC (echelon at index 11)."""
    if len(sidc) >= 12:
        return _SIDC_ECH_MAP.get(sidc[10:12], "")
    return ""


class MainWindow(QMainWindow):
    def __init__(
        self,
        server_url: str,
        token: str,
        callsign: str,
        mission_id: Optional[int] = None,
    ):
        super().__init__()
        self._server_url = server_url
        self._token = token
        self._callsign = callsign
        self._client = ArrowClient(server_url, token)
        # Scope every request to the chosen mission (X-Mission-ID header).
        self._client.active_mission_id = mission_id
        self._role = "OPERATOR"
        self._clearance = 0
        self._my_operator_id: Optional[int] = None
        self._active_mission_id: Optional[int] = mission_id
        self._overlays: dict[int, dict] = {}  # Saved overlays, id → dto
        self._ws: Optional[WSListener] = None
        self._toasts = ToastManager(self)
        self._suppress_toasts = False
        self._voice = VoiceAlertPlayer(self)
        self._voice.enabled = _settings_bool(
            _settings_load("display_voice_alerts"), True
        )

        # Native OS location (macOS Core Location). QtWebEngine's
        # navigator.geolocation does not resolve a fix on macOS, so on darwin we
        # source the own-position fix natively and push it into the map HUD.
        self._location = LocationProvider(self)

        # Active draw target (where new graphics / symbols / free-draw go). Keys:
        #   "map:server"  → POST to backend, no layer (distributed + WS broadcast)
        #   "map:local"   → LocalStore, loose (offline; distribute later)
        #   "local:<id>"  → a local drawing layer (offline)
        #   "overlay:<id>"→ a distributed layer (server overlay; auto-attach)
        self._active_layer_key: str = "map:server"
        self._local_store = LocalStore()

        # Pending route colors: route_id → color (set when draw is requested)
        self._pending_route_colors: dict[str, str] = {}
        # MBTiles overlay registry: mbt_id → {path, name, min_zoom, max_zoom, visible}
        self._mbtiles: dict[str, dict] = {}
        self._mbtiles_dlg = MBTilesDialog(self)
        self._tile_server = MBTilesServer()
        port = self._tile_server.start()

        self._build_ui()
        # Load map via HTTP (fixes Qt6/macOS Metal compositor black-screen bug)
        self._map.set_map_server_port(port)
        self._connect_signals()
        self._start_ws()
        # Fallback in case bridge.map_ready never fires (e.g. a QWebChannel
        # hiccup). It must NOT fire blindly: the map page is large and reloaded
        # fresh each launch (HTTP cache is cleared), so at a fixed delay its
        # script may not have run yet — calling _load_all then pushes data into a
        # page whose functions don't exist ("X is not defined") AND the _loaded
        # guard would block the real map_ready from ever re-running it. So poll
        # for JS readiness and only then load.
        QTimer.singleShot(1800, self._fallback_load_when_ready)

        # Periodically refresh the Devices panel: FRONT online status decays on a
        # 90 s heartbeat and ATAK "last seen" ages even without WS events.
        if self._token:
            self._devices_timer = QTimer(self)
            self._devices_timer.setInterval(20_000)
            self._devices_timer.timeout.connect(self._load_devices)
            self._devices_timer.start()

    # ================================================================
    # UI
    # ================================================================
    def _build_ui(self):
        mode = "READ-ONLY" if not self._token else "COP"
        self.setWindowTitle(f"ARROW FRONT  —  {self._callsign.upper()}  —  {mode}")
        self.setMinimumSize(1024, 700)
        self.resize(1600, 960)

        from pathlib import Path
        from PyQt6.QtGui import QIcon

        icon_path = Path(__file__).parent.parent / "resources" / "arrow_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ---- Toolbar --------------------------------------------------
        self._toolbar = MainToolbar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

        # ---- Panels ---------------------------------------------------
        self._orbat_panel = ORBATPanel()
        self._devices_panel = DevicesPanel()
        self._firemissions_panel = FireMissionsPanel()
        self._reports_panel = ReportsPanel()
        self._messages_panel = MessagesPanel()
        self._alerts_panel = AlertsPanel()
        self._draw_panel = DrawPanel()
        self._missions_panel = MissionsPanel()
        self._strike_panel = StrikePackagePanel()
        self._opord_panel = OpordPanel()
        self._streams_panel = StreamsPanel()
        self._media_panel = MediaPanel()
        self._mumble_panel = MumblePanel()
        self._log_panel = LogPanel()
        self._routes_panel = RoutesPanel()
        self._planner_windows: list[StrikePlannerWindow] = []
        self._opord_windows: list[OpordWindow] = []
        self._stream_viewers: list[StreamViewerWindow] = []
        self._medevac_windows: list[MedevacWindow] = []
        self._fire_windows: list[FireMissionDialog] = []
        self._mortarcalc_windows: list = []

        # Right: vertical activity bar — feature panels open in the right window.
        self._right_panel = ActivityPanel(side="right", default_width=360)
        self._info = self._right_panel
        self._info.add_panel("missions", "◈", "MISS", self._missions_panel, "1")
        self._info.add_panel("strike", "◆", "STRK", self._strike_panel, "2")
        self._info.add_panel(
            "firemissions", "🎯", "FIRE", self._firemissions_panel, "F"
        )
        self._info.add_panel("opord", "📋", "OPORD", self._opord_panel, "3")
        self._info.add_panel("streams", "📡", "STRMS", self._streams_panel, "4")
        self._info.add_panel("reports", "≡", "RPTS", self._reports_panel, "5")
        self._info.add_panel("messages", "◎", "MSG", self._messages_panel, "6")
        self._info.add_panel("alerts", "⚡", "ALRT", self._alerts_panel, "7")
        self._info.add_panel("media", "🖼", "MEDIA", self._media_panel, "9")
        self._info.add_panel("mumble", "🎙", "VOICE", self._mumble_panel, "0")
        self._info.add_panel("log", "📋", "LOG", self._log_panel, "L")
        self._info.add_panel("routes", "🗺", "ROUTE", self._routes_panel, "N")

        # ---- Map ------------------------------------------------------
        self._map = MapView(self)
        self._map.set_auth(self._server_url, self._token)

        # ---- Side panels ----------------------------------------------
        # Left: vertical activity bar — ORBAT opens in the left window.
        # (Add further icons here later with another add_panel(...) call.)
        self._left_panel = ActivityPanel(side="left", default_width=270)
        self._left_panel.add_panel("orbat", "⊟", "ORBAT", self._orbat_panel, "O")
        self._left_panel.add_panel("devices", "📶", "DEVS", self._devices_panel, "D")
        self._left_panel.add_panel("draw", "✚", "DRAW", self._draw_panel, "8")
        # (self._right_panel was created above with all feature panels added.)

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

        # Bind splitter references (needed for resize logic). Fallback sizes
        # describe the fully-expanded 3-column layout (icon bar + content each
        # side) for the pre-layout case where the splitter reports zero widths.
        _fallback = [316, 900, 406]
        self._left_panel.bind_splitter(self._splitter, 0, fallback=_fallback)
        self._right_panel.bind_splitter(self._splitter, 2, fallback=_fallback)

        # Defer collapse until after window is shown and splitter has real px
        # dimensions. Both side panels start collapsed — only the icon bars show.
        QTimer.singleShot(0, self._left_panel.collapse)
        QTimer.singleShot(0, self._right_panel.collapse)

        # Map always stretches; panels have fixed initial sizes
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes([316, 900, 406])

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
        QShortcut(QKeySequence("F10"), self).activated.connect(self._take_screenshot)
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self._open_settings)

    # ================================================================
    # SIGNALS
    # ================================================================
    def _connect_signals(self):
        tb = self._toolbar
        # Each toolbar QMenu is a native popup that appears over the WebEngine
        # view and drops the Metal compositor framebuffer when it closes.
        for menu in tb.popup_menus:
            menu.aboutToHide.connect(self._map.notify_menu_closed)
        tb.mode_changed.connect(self._on_mode_from_toolbar)
        tb.layer_toggled.connect(self._map.toggle_layer)
        tb.group_level_changed.connect(self._map.set_group_level)
        tb.group_auto_changed.connect(self._map.set_group_auto)
        tb.base_changed.connect(self._map.set_base_layer)
        tb.fit_requested.connect(self._map.fit_tracks)
        tb.alert_requested.connect(self._send_alert)
        tb.mbtiles_manage.connect(self._open_mbtiles_manager)
        tb.weather_toggled.connect(self._map.set_weather_layer)
        tb.weather_fetch.connect(lambda: self._map._js("fetchWeatherAtCenter()"))
        tb.screenshot_requested.connect(self._take_screenshot)
        tb.config_requested.connect(self._open_settings)

        self._map.bridge.coords_changed.connect(self._statusbar.update_coords)
        self._map.bridge.own_position.connect(self._on_own_position)
        self._map.bridge.map_ready.connect(self._load_all)
        self._map.render_crashed.connect(self._on_render_crashed)
        self._map.bridge.radial_action.connect(self._on_radial_action)
        self._map.bridge.graphic_drawn.connect(self._on_graphic_drawn)
        self._map.bridge.measure_done.connect(
            lambda d, b: self.statusBar().showMessage(f"DIST {d}  BRG {b}", 6000)
        )

        self._orbat_panel.operator_focus_requested.connect(self._focus_operator)
        self._orbat_panel.message_requested.connect(
            lambda _: self._info.activate("messages")
        )
        self._devices_panel.operator_focus_requested.connect(self._focus_operator)
        self._devices_panel.coord_focus_requested.connect(
            lambda lat, lon: self._map.center_on(lat, lon, zoom=16)
        )
        self._firemissions_panel.refresh_requested.connect(self._load_fire_missions)
        self._firemissions_panel.locate_requested.connect(
            lambda lat, lon: self._map.center_on(lat, lon, zoom=15)
        )
        self._firemissions_panel.status_change_requested.connect(
            self._on_fm_status_change
        )
        self._reports_panel.locate_requested.connect(
            lambda lat, lon: self._map.center_on(lat, lon, zoom=14)
        )
        self._messages_panel.message_send_requested.connect(self._send_message_scoped)
        self._messages_panel.manage_rooms_requested.connect(self._open_room_manager)
        self._draw_panel.draw_mode_changed.connect(self._map.set_draw_mode)
        self._draw_panel.draw_graphic.connect(self._map.set_draw_graphic)
        self._draw_panel.free_draw_changed.connect(self._map.set_free_draw)
        self._draw_panel.free_draw_undo.connect(self._map.free_draw_undo)
        self._draw_panel.free_draw_clear.connect(self._map.free_draw_clear)
        self._draw_panel.delete_all_graphics.connect(self._on_delete_all_graphics)
        self._draw_panel.place_symbol_requested.connect(self._on_place_symbol)
        self._draw_panel.add_layer_requested.connect(self._import_kml_file)
        self._draw_panel.layer_target_changed.connect(self._on_layer_target_changed)
        self._draw_panel.layer_create_requested.connect(self._on_layer_create)
        self._draw_panel.layer_rename_requested.connect(self._on_layer_rename)
        self._draw_panel.layer_delete_requested.connect(self._on_layer_delete)
        self._draw_panel.layer_distribute_requested.connect(self._on_layer_distribute)
        self._draw_panel.layer_export_requested.connect(self._export_layer_target)
        self._map.bridge.symbol_selected.connect(self._on_symbol_placed)
        self._map.bridge.free_draw_saved.connect(self._on_free_draw_saved)
        self._map.bridge.overlay_create_requested.connect(self._on_overlay_create)
        self._map.bridge.overlay_patch_requested.connect(self._on_overlay_patch)
        self._map.bridge.overlay_delete_requested.connect(self._on_overlay_delete)
        self._map.bridge.layer_export_requested.connect(self._on_layer_export)
        self._map.bridge.layer_import_requested.connect(self._on_layer_import)
        self._map.bridge.tactical_object_action.connect(self._on_tactical_object_action)
        self._map.bridge.tactical_object_move.connect(self._on_tactical_object_move)
        self._map.bridge.route_drawn.connect(self._on_route_drawn)
        self._map.bridge.route_draw_cancelled.connect(
            self._on_route_draw_cancelled_from_map
        )
        self._map.file_dropped.connect(self._on_file_dropped_on_map)

        self._routes_panel.route_draw_requested.connect(self._on_route_draw_requested)
        self._routes_panel.route_draw_cancelled.connect(
            lambda: self._map.cancel_route_drawing()
        )
        self._routes_panel.route_deleted.connect(self._on_route_deleted)
        self._routes_panel.route_visibility_changed.connect(self._map.set_route_visible)
        self._routes_panel.route_focus_requested.connect(self._map.center_on_route)
        self._routes_panel.route_edit_done.connect(self._on_route_updated)
        self._routes_panel.route_add_requested.connect(self._on_route_add)
        self._routes_panel.navigate_requested.connect(self._on_navigate_requested)
        self._map.bridge.nav_completed.connect(self._on_nav_completed)
        self._map.bridge.nav_stopped.connect(lambda: None)
        self._missions_panel.mission_selected.connect(self._on_mission_selected)
        self._missions_panel.mission_cleared.connect(self._on_mission_cleared)
        self._missions_panel.refresh_requested.connect(self._load_missions)
        self._missions_panel.delete_all_requested.connect(self._on_delete_all_missions)

        self._strike_panel.refresh_requested.connect(self._load_strike_packages)
        self._opord_panel.refresh_requested.connect(self._load_opords)
        self._opord_panel.open_requested.connect(self._open_opord)
        self._opord_panel.create_requested.connect(self._new_opord)

        self._streams_panel.stream_open_requested.connect(self._open_stream)
        self._streams_panel.recording_open_requested.connect(self._open_recording)
        self._streams_panel.refresh_requested.connect(self._load_streams)
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
        ws_base = (
            self._server_url.replace("http://", "ws://")
            .replace("https://", "wss://")
            .rstrip("/")
        )
        # Strip /api suffix — WS endpoint is at /ws, not /api/ws
        if ws_base.endswith("/api"):
            ws_base = ws_base[:-4]
        log.info("WS base URL: %s", ws_base)
        self._ws = WSListener(ws_base, self._token)
        self._ws.track_received.connect(self._on_track)
        self._ws.cot_received.connect(self._on_cot)
        self._ws.alert_received.connect(self._on_alert)
        self._ws.report_received.connect(self._on_report)
        self._ws.message_received.connect(self._on_message)
        self._ws.graphic_received.connect(self._on_tact_obj_event)
        self._ws.vehicle_received.connect(self._on_vehicle_event)
        self._ws.fire_mission_received.connect(self._on_fm_event)
        self._ws.kml_received.connect(self._on_kml_event)
        self._ws.overlay_received.connect(self._on_overlay_event)
        self._ws.presence_changed.connect(self._on_presence)
        self._ws.cot_presence_changed.connect(self._on_cot_presence)
        self._ws.mission_received.connect(self._on_mission_event)
        self._ws.strike_package_received.connect(self._on_strike_ws)
        self._ws.stream_received.connect(self._on_stream_ws)
        self._ws.connection_changed.connect(self._statusbar.set_connected)
        self._ws.start()

    # ================================================================
    # INITIAL DATA LOAD
    # ================================================================
    _loaded = False

    def _fallback_load_when_ready(self):
        """Poll the map page for JS readiness, then run the initial load.

        Acts as a safety net if bridge.map_ready never arrives. If map_ready
        already fired, the _loaded guard makes this a no-op. Otherwise it probes
        the page and only loads once the map script has actually defined its
        functions — never pushing data into a half-loaded page.
        """
        if self._loaded:
            return

        def _on_probe(ready):
            if self._loaded:
                return
            if ready:
                self._load_all()
            else:
                QTimer.singleShot(400, self._fallback_load_when_ready)

        self._map.eval_js("typeof setGPSConfig === 'function'", _on_probe)

    def _load_all(self):
        if self._loaded:
            return
        self._loaded = True
        self._suppress_toasts = True
        self._load_default_map()
        self._restore_mbtiles()
        self._load_saved_routes()
        self._apply_gps_config()
        self._resolve_role()
        self._load_hierarchy()
        self._load_devices()
        self._load_missions()
        self._load_opords()
        self._load_streams()
        self._load_strike_packages()
        self._load_live_operators()
        self._load_cot_tracks()
        self._load_vehicles()
        self._load_tactical_objects()
        self._load_fire_missions()
        self._load_kml_layers()
        self._load_overlays()
        self._load_alerts()
        self._load_reports()
        self._load_messages()
        self._load_local_objects()
        self._suppress_toasts = False

    # ================================================================
    # MENU BAR
    # ================================================================

    def _build_menu(self):
        mb = self.menuBar()

        # ── File ────────────────────────────────────────────────────
        file_menu = mb.addMenu("File")

        act_settings = QAction("Configuration…", self)
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)

        file_menu.addSeparator()

        act_logout = QAction("Log Out…", self)
        act_logout.setStatusTip("Sign out and return to the login screen")
        act_logout.triggered.connect(self._logout)
        file_menu.addAction(act_logout)

        file_menu.addSeparator()

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
            ("Missions", "missions"),
            ("Strike Packages", "strike"),
            ("Fire Missions", "firemissions"),
            ("OPORDs", "opord"),
            ("Reports", "reports"),
            ("Messages", "messages"),
            ("Alerts", "alerts"),
            ("Media Gallery", "media"),
        ]:
            act = QAction(name, self)
            act.triggered.connect(
                lambda _, p=panel: (self._right_panel.expand(), self._info.activate(p))
            )
            view_menu.addAction(act)

        # Draw now lives in the left activity bar alongside ORBAT/Devices.
        act_draw = QAction("Draw", self)
        act_draw.triggered.connect(
            lambda _: (self._left_panel.expand(), self._left_panel.activate("draw"))
        )
        view_menu.addAction(act_draw)

        # ── Fire Support ────────────────────────────────────────────
        fs_menu = mb.addMenu("Fire Support")
        act_mortarcalc = QAction("Mortar FDC (MortarCalc)…", self)
        act_mortarcalc.setStatusTip(
            "Open the 81 mm mortar fire-direction-centre calculator"
        )
        act_mortarcalc.triggered.connect(self._open_mortarcalc)
        fs_menu.addAction(act_mortarcalc)

        # ── Admin ───────────────────────────────────────────────────
        self._admin_menu = mb.addMenu("Admin")
        self._admin_menu.setEnabled(False)  # unlocked after role resolved

        act_del_missions = QAction("Delete All Missions…", self)
        act_del_missions.setStatusTip(
            "Permanently delete every mission from the server (ADMIN only)"
        )
        act_del_missions.triggered.connect(self._confirm_delete_all_missions)
        self._admin_menu.addAction(act_del_missions)

        act_del_packages = QAction("Delete All Strike Packages…", self)
        act_del_packages.setStatusTip(
            "Permanently delete all strike packages (ADMIN only)"
        )
        act_del_packages.triggered.connect(self._confirm_delete_all_packages)
        self._admin_menu.addAction(act_del_packages)

        self._admin_menu.addSeparator()

        act_jdss = QAction("JDSS Gateway…", self)
        act_jdss.setStatusTip("Configure & monitor the JDSSArrow coalition bridge")
        act_jdss.triggered.connect(self._open_jdss_gateway)
        self._admin_menu.addAction(act_jdss)

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
            self,
            "Exit",
            "Exit Arrow Front?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Yes:
            sys.exit(0)

    def _logout(self):
        ans = QMessageBox.question(
            self,
            "Log Out",
            f"Log out {self._callsign}?\nYou'll return to the login screen.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        # Forget the saved token so auto-login won't silently reconnect. Keep the
        # server URL + callsign so the login dialog stays pre-filled.
        try:
            from front.client import auth as keyring_auth

            keyring_auth.clear_token(self._server_url)
        except Exception:
            pass
        # Relaunch a fresh process — with the token gone, it lands on the login
        # dialog. Detach first, then exit this instance.
        QProcess.startDetached(sys.executable, sys.argv)
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
            QMessageBox.information(
                self, "Delete Strike Packages", "No packages on server."
            )
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
                    f"Deleted {n-failed}/{n} packages — {failed} failed", 5000
                )
            else:
                self._toasts.show("info", "PACKAGES DELETED", f"{n} removed")

    def _reload_all(self):
        self._loaded = False
        self._load_all()
        self.statusBar().showMessage("Data reloaded", 3000)

    def _on_render_crashed(self):
        """The map's render process crashed and MapView is reloading the page.

        Drop the load guard so the fresh page's map_ready re-runs _load_all and
        re-pushes all data; otherwise the recovered map would come back empty.
        """
        self._loaded = False
        self.statusBar().showMessage("Map renderer restarted — reloading data…", 4000)

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

    def _open_mortarcalc(self):
        """Open the MortarCalc 81 mm mortar FDC as a standalone Front-owned window.

        Built lazily: importing mortarcalc pulls in its QtWebEngine map panel,
        which is safe here because Front already imports QtWebEngineWidgets at
        module load (front.map.view), before the QApplication was created. A
        reference is kept so the window is not garbage-collected.
        """
        # Re-use an already-open window instead of spawning duplicates.
        for w in self._mortarcalc_windows:
            try:
                if w.isVisible():
                    w.showNormal()
                    w.raise_()
                    w.activateWindow()
                    return
            except RuntimeError:
                pass  # underlying C++ window was destroyed; fall through to rebuild
        try:
            from mortarcalc.app import build_window

            win = build_window()
        except Exception as e:
            log.exception("MortarCalc failed to open")
            QMessageBox.critical(self, "MortarCalc", f"Could not open MortarCalc:\n{e}")
            return
        # Mirror MortarCalc pieces / FOs / targets onto the Front COP map while
        # the FDC window is open. FOs are linked to live operators by call sign.
        try:
            from front.integrations.mortarcalc_bridge import MortarcalcMapBridge

            win._map_bridge = MortarcalcMapBridge(
                win, self._map, operators_provider=self._client.live_operators
            )
            win.closing.connect(lambda w=win: self._on_mortarcalc_closed(w))
        except Exception:
            log.exception("MortarCalc map bridge failed to attach")

        # Also mirror onto the web map via the Arrow backend REST API, and
        # show a Front toast whenever a group transitions to SHOT / IN_EFFECT.
        try:
            from front.integrations.mortarcalc_bridge import MortarcalcWebBridge

            win._web_bridge = MortarcalcWebBridge(
                win,
                arrow_client=self._client,
                toast_callback=lambda msg: self._toasts.show(
                    "mission", "MORTARS FIRING", msg
                ),
            )
        except Exception:
            log.exception("MortarCalc web bridge failed to attach")

        win.show()
        win.raise_()
        win.activateWindow()
        self._mortarcalc_windows.append(win)

    def _on_mortarcalc_closed(self, win):
        """Drop a closed MortarCalc window so it is not reused or leaked."""
        try:
            self._mortarcalc_windows.remove(win)
        except ValueError:
            pass

    # ================================================================
    # SETTINGS / CONFIGURATION
    # ================================================================
    def _open_settings(self):
        dlg = ConfigDialog(self)
        dlg.gps_config_changed.connect(self._on_gps_config)
        dlg.base_layer_changed.connect(self._map.set_base_layer)
        dlg.trails_changed.connect(lambda on: self._map.toggle_layer("operTrails", on))
        dlg.voice_alerts_changed.connect(lambda on: setattr(self._voice, "enabled", on))
        dlg.exec()

    def _open_jdss_gateway(self):
        from front.app.jdss_dialog import JdssGatewayDialog

        JdssGatewayDialog(self, client=self._client, role=self._role).exec()

    _native_loc_wired = False

    def _wire_native_location(self):
        """Connect the native location provider to the map HUD once."""
        if self._native_loc_wired:
            return
        self._native_loc_wired = True
        self._location.position_changed.connect(self._map.set_own_position_native)
        self._location.status_changed.connect(self._map.set_own_position_status)

    def _apply_native_location(self, enabled: bool, high_acc: bool):
        """Start/stop native OS location to match the GPS config (macOS only)."""
        if not _native_loc_supported():
            return
        if enabled:
            self._wire_native_location()
            self._location.start(high_accuracy=high_acc)
        else:
            self._location.stop()

    def _apply_gps_config(self):
        enabled, high_acc, max_age, center, show_acc = read_gps_config()
        self._map.set_gps_config(enabled, high_acc, max_age, center, show_acc)
        self._apply_native_location(enabled, high_acc)

    def _on_gps_config(
        self, enabled: bool, high_acc: bool, max_age: int, center: bool, show_acc: bool
    ):
        self._map.set_gps_config(enabled, high_acc, max_age, center, show_acc)
        self._apply_native_location(enabled, high_acc)

    def _resolve_role(self):
        try:
            me = self._client.me()
            self._role = me.get("role", "OPERATOR")
            self._clearance = int(me.get("clearance", 0) or 0)
            self._my_operator_id = me.get("id")
            self._callsign = me.get("callsign", self._callsign)
            log.info("Authenticated: callsign=%s role=%s", self._callsign, self._role)
            self._messages_panel.set_my_callsign(self._callsign)
            self._messages_panel.set_server(self._server_url, self._token)
            self._media_panel.set_client(self._client)
            self._unlock_admin_menu()
            mode = "READ-ONLY" if not self._token else "COP"
            self.setWindowTitle(
                f"ARROW FRONT  —  {self._callsign.upper()}"
                f"  [{self._role}]  —  {mode}"
            )
            self._render_classification_banner()
        except Exception:
            pass

    def _render_classification_banner(self):
        """Show the active mission's classification as a colour-coded menu-bar badge."""
        from front.app.mission_dialog import CLASS_COLORS, class_name

        level = 0
        try:
            if self._active_mission_id:
                level = int(
                    self._client.mission(self._active_mission_id).get("classification", 0)
                    or 0
                )
        except Exception:
            level = 0
        level = max(0, min(4, level))
        badge = getattr(self, "_class_badge", None)
        if badge is None:
            badge = QLabel()
            badge.setContentsMargins(10, 0, 10, 0)
            self.menuBar().setCornerWidget(badge, Qt.Corner.TopRightCorner)
            self._class_badge = badge
        badge.setText(f" {class_name(level)} ")
        badge.setStyleSheet(
            f"background:{CLASS_COLORS[level]};color:#fff;font-weight:700;"
            "font-size:11px;letter-spacing:.08em;border-radius:4px;"
        )

    def _load_hierarchy(self):
        try:
            data = self._client.hierarchy()
            import sys

            print(
                f"[ORBAT] keys={list(data.keys()) if isinstance(data,dict) else type(data)}",
                file=sys.stderr,
            )
            companies = data.get("companies", []) if isinstance(data, dict) else []
            print(
                f"[ORBAT] companies={len(companies)}, "
                f"unassigned={len(data.get('unassigned_operators',[]))}",
                file=sys.stderr,
            )
            self._orbat_panel.load_hierarchy(data)
            self._map.set_hierarchy(data)
        except Exception as e:
            import sys

            print(f"[ORBAT] error: {e}", file=sys.stderr)

    def _load_devices(self):
        """Refresh the Devices panel: FRONT (Arrow ops) + ATAK (CoT clients)."""
        try:
            self._devices_panel.load_front(self._client.live_operators())
        except Exception:
            pass
        try:
            self._devices_panel.load_atak(self._client.cot_clients())
        except Exception:
            pass

    def _load_live_operators(self):
        try:
            ops = self._client.live_operators()
            self._messages_panel.set_operators(ops)
            for op in ops:
                if op.get("latitude") and op.get("longitude"):
                    self._push_track(
                        {
                            "id": op.get("operator_id") or op.get("id"),
                            "callsign": op.get("callsign", "?"),
                            "lat": op["latitude"],
                            "lon": op["longitude"],
                            "heading": op.get("heading"),
                            "speed": op.get("speed"),
                            "unit": op.get("team", ""),
                            "online": True,
                            "last_seen": op.get("recorded_at", ""),
                            "position_source": op.get("position_source"),
                        }
                    )
            # Keep MortarCalc FO markers pinned to fresh operator positions.
            for w in self._mortarcalc_windows:
                bridge = getattr(w, "_map_bridge", None)
                if bridge is not None:
                    bridge.sync()
        except Exception:
            pass

    def _load_cot_tracks(self):
        try:
            for t in self._client.cot_tracks():
                self._map.update_cot_track(t)
        except Exception:
            pass

    def _load_vehicles(self):
        self._vehicles = {}  # id -> vehicle dto; position follows assigned operator
        try:
            for v in self._client.vehicles():
                self._vehicles[v["id"]] = v
                self._map.update_vehicle(v)
        except Exception:
            pass

    def _load_tactical_objects(self):
        try:
            for obj in self._client.tactical_objects():
                self._map.add_tactical_object(obj)
        except Exception:
            pass

    def _load_fire_missions(self):
        # Resolve operator callsigns for the FDC queue labels (best-effort).
        try:
            self._firemissions_panel.set_operators(self._client.operators())
        except Exception:
            pass
        self._firemissions_panel.set_role(self._role, self._my_operator_id)
        try:
            missions = self._client.fire_missions()
            self._firemissions_panel.load_missions(missions)
            for fm in missions:
                self._map.add_fire_mission(fm)
        except Exception:
            pass

    def _on_fm_status_change(self, fm_id: int, new_status: str):
        try:
            fm = self._client.update_fire_mission(fm_id, status=new_status)
            self._firemissions_panel.upsert_mission(fm)
            self._map.add_fire_mission(fm)
        except Exception as e:
            self.statusBar().showMessage(f"Status update failed: {e}", 4000)

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

    # ---- Saved overlays + layer export/import -----------------------
    def _can_edit_overlays(self) -> bool:
        return self._role in ("ADMIN", "BATTLE_CAPTAIN")

    def _overlay_payload(self) -> list[dict]:
        """Right-panel overlay list = server overlays + local layers (as pseudo-
        overlays so they get a checkbox and the same visibility filter)."""
        out: list[dict] = list(self._overlays.values())
        for layer in self._local_store.list_layers():
            ids = [o["id"] for o in self._local_store.objects_for_layer(layer["id"])]
            out.append(
                {
                    "id": f"local:{layer['id']}",
                    "name": f"💾 {layer['name']}",
                    "object_ids": ids,
                    "local": True,
                }
            )
        return out

    def _push_overlays(self):
        # canEdit reflects server-overlay rights; local entries hide their CRUD
        # in the panel and are managed from the Draw panel instead.
        self._map.set_overlays(self._overlay_payload(), self._can_edit_overlays())
        self._refresh_layer_combo()

    def _activate_target_overlay(self):
        """Check the active draw-target layer in the right panel so what you draw
        into it stays visible (members are hidden unless their layer is on)."""
        k = self._active_layer_key
        if k.startswith("local:"):
            self._map.set_overlay_active(k, True)
        elif k.startswith("overlay:"):
            self._map.set_overlay_active(int(k.split(":", 1)[1]), True)

    def _load_overlays(self):
        try:
            self._overlays = {o["id"]: o for o in self._client.overlays()}
        except Exception:
            self._overlays = {}
        self._push_overlays()

    def _on_overlay_event(self, data: dict):
        """WS `overlay` channel — keep the in-map panel in sync across clients."""
        event = data.get("event", "")
        oid = data.get("id")
        if event == "deleted" and oid is not None:
            self._overlays.pop(oid, None)
            self._push_overlays()
            return
        # created/updated payloads carry the full OverlayOut; fall back to a
        # reload if a thin payload ever arrives.
        if oid is not None and "object_ids" in data:
            self._overlays[oid] = data
            self._push_overlays()
        else:
            self._load_overlays()

    def _on_overlay_create(self, json_str: str):
        try:
            d = json.loads(json_str)
            ov = self._client.create_overlay(
                d.get("name", "Overlay"),
                d.get("description", ""),
                d.get("object_ids") or [],
            )
            self._overlays[ov["id"]] = ov
            self._push_overlays()
        except Exception as e:
            self.statusBar().showMessage(f"Overlay create failed: {e}", 4000)

    def _on_overlay_patch(self, overlay_id: int, json_str: str):
        try:
            ov = self._client.patch_overlay(overlay_id, **json.loads(json_str))
            self._overlays[ov["id"]] = ov
            self._push_overlays()
        except Exception as e:
            self.statusBar().showMessage(f"Overlay update failed: {e}", 4000)

    def _on_overlay_delete(self, overlay_id: int):
        try:
            self._client.delete_overlay(overlay_id)
            self._overlays.pop(overlay_id, None)
            self._push_overlays()
        except Exception as e:
            self.statusBar().showMessage(f"Overlay delete failed: {e}", 4000)

    def _on_layer_export(self, kind: str, source_id: int):
        try:
            env = self._client.export_layer(kind, source_id)
        except Exception as e:
            self.statusBar().showMessage(f"Export failed: {e}", 4000)
            return
        default = f"{env.get('name', 'layer')}.{kind.lower()}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export layer", default, "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(env, f, indent=2)
            self.statusBar().showMessage(f"Exported to {path}", 4000)
        except OSError as e:
            self.statusBar().showMessage(f"Could not write file: {e}", 4000)

    def _on_layer_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import layer", "", "JSON (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                env = json.load(f)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Import Failed", f"Not a valid layer file:\n{e}")
            return
        try:
            res = self._client.import_layer(env, self._active_mission_id)
        except Exception as e:
            msg = (
                "Permission denied (need BATTLE_CAPTAIN/ADMIN)."
                if "403" in str(e)
                else str(e)
            )
            QMessageBox.critical(self, "Import Failed", msg)
            return
        kind = res.get("kind", "")
        if kind == "OVERLAY":
            self._load_overlays()
        elif kind == "KML":
            try:
                self._map.add_kml_layer(self._client.kml_layer(res["id"]))
            except Exception:
                pass
        self._toasts.show("info", "LAYER IMPORTED", res.get("name", "").upper())

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
        self._load_chatrooms()

    def _load_chatrooms(self):
        try:
            self._messages_panel.set_rooms(self._client.chatrooms())
        except Exception:
            pass

    def _open_room_manager(self):
        try:
            ops = self._client.operators()
        except Exception:
            ops = []
        dlg = RoomManagerDialog(self._client, ops, self)
        dlg.rooms_changed.connect(self._load_chatrooms)
        dlg.exec()
        self._load_chatrooms()

    def _load_missions(self):
        try:
            missions = self._client.missions()
            import sys

            print(
                f"[MISSIONS] role={self._role} count={len(missions)}", file=sys.stderr
            )
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
        log.debug(
            "TRACK  %s  lat=%.5f lon=%.5f hdg=%s",
            data.get("callsign"),
            data.get("lat", 0),
            data.get("lon", 0),
            data.get("heading"),
        )
        self._push_track(data)
        self._orbat_panel.update_from_tracking(data)
        # Vehicles assigned to this operator inherit its position.
        op_id = data.get("operator_id") or data.get("id")
        lat = data.get("lat") or data.get("latitude")
        lon = data.get("lon") or data.get("longitude")
        if op_id is not None and lat and lon:
            for v in getattr(self, "_vehicles", {}).values():
                if v.get("operator_id") == op_id:
                    v["latitude"], v["longitude"] = float(lat), float(lon)
                    self._map.update_vehicle(v)

    def _on_cot(self, data: dict):
        event = data.get("event", "update")
        if event == "delete":
            uid = data.get("cot_uid") or data.get("uid")
            if uid:
                self._map._js(f"removeCotTrack({json.dumps(uid)})")
        else:
            self._map.update_cot_track(data)

    def _on_alert(self, data: dict):
        log.warning(
            "ALERT  type=%s  operator=%s",
            data.get("type"),
            data.get("operator") or data.get("callsign"),
        )
        self._alerts_panel.add_alert(data)
        lat = data.get("latitude") or data.get("lat")
        lon = data.get("longitude") or data.get("lon")
        if lat and lon:
            self._map.add_alert_marker({**data, "lat": lat, "lon": lon})
        self._info.inc_badge("alerts")
        alert_type = data.get("type", "ALERT")
        operator = data.get("operator") or data.get("callsign") or ""
        if not self._suppress_toasts:
            self._toasts.alert(alert_type, operator)
            self._voice.play(alert_type)
            # Only pop the panel open for LIVE alerts — historical alerts replayed
            # during _load_all must not re-expand the (default-collapsed) panel.
            if alert_type in ("TIC", "DRONE_SPOTTED"):
                self._right_panel.expand()
                self._info.activate("alerts")

    def _on_report(self, data: dict):
        self._reports_panel.add_report(data)
        self._info.inc_badge("reports")
        rtype = data.get("type", "REPORT")
        sender = data.get("sender") or data.get("callsign") or ""
        if not self._suppress_toasts:
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

    def _on_vehicle_event(self, data: dict):
        cache = getattr(self, "_vehicles", None)
        if cache is None:
            cache = self._vehicles = {}
        # The 'deleted' broadcast carries only {"id": ...} — no callsign.
        if "callsign" not in data:
            cache.pop(data.get("id"), None)
            self._map.remove_vehicle(data.get("id"))
        else:
            cache[data["id"]] = data
            self._map.update_vehicle(data)

    def _on_fm_event(self, data: dict):
        self._map.add_fire_mission(data)
        self._firemissions_panel.upsert_mission(data)
        # The WS listener forwards only the inner data dict. A fresh submission
        # carries `callsign`; an FDC update carries `updated_by` instead.
        is_new = bool(data.get("callsign")) and "updated_by" not in data
        if is_new and not self._suppress_toasts:
            sender = data.get("callsign", "")
            if sender != self._callsign:
                self._info.inc_badge("firemissions")
                self._toasts.show(
                    "mission",
                    "FIRE MISSION",
                    f"{sender} · {data.get('mission_type','')}",
                )

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
        # Room lifecycle events (room_created / member_added / …) ride the `chat`
        # channel but carry a room dict, not a message — refresh the room list.
        if "message_type" not in data:
            self._load_chatrooms()
            return
        self._messages_panel.add_message(data)
        sender = data.get("sender") or data.get("callsign") or "?"
        if sender != self._callsign:
            preview = (data.get("content") or "")[:60]
            if not self._suppress_toasts:
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
        tact_objs = bundle.get("tactical_objects") or bundle.get(
            "_tactical_objects_expanded", []
        )
        for obj in tact_objs:
            self._map.add_tactical_object(obj)
        # Center map on target if available
        tlat = bundle.get("target_lat")
        tlon = bundle.get("target_lon")
        if tlat and tlon:
            self._map.center_on(float(tlat), float(tlon), zoom=13)
        name = bundle.get("name", "package")
        self._toasts.show("mission", "OVERLAY LOADED", name.upper())

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
        name = data.get("name", "Strike package")
        if event in ("activated",):
            self._toasts.show("mission", "STRIKE PKG ACTIVATED", name.upper())
        elif event in ("created",):
            self._toasts.show("info", "NEW STRIKE PKG", name.upper())

    def _load_opords(self):
        try:
            self._opord_panel.load_opords(self._client.opords())
        except Exception as e:
            import sys

            print(f"[OPORD] error: {e}", file=sys.stderr)

    def _open_opord(self, opord_data: dict):
        """Open existing OPORD in editor window."""
        try:
            full = self._client.opord(opord_data["id"])
        except Exception:
            full = opord_data
        win = OpordWindow(
            self._client, full, map_capture_fn=lambda: self._map.grab(), parent=self
        )
        win.saved.connect(lambda _: self._load_opords())
        win.published.connect(lambda _: self._load_opords())
        win.show()
        self._opord_windows.append(win)

    def _new_opord(self):
        """Open blank OPORD editor."""
        win = OpordWindow(
            self._client, None, map_capture_fn=lambda: self._map.grab(), parent=self
        )
        win.saved.connect(lambda _: self._load_opords())
        win.show()
        self._opord_windows.append(win)

    def _load_streams(self):
        try:
            live = self._client.live_streams()
            self._streams_panel.load_live_streams(live)
        except Exception:
            pass
        try:
            ext = self._client.external_streams()
            self._streams_panel.load_external_streams(ext)
        except Exception:
            pass
        try:
            oct_streams = self._client.octopus_streams()
            self._streams_panel.load_octopus_streams(oct_streams)
        except Exception:
            pass
        try:
            recs = self._client.recordings()
            self._streams_panel.load_recordings(recs)
        except Exception:
            pass

    def _open_stream(self, stream: dict, stream_type: str):
        if stream_type in ("ws_jpeg", "android", "live"):
            win = StreamViewerWindow.open_android(
                stream, self._server_url, self._token, parent=self
            )
        elif stream_type == "hls":
            win = StreamViewerWindow.open_octopus(
                stream, self._server_url, self._token, parent=self
            )
        else:
            win = StreamViewerWindow.open_external(
                stream, self._server_url, self._token, parent=self
            )
        win.show()
        self._stream_viewers.append(win)
        self._toasts.show(
            "info", "STREAM OPENED", stream.get("callsign") or stream.get("name", "")
        )

    def _open_recording(self, rec: dict):
        win = StreamViewerWindow.open_recording(
            rec, self._server_url, self._token, parent=self
        )
        win.show()
        self._stream_viewers.append(win)

    def _on_stream_ws(self, data: dict):
        event = data.get("event", "")
        if event == "started":
            self._streams_panel.add_live_stream(data.get("data", data))
            self._info.inc_badge("streams")
            cs = (data.get("data") or data).get("callsign", "")
            self._toasts.show("info", "STREAM STARTED", cs)
        elif event == "ended":
            sid = (data.get("data") or data).get("id", "")
            self._streams_panel.remove_live_stream(str(sid))

    def _on_mission_event(self, data: dict):
        self._load_missions()

    def _on_presence(self, data: dict):
        op_id = data.get("operator_id")
        online = data.get("online", False)
        if op_id is not None:
            self._orbat_panel.update_operator_presence(int(op_id), online)
        # FRONT roster reflects live operator presence — refresh it.
        try:
            self._devices_panel.load_front(self._client.live_operators())
        except Exception:
            pass

    def _on_cot_presence(self, _data: dict):
        """An ATAK TCP client connected/disconnected — refresh the ATAK roster."""
        try:
            self._devices_panel.load_atak(self._client.cot_clients())
        except Exception:
            pass

    # ================================================================
    # RADIAL MENU ACTIONS
    # ================================================================
    def _on_mission_selected(self, mission: dict):
        mid = mission.get("id")
        self._active_mission_id = mid
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
                f" — {failed} failed (ADMIN required)",
                6000,
            )
        else:
            self._toasts.show(
                "info",
                "ALL MISSIONS DELETED",
                f"{len(missions)} mission{'s' if len(missions)!=1 else ''} removed",
            )

    def _on_mission_cleared(self):
        self._active_mission_id = None
        mode = "READ-ONLY" if not self._token else "COP"
        self.setWindowTitle(f"ARROW FRONT  —  {self._callsign.upper()}  —  {mode}")

    def _on_symbol_placed(
        self,
        sidc: str,
        designation: str,
        lat: float,
        lon: float,
        active_overlay_id: int = 0,
    ):
        """User placed a symbol via the picker — save to server as tactical object."""
        from PyQt6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QDialogButtonBox,
            QFileDialog,
            QLabel,
            QPushButton,
        )

        aff_map = {
            "F": "FRIENDLY",
            "H": "HOSTILE",
            "N": "NEUTRAL",
            "U": "UNKNOWN",
            "A": "FRIENDLY",
        }
        affiliation = aff_map.get(sidc[1] if len(sidc) > 1 else "U", "UNKNOWN")
        obj_type = "ENEMY" if affiliation == "HOSTILE" else "MARKER"
        echelon = _sidc_echelon(sidc)

        # Offer optional photo attachment — server targets only (photos live on
        # the backend, so they don't apply to local layers; the dialog is built
        # but only shown when the active target is a server one).
        photo_id: Optional[int] = None
        dlg = QDialog(self)
        dlg.setWindowTitle("Attach Photo/Video?")
        dlg.setMinimumWidth(300)
        layout = QVBoxLayout(dlg)
        layout.addWidget(
            QLabel(
                f"Symbol: {designation or sidc}\nAttach a photo or video? (optional)"
            )
        )
        file_label = QLabel("None selected")
        file_label.setStyleSheet("color:#8b949e;font-size:9px;")
        file_path: list[str] = []

        def pick():
            path, _ = QFileDialog.getOpenFileName(
                dlg,
                "Attach Photo or Video",
                "",
                "Media (*.jpg *.jpeg *.png *.gif *.webp *.mp4 *.webm *.mov *.ogv);;All Files (*)",
            )
            if path:
                file_path.clear()
                file_path.append(path)
                from pathlib import Path

                file_label.setText(f"📎 {Path(path).name}")

        row = QHBoxLayout()
        pick_btn = QPushButton("📎 Browse…")
        pick_btn.clicked.connect(pick)
        row.addWidget(pick_btn)
        row.addWidget(file_label, 1)
        layout.addLayout(row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if not self._target_is_local() and dlg.exec() == QDialog.DialogCode.Accepted:
            if file_path:
                try:
                    photo_id = self._client.upload_media(file_path[0])
                except Exception as e:
                    self._statusbar.showMessage(f"Upload failed: {e}", 4000)

        geometry = {"type": "point", "coords": [[lat, lon]]}
        try:
            obj = self._save_drawn(
                obj_type,
                geometry,
                notes=designation or "",
                affiliation=affiliation,
                symbol_code=sidc,
                echelon=echelon,
                photo_id=photo_id,
                fallback_overlay_id=active_overlay_id,
            )
        except Exception as e:
            self._statusbar.showMessage(f"Symbol not saved: {e}", 3000)
            return
        # Local symbols are already rendered by _save_drawn; for server symbols
        # render immediately (the picker has no optimistic preview).
        if obj is not None and not obj.get("local"):
            self._map.add_tactical_object(obj)

    def _on_mode_from_toolbar(self, mode: str):
        """Route toolbar mode changes — handle measure modes separately."""
        if mode == "measure_dist":
            self._map._js("startMeasure('distance')")
        elif mode == "measure_az":
            self._map._js("startMeasure('azimuth')")
        elif mode == "measure_range":
            self._map._js("startRangeMode()")
        elif mode == "meas_clear":
            self._map._js("clearMeasure(); clearRangeCircles(); closeRangePanel()")
        else:
            self._map.set_draw_mode(mode)

    def _on_radial_action(self, action: str, lat: float, lon: float):
        if action == "tic":
            self._send_alert("TIC", lat=lat, lon=lon)
            self._place_radial_marker(
                "HOSTILE", lat, lon, notes="TIC", affiliation="HOSTILE"
            )
        elif action == "drone":
            self._send_alert("DRONE_SPOTTED", lat=lat, lon=lon)
            self._place_radial_marker(
                "DRONE", lat, lon, notes="DRONE", affiliation="HOSTILE"
            )
            self._right_panel.expand()
            self._info.activate("alerts")
        elif action in ("enemy", "hostile"):
            pass  # symbol picker handles placement
        elif action in ("friendly",):
            pass  # symbol picker handles placement
        elif action == "medevac":
            self._open_medevac(lat, lon)
        elif action == "poi":
            self._place_poi_with_photo(lat, lon)
        elif action == "fire":
            self._open_call_for_fire(lat, lon)
        elif action == "report":
            self._right_panel.expand()
            self._info.activate("reports")

    def _open_call_for_fire(self, lat: float, lon: float):
        """Open the Call-for-Fire dialog with the target pre-filled (radial → FIRE)."""
        try:
            from front.utils.mgrs_util import to_mgrs

            mgrs = to_mgrs(lat, lon)
        except Exception:
            mgrs = f"{lat:.5f}, {lon:.5f}"

        dlg = FireMissionDialog(self._client, lat, lon, mgrs, parent=self)
        dlg.fire_mission_submitted.connect(self._on_fire_mission_submitted)
        dlg.show()
        dlg.raise_()
        self._fire_windows.append(dlg)

    def _on_fire_mission_submitted(self, fm: dict):
        """Render the just-submitted mission locally and confirm. Other clients
        receive it over the `fire-mission` WS channel."""
        try:
            self._map.add_fire_mission(fm)
        except Exception:
            pass
        self._firemissions_panel.upsert_mission({**fm, "callsign": self._callsign})
        self._toasts.show(
            "mission",
            "FIRE MISSION SENT",
            f"{fm.get('mission_type', '')} · {fm.get('ammunition', '')}",
        )

    def _open_medevac(self, lat: float, lon: float):
        """Place a MEDEVAC marker on the map and open the 9-liner form."""
        # Convert lat/lon to MGRS for Line 1 pre-fill
        try:
            from front.utils.mgrs_util import to_mgrs

            mgrs = to_mgrs(lat, lon)
        except Exception:
            mgrs = f"{lat:.5f}, {lon:.5f}"

        # Place a medical marker on the map immediately
        self._place_medevac_marker(lat, lon)

        # Open the 9-liner window
        win = MedevacWindow(self._client, lat, lon, mgrs, parent=self)
        win.report_submitted.connect(
            lambda _: (self._right_panel.expand(), self._info.activate("reports"))
        )
        win.show()
        win.raise_()
        self._medevac_windows.append(win)

    def _place_medevac_marker(self, lat: float, lon: float):
        """Place a red-cross MEDEVAC marker on the map at the given position."""
        sidc = MedevacWindow.MEDEVAC_SIDC
        obj = {
            "id": f"medevac_{lat:.5f}_{lon:.5f}",
            "type": "MARKER",
            "symbol_code": sidc,
            "latitude": lat,
            "longitude": lon,
            "affiliation": "FRIENDLY",
            "notes": "MEDEVAC",
        }
        self._map.add_tactical_object(obj)
        # Also persist to backend so it shows on the web map
        try:
            self._client.post_tactical_object(
                "MARKER",
                {"type": "point", "coords": [[lat, lon]]},
                notes="MEDEVAC",
                affiliation="FRIENDLY",
                symbol_code=sidc,
            )
        except Exception:
            pass

    def _on_file_dropped_on_map(self, file_path: str, lat: float, lon: float):
        self._place_poi_with_photo(lat, lon, preset_file=file_path)

    def _place_poi_with_photo(
        self, lat: float, lon: float, preset_file: str | None = None
    ):
        from PyQt6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QDialogButtonBox,
            QLineEdit,
            QFileDialog,
            QLabel,
            QPushButton,
        )
        from pathlib import Path

        dlg = QDialog(self)
        dlg.setWindowTitle("Place POI")
        dlg.setMinimumWidth(360)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Notes:"))
        notes_edit = QLineEdit()
        notes_edit.setPlaceholderText("Notes (optional)")
        layout.addWidget(notes_edit)

        layout.addWidget(QLabel("Photo / Video:"))
        file_path: list[str] = [preset_file] if preset_file else []

        fname = Path(preset_file).name if preset_file else "No file selected"
        file_label = QLabel(f"📎 {fname}" if preset_file else fname)
        file_label.setStyleSheet("color:#8b949e;font-size:9px;")

        def pick():
            path, _ = QFileDialog.getOpenFileName(
                dlg,
                "Attach Photo or Video",
                "",
                "Media (*.jpg *.jpeg *.png *.gif *.webp *.mp4 *.webm *.mov *.ogv);;All Files (*)",
            )
            if path:
                file_path.clear()
                file_path.append(path)
                file_label.setText(f"📎 {Path(path).name}")

        def clear_file():
            file_path.clear()
            file_label.setText("No file selected")

        btn_row = QHBoxLayout()
        pick_btn = QPushButton("📎 Browse…")
        pick_btn.clicked.connect(pick)
        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(28)
        clear_btn.clicked.connect(clear_file)
        btn_row.addWidget(pick_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(file_label, 1)
        layout.addLayout(btn_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        notes = notes_edit.text().strip() or "POI"
        photo_id: Optional[int] = None
        if file_path:
            try:
                photo_id = self._client.upload_media(file_path[0])
            except Exception as e:
                self.statusBar().showMessage(f"Upload failed: {e}", 4000)

        self._place_radial_marker(
            "POI", lat, lon, notes=notes, affiliation="NEUTRAL", photo_id=photo_id
        )

    def _place_radial_marker(
        self,
        obj_type: str,
        lat: float,
        lon: float,
        notes: str = "",
        affiliation: str = "UNKNOWN",
        photo_id: Optional[int] = None,
    ):
        from front.map.symbology import build as build_sidc

        aff_sidc = {"FRIENDLY": "F", "HOSTILE": "H", "NEUTRAL": "N"}.get(
            affiliation, "U"
        )
        type_func = {
            "HOSTILE": "infantry",
            "ENEMY": "infantry",
            "MARKER": "unit",
            "POI": "location",
            "DRONE": "drone",
        }.get(obj_type, "unit")
        dim = "A" if obj_type == "DRONE" else "G"
        sidc = build_sidc(aff_sidc, type_func, "none", dim=dim)
        try:
            self._client.post_tactical_object(
                obj_type,
                {"type": "point", "coords": [[lat, lon]]},
                notes=notes,
                affiliation=affiliation,
                symbol_code=sidc,
                photo_id=photo_id,
            )
        except Exception:
            pass
        self._map.add_tactical_object(
            {
                "id": f"radial_{notes}_{lat:.4f}_{lon:.4f}",
                "type": obj_type,
                "symbol_code": sidc,
                "latitude": lat,
                "longitude": lon,
                "affiliation": affiliation,
                "notes": notes,
            }
        )

    # ================================================================
    # TOOLBAR HANDLERS
    # ================================================================
    _last_pos_push = 0.0

    def _on_own_position(self, lat: float, lon: float, accuracy: float):
        """Push our own GPS fix to the backend so the web COP can see/zoom to us.

        navigator.geolocation.watchPosition can fire several times a second, so
        throttle to at most one POST per 5 s (the first fix always goes through,
        since _last_pos_push starts at 0). The HTTP call runs on a daemon thread
        to keep the UI responsive. No-op in read-only mode (no token)."""
        if not self._token:
            return
        import time
        import threading

        now = time.monotonic()
        if now - self._last_pos_push < 5.0:
            return
        self._last_pos_push = now

        def _work():
            try:
                self._client.push_position(lat, lon)
            except Exception as e:
                import sys

                print(f"[tracking] position push failed: {e}", file=sys.stderr)

        threading.Thread(target=_work, daemon=True, name="push-position").start()

    def _send_alert(
        self, alert_type: str, lat: Optional[float] = None, lon: Optional[float] = None
    ):
        try:
            self._client.send_alert(alert_type, lat=lat, lon=lon)
        except Exception as e:
            self.statusBar().showMessage(f"Alert failed: {e}", 3000)

    def _send_message_scoped(
        self,
        content: str,
        scope: str,
        receiver_id: object,
        mission_id: object,
        file_path: object = None,
    ):
        try:
            photo_id: Optional[int] = None
            if file_path:
                photo_id = self._client.upload_media(str(file_path))
            if scope == "DIRECT" and receiver_id is not None:
                self._client.send_message(
                    content, receiver_id=int(receiver_id), photo_id=photo_id
                )
            elif scope == "ROOM" and mission_id is not None:
                # `mission_id` slot carries the chatroom_id for ROOM scope.
                self._client.send_message_room(
                    content, chatroom_id=int(mission_id), photo_id=photo_id
                )
            else:
                self._client.send_message(content, photo_id=photo_id)
        except Exception as e:
            self.statusBar().showMessage(f"Message failed: {e}", 3000)

    # ================================================================
    # MBTILES CRUD
    # ================================================================

    def _open_mbtiles_manager(self):
        dlg = self._mbtiles_dlg
        for sig in (dlg.add_requested, dlg.remove_requested, dlg.toggle_requested):
            try:
                sig.disconnect()
            except Exception:
                pass
        dlg.add_requested.connect(self._mbtiles_add)
        dlg.remove_requested.connect(self._mbtiles_remove)
        dlg.toggle_requested.connect(self._mbtiles_toggle)
        dlg.set_client(self._client)
        dlg.refresh(self._mbtiles)
        dlg.show()
        dlg.raise_()

    def _mbtiles_add(self, path: str):
        try:
            mbt_id, tile_url, min_z, max_z, name = self._tile_server.load(path)
        except Exception as exc:
            self.statusBar().showMessage(f"MBTiles load failed: {exc}", 4000)
            return
        self._mbtiles[mbt_id] = {
            "path": path,
            "name": name,
            "min_zoom": min_z,
            "max_zoom": max_z,
            "visible": True,
        }
        self._map.add_mbtiles_layer(mbt_id, tile_url, min_z, max_z, name)
        self._save_mbtiles_settings()
        self._mbtiles_dlg.refresh(self._mbtiles)
        self.statusBar().showMessage(
            f"MBTiles loaded: {name}  (z{min_z}–{max_z})", 3000
        )

    def _mbtiles_remove(self, mbt_id: str):
        if mbt_id not in self._mbtiles:
            return
        name = self._mbtiles[mbt_id]["name"]
        self._tile_server.unload(mbt_id)
        self._map.remove_mbtiles_layer(mbt_id)
        del self._mbtiles[mbt_id]
        self._save_mbtiles_settings()
        self._mbtiles_dlg.refresh(self._mbtiles)
        self.statusBar().showMessage(f"MBTiles removed: {name}", 2000)

    def _mbtiles_toggle(self, mbt_id: str, visible: bool):
        if mbt_id not in self._mbtiles:
            return
        self._mbtiles[mbt_id]["visible"] = visible
        self._map.toggle_mbtiles_layer(mbt_id, visible)
        self._mbtiles_dlg.refresh(self._mbtiles)

    def _save_mbtiles_settings(self):
        s = QSettings("Arrow", "ArrowFront")
        s.setValue("mbtiles/paths", [v["path"] for v in self._mbtiles.values()])

    # Bundled offline base map shipped with the app (full-world MapQuest tiles).
    _DEFAULT_MBTILES_NAME = "mapquest_2014-02-11_084957.mbtiles"

    def _load_default_map(self):
        """Seed the bundled MapQuest MBTiles as the default map on first run.

        Gives the app a working offline base map out of the box without any
        online tiles. Seeded once via a QSettings flag, and only when the file
        exists — so if the user later removes it from the MBTiles manager, it is
        not silently re-added on the next launch.
        """
        from pathlib import Path

        s = QSettings("Arrow", "ArrowFront")
        if s.value("mbtiles/default_seeded", False, type=bool):
            return
        default_path = (
            Path(__file__).resolve().parent.parent / "map" / self._DEFAULT_MBTILES_NAME
        )
        if not default_path.exists():
            return
        path = str(default_path)
        # Don't double-load if the user already added this exact file.
        if not any(v["path"] == path for v in self._mbtiles.values()):
            try:
                self._mbtiles_add(path)
            except Exception:
                return  # leave unseeded so a transient failure can retry next run
        s.setValue("mbtiles/default_seeded", True)

    def _restore_mbtiles(self):
        """Reload previously loaded MBTiles files on startup."""
        s = QSettings("Arrow", "ArrowFront")
        paths = s.value("mbtiles/paths", [])
        if isinstance(paths, str):
            paths = [paths]
        for path in paths or []:
            try:
                self._mbtiles_add(path)
            except Exception:
                pass

    def _on_free_draw_saved(
        self,
        obj_type: str,
        geom_json: str,
        notes_json: str,
        active_overlay_id: int = 0,
    ):
        """Persist a free-draw stroke/text so web + other fronts see it via WS.

        "Draw on overlays": when exactly one overlay is active (the page passes
        its id), append the new object to that overlay so it travels with it.
        """
        try:
            geom = json.loads(geom_json)
            if not geom.get("coords"):
                return
            obj = self._save_drawn(
                obj_type,
                geom,
                notes=notes_json,
                affiliation="NEUTRAL",
                fallback_overlay_id=active_overlay_id,
            )
        except Exception as e:
            self._statusbar.showMessage(f"Free draw not saved: {e}", 3000)
            return
        # Local objects are already drawn by _save_drawn; for server objects we
        # render the canonical keyed object now (replaces the optimistic preview
        # via the FREEDRAW FIFO) rather than waiting for the WS echo. Overlay
        # membership was patched first, so the stroke isn't filtered out.
        if obj is not None and not obj.get("local"):
            try:
                self._map.add_tactical_object(obj)
            except Exception:
                pass

    def _attach_to_active_overlay(self, obj_id: int, active_overlay_id: int) -> None:
        """Add obj_id to overlay active_overlay_id (0 = skip)."""
        if not active_overlay_id or not self._can_edit_overlays():
            return
        ov = self._overlays.get(active_overlay_id)
        if ov is None:
            return
        ids = sorted({*ov.get("object_ids", []), obj_id})
        try:
            updated = self._client.patch_overlay(active_overlay_id, object_ids=ids)
            self._overlays[updated["id"]] = updated
            self._push_overlays()
        except Exception:
            pass

    def _on_tactical_object_action(self, action: str, obj_id: int):
        if action == "delete" and obj_id > 0:
            try:
                self._client.delete_tactical_object(obj_id)
            except Exception as e:
                self.statusBar().showMessage(f"Delete failed: {e}", 3000)

    def _on_delete_all_graphics(self):
        # Clear the local map immediately for responsiveness, then delete every
        # tactical object on the backend in a worker thread (each delete is a
        # blocking HTTP call; the server enforces per-object permissions, so
        # only objects the user may remove actually go — 403s are skipped).
        self._map.clear_all_graphics()
        # Also wipe locally-saved objects so they don't reappear on next launch.
        try:
            self._local_store.clear()
        except Exception:
            pass
        self.statusBar().showMessage("Deleting all graphics…", 3000)

        import threading

        def _work():
            try:
                objs = self._client.tactical_objects()
            except Exception:
                return
            for o in objs:
                oid = o.get("id")
                if oid is None:
                    continue
                try:
                    self._client.delete_tactical_object(oid)
                except Exception:
                    pass

        threading.Thread(target=_work, daemon=True, name="del-all-graphics").start()

    def _on_tactical_object_move(
        self, obj_id: int, lat: float, lon: float, geometry_json: str = ""
    ):
        if obj_id > 0:
            try:
                self._client.patch_tactical_object(
                    obj_id, lat, lon, geometry_json or None
                )
            except Exception as e:
                self.statusBar().showMessage(f"Move failed: {e}", 3000)

    # ================================================================
    # ROUTE PLANNING
    # ================================================================

    def _on_navigate_requested(self, route_id: str):
        route = self._routes_panel._routes.get(route_id)
        if not route:
            return
        self._map.start_navigation(route)
        self._right_panel.collapse()  # maximize map space while navigating

    def _on_nav_completed(self, route_id: str):
        name = self._routes_panel._routes.get(route_id, {}).get("name", "Route")
        self._toasts.show("info", "ROUTE COMPLETE", name.upper())

    def _on_route_draw_requested(self, route_id: str, color: str):
        self._pending_route_colors[route_id] = color
        self._map.start_route_drawing(route_id, color)
        self._right_panel.expand()
        self._info.activate("routes")

    def _on_route_drawn(self, route_id: str, wps_json: str):
        from PyQt6.QtWidgets import QDialog

        try:
            wps = json.loads(wps_json)
        except Exception:
            wps = []
        self._routes_panel.on_draw_cancelled_from_map()  # clear banner

        color = self._pending_route_colors.pop(route_id, "#3fb950")
        route = {
            "id": route_id,
            "name": "Route",
            "color": color,
            "speed_kmh": 30.0,
            "waypoints": wps,
            "visible": True,
        }
        dlg = RoutePropertiesDialog(route, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        route = dlg.get_result()
        route["visible"] = True
        self._routes_panel.add_route(route)
        self._map.add_route(route)
        self._save_routes()
        self._right_panel.expand()
        self._info.activate("routes")

    def _on_route_draw_cancelled_from_map(self, route_id: str):
        self._routes_panel.on_draw_cancelled_from_map()

    def _on_route_deleted(self, route_id: str):
        self._map.remove_route(route_id)
        self._save_routes()

    def _on_route_updated(self, route: dict):
        self._map.add_route(route)
        self._save_routes()

    def _on_route_add(self, route: dict):
        self._map.add_route(route)
        self._save_routes()

    def _save_routes(self):
        s = QSettings("Arrow", "ArrowFront")
        s.setValue("routes/v1", json.dumps(self._routes_panel.get_routes()))

    def _load_saved_routes(self):
        s = QSettings("Arrow", "ArrowFront")
        raw = s.value("routes/v1", None)
        if not raw:
            return
        try:
            routes = json.loads(raw)
        except Exception:
            return
        self._routes_panel.load_routes(routes)
        for r in routes:
            self._map.add_route(r)

    def _on_graphic_drawn(
        self,
        gtype: str,
        geojson_str: str,
        affiliation: str = "FRIENDLY",
        active_overlay_id: int = 0,
    ):
        """Persist a drawn tactical graphic to the backend (synced to web + android).

        Uses the SHARED canonical type vocabulary + separate affiliation field,
        and geometry {type:'line'|'polygon', coords:[[lat,lon],...]} — identical
        format to the web client, so all three render each other's graphics.
        """
        try:
            geom = json.loads(geojson_str)
            if not (geom.get("coords") or []):
                return
            # Server graphics render via the WS echo; local ones render in
            # _save_drawn — so nothing extra to draw here.
            self._save_drawn(
                gtype,
                geom,
                affiliation=affiliation or "FRIENDLY",
                fallback_overlay_id=active_overlay_id,
            )
        except Exception as e:
            self._statusbar.showMessage(f"Graphic not saved: {e}", 3000)

    # ================================================================
    # DRAW PANEL — symbol placement, layer add, local save mode
    # ================================================================
    def _on_place_symbol(self, affiliation: str):
        """Arm one-shot symbol placement: next map click opens the picker."""
        self._map.arm_symbol_placement(affiliation)
        self._statusbar.showMessage(
            f"Click the map to place a {affiliation.lower()} symbol…", 4000
        )

    # ---- Active draw target (layers) ------------------------------------
    def _target_is_local(self) -> bool:
        k = self._active_layer_key
        return k == "map:local" or k.startswith("local:")

    def _save_drawn(
        self,
        obj_type: str,
        geometry: dict,
        notes: str = "",
        affiliation: str = "UNKNOWN",
        symbol_code: str = "",
        echelon: str = "",
        photo_id: Optional[int] = None,
        fallback_overlay_id: int = 0,
    ) -> Optional[dict]:
        """Save one drawn element into the ACTIVE draw target.

        Returns the render-ready object (local: rendered already; server:
        caller decides). ``fallback_overlay_id`` is the in-map active overlay,
        honoured only for the default "map:server" target so the existing
        in-map "draw on overlays" workflow keeps working.
        """
        key = self._active_layer_key
        if key == "map:local" or key.startswith("local:"):
            layer_id = int(key.split(":", 1)[1]) if key.startswith("local:") else None
            obj = self._local_store.add(
                obj_type,
                geometry,
                notes=notes,
                affiliation=affiliation,
                symbol_code=symbol_code,
                echelon=echelon,
                layer_id=layer_id,
            )
            self._map.add_tactical_object(obj)
            if layer_id is not None:
                # Refresh the right panel so the new element joins the layer's
                # membership (and bump the left combo count).
                self._push_overlays()
            return obj
        # Server targets
        obj = self._client.post_tactical_object(
            obj_type,
            geometry,
            notes=notes,
            affiliation=affiliation,
            symbol_code=symbol_code,
            echelon=echelon,
            photo_id=photo_id,
        )
        overlay_id = (
            int(key.split(":", 1)[1])
            if key.startswith("overlay:")
            else fallback_overlay_id
        )
        if overlay_id:
            self._attach_to_active_overlay(obj["id"], overlay_id)
        return obj

    def _layer_entries(self) -> list[tuple[str, str]]:
        """Combined target list: map defaults + local layers + server overlays."""
        entries: list[tuple[str, str]] = [
            ("map:server", "📡 Map · Distribute"),
            ("map:local", "💾 Map · Local"),
        ]
        for layer in self._local_store.list_layers():
            entries.append(
                (f"local:{layer['id']}", f"💾 {layer['name']} ({layer['count']})")
            )
        for oid in sorted(self._overlays):
            ov = self._overlays[oid]
            n = len(ov.get("object_ids") or [])
            entries.append((f"overlay:{oid}", f"📡 {ov.get('name', 'overlay')} ({n})"))
        return entries

    def _refresh_layer_combo(self):
        entries = self._layer_entries()
        keys = {k for k, _ in entries}
        if self._active_layer_key not in keys:
            self._active_layer_key = "map:server"
        self._draw_panel.set_layers(entries, self._active_layer_key)
        # Keep the authoritative key in sync with what the combo actually shows.
        self._active_layer_key = self._draw_panel.current_layer_key()

    def _on_layer_target_changed(self, key: str):
        self._active_layer_key = key or "map:server"
        # Selecting a layer checks it in the right panel so its elements (and
        # whatever you draw next) stay visible under the overlay filter.
        self._activate_target_overlay()
        label = {
            "map:server": "Map · Distribute (server)",
            "map:local": "Map · Local (this device)",
        }.get(self._active_layer_key, "")
        if not label:
            kind = "local" if self._active_layer_key.startswith("local:") else "shared"
            label = f"active {kind} layer"
        self._statusbar.showMessage(f"Draw target: {label}", 3000)

    def _import_kml_file(self):
        """Upload a .kml/.kmz file as a new layer (BATTLE_CAPTAIN/ADMIN)."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Add KML / KMZ Layer",
            "",
            "KML/KMZ (*.kml *.kmz);;All Files (*)",
        )
        if not path:
            return
        try:
            layer = self._client.upload_kml(path)
        except Exception as e:
            msg = (
                "Permission denied (need BATTLE_CAPTAIN/ADMIN)."
                if "403" in str(e)
                else str(e)
            )
            QMessageBox.critical(self, "KML Upload Failed", msg)
            return
        try:
            self._map.add_kml_layer(layer)
        except Exception:
            pass
        self._toasts.show(
            "info", "LAYER ADDED", str(layer.get("name", "")).upper() or "KML"
        )

    def _load_local_objects(self):
        """Render every locally-saved element (offline-first) on the map."""
        try:
            for obj in self._local_store.all():
                self._map.add_tactical_object(obj)
        except Exception:
            pass
        self._refresh_layer_combo()

    # ---- Layer CRUD -----------------------------------------------------
    def _on_layer_create(self):
        """Create a new drawing layer (local or distributed) and make it active."""
        from PyQt6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "New Layer", "Layer name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        distributed = False
        if self._token:
            ans = QMessageBox.question(
                self,
                "Layer Type",
                f"Distribute “{name}” to the server (shared with all clients)?\n\n"
                "Yes — distributed (server overlay)\n"
                "No — local only (this device)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            distributed = ans == QMessageBox.StandardButton.Yes
        if distributed:
            try:
                ov = self._client.create_overlay(name, "", [])
            except Exception as e:
                QMessageBox.critical(self, "Create Layer", str(e))
                return
            self._overlays[ov["id"]] = ov
            self._active_layer_key = f"overlay:{ov['id']}"
        else:
            layer = self._local_store.create_layer(name)
            self._active_layer_key = f"local:{layer['id']}"
        # Show the new layer in the right panel and make it the active (checked)
        # target so drawing into it is visible immediately.
        self._push_overlays()
        self._activate_target_overlay()
        self._statusbar.showMessage(f"Active layer: {name}", 3000)

    def _on_layer_rename(self, key: str):
        from PyQt6.QtWidgets import QInputDialog

        if key.startswith("local:"):
            lid = int(key.split(":", 1)[1])
            cur = self._local_store.layer(lid).get("name", "")
            name, ok = QInputDialog.getText(self, "Rename Layer", "New name:", text=cur)
            if ok and name.strip():
                self._local_store.rename_layer(lid, name.strip())
                self._refresh_layer_combo()
        elif key.startswith("overlay:"):
            oid = int(key.split(":", 1)[1])
            cur = self._overlays.get(oid, {}).get("name", "")
            name, ok = QInputDialog.getText(self, "Rename Layer", "New name:", text=cur)
            if ok and name.strip():
                try:
                    ov = self._client.patch_overlay(oid, name=name.strip())
                except Exception as e:
                    QMessageBox.critical(self, "Rename Layer", str(e))
                    return
                self._overlays[ov["id"]] = ov
                self._push_overlays()
        else:
            self._statusbar.showMessage("The Map target cannot be renamed.", 3000)

    def _on_layer_delete(self, key: str):
        if key.startswith("local:"):
            lid = int(key.split(":", 1)[1])
            info = self._local_store.layer(lid)
            if not info:
                return
            ans = QMessageBox.question(
                self,
                "Delete Layer",
                f"Delete local layer “{info['name']}” and its "
                f"{info['count']} element(s)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            for o in self._local_store.objects_for_layer(lid):
                self._map.remove_tactical_object(o["id"])
            self._local_store.delete_layer(lid)
        elif key.startswith("overlay:"):
            oid = int(key.split(":", 1)[1])
            info = self._overlays.get(oid, {})
            ans = QMessageBox.question(
                self,
                "Delete Layer",
                f"Delete distributed layer “{info.get('name', '')}”?\n\n"
                "The overlay grouping is removed for all clients "
                "(the objects themselves remain).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            try:
                self._client.delete_overlay(oid)
            except Exception as e:
                QMessageBox.critical(self, "Delete Layer", str(e))
                return
            self._overlays.pop(oid, None)
        else:
            self._statusbar.showMessage("The Map target cannot be deleted.", 3000)
            return
        if self._active_layer_key == key:
            self._active_layer_key = "map:server"
        self._push_overlays()  # also refreshes the combo

    def _on_layer_distribute(self, key: str):
        """Push a LOCAL layer's elements to the server (into a new overlay)."""
        if not self._token:
            QMessageBox.information(self, "Distribute", "Not connected to a server.")
            return
        lid: Optional[int] = None
        layer_name: Optional[str] = None
        if key == "map:local":
            items = [o for o in self._local_store.all() if o.get("layer_id") is None]
        elif key.startswith("local:"):
            lid = int(key.split(":", 1)[1])
            items = self._local_store.objects_for_layer(lid)
            layer_name = self._local_store.layer(lid).get("name", "Layer")
        else:
            self._statusbar.showMessage("Only local layers can be distributed.", 3000)
            return
        if not items:
            self._toasts.show("info", "NOTHING TO DISTRIBUTE", "No local elements")
            return
        ans = QMessageBox.question(
            self,
            "Distribute Layer",
            f"Push {len(items)} element(s) to the server"
            + (f" as overlay “{layer_name}”" if layer_name else "")
            + "?\n\nThey will be broadcast to all connected clients.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        overlay_id: Optional[int] = None
        if layer_name:
            try:
                ov = self._client.create_overlay(layer_name, "", [])
                overlay_id = ov["id"]
                self._overlays[overlay_id] = ov
            except Exception:
                overlay_id = None
        new_ids: list[int] = []
        failed = 0
        for it in items:
            try:
                geom_str = it.get("geometry") or ""
                geom = (
                    json.loads(geom_str)
                    if geom_str
                    else {
                        "type": "point",
                        "coords": [[it["latitude"], it["longitude"]]],
                    }
                )
                obj = self._client.post_tactical_object(
                    it["type"],
                    geom,
                    notes=it.get("notes", ""),
                    affiliation=it.get("affiliation", "UNKNOWN"),
                    symbol_code=it.get("symbol_code", ""),
                    echelon=it.get("echelon", ""),
                )
            except Exception:
                failed += 1
                continue
            self._map.remove_tactical_object(it["id"])
            self._local_store.delete(it["local_id"])
            self._map.add_tactical_object(obj)
            new_ids.append(obj["id"])
        if overlay_id and new_ids:
            try:
                ov = self._client.patch_overlay(overlay_id, object_ids=new_ids)
                self._overlays[ov["id"]] = ov
            except Exception:
                pass
        # Drop the now-empty local layer only if everything was distributed.
        if lid is not None and failed == 0:
            self._local_store.delete_layer(lid)
        self._active_layer_key = f"overlay:{overlay_id}" if overlay_id else "map:server"
        self._push_overlays()
        # Keep the freshly-distributed overlay visible (members hide otherwise).
        self._activate_target_overlay()
        if failed:
            self._statusbar.showMessage(
                f"Distributed {len(items) - failed}/{len(items)} — {failed} failed",
                6000,
            )
        else:
            self._toasts.show(
                "info", "DISTRIBUTED", f"{len(items)} element(s) sent to server"
            )

    def _export_layer_target(self, key: str):
        """Export the selected layer to a JSON file (server overlay or local)."""
        if key.startswith("overlay:"):
            self._on_layer_export("OVERLAY", int(key.split(":", 1)[1]))
            return
        if key.startswith("local:") or key == "map:local":
            if key.startswith("local:"):
                lid = int(key.split(":", 1)[1])
                name = self._local_store.layer(lid).get("name", "layer")
                objs = self._local_store.objects_for_layer(lid)
            else:
                name = "local"
                objs = [o for o in self._local_store.all() if o.get("layer_id") is None]
            if not objs:
                self._statusbar.showMessage("Layer has no elements to export.", 3000)
                return
            envelope = {
                "kind": "LOCAL_LAYER",
                "name": name,
                "objects": [
                    {
                        "type": o["type"],
                        "geometry": o.get("geometry", ""),
                        "notes": o.get("notes", ""),
                        "affiliation": o.get("affiliation", "UNKNOWN"),
                        "symbol_code": o.get("symbol_code", ""),
                        "echelon": o.get("echelon", ""),
                    }
                    for o in objs
                ],
            }
            path, _ = QFileDialog.getSaveFileName(
                self, "Export layer", f"{name}.local.json", "JSON (*.json)"
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(envelope, f, indent=2)
                self._statusbar.showMessage(f"Exported to {path}", 4000)
            except OSError as e:
                self._statusbar.showMessage(f"Could not write file: {e}", 4000)
            return
        self._statusbar.showMessage("The Map target cannot be exported.", 3000)

    def _focus_operator(self, operator_id: int):
        try:
            for op in self._client.live_operators():
                oid = op.get("operator_id") or op.get("id")
                if oid == operator_id and op.get("latitude") and op.get("longitude"):
                    self._map.center_on(op["latitude"], op["longitude"], zoom=16)
                    return
        except Exception:
            pass

    # ================================================================
    # SCREENSHOT
    # ================================================================
    def _take_screenshot(self):
        import datetime
        from PyQt6.QtWidgets import QFileDialog

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"arrow_map_{ts}.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Map Screenshot",
            default_name,
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg)",
        )
        if not path:
            return
        pixmap = self._map.grab()
        if pixmap.save(path):
            self._toasts.show("info", "SCREENSHOT SAVED", path.split("/")[-1])
            self.statusBar().showMessage(f"Screenshot saved: {path}", 5000)
        else:
            self.statusBar().showMessage("Screenshot failed to save", 4000)

    # ================================================================
    # HELPERS
    # ================================================================
    def _push_track(self, data: dict):
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
        try:
            self._location.stop()
        except Exception:
            pass
        event.accept()
