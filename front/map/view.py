"""MapView — QWebEngineView hosting the Leaflet tactical COP."""
from __future__ import annotations
import base64
import json
import sys
from pathlib import Path

from PyQt6.QtCore import QUrl, QFile, QIODevice, Qt, QEvent, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineScript, QWebEnginePage, QWebEngineSettings, QWebEnginePermission,
    QWebEngineProfile,
)
from PyQt6.QtWebChannel import QWebChannel

from front.map.bridge import MapBridge

_MEDIA_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.webm', '.mov', '.ogv')


def _is_media_file(path: str) -> bool:
    return path.lower().endswith(_MEDIA_EXTS)


class _DebugPage(QWebEnginePage):
    """Forwards JS console messages to Python stdout for debugging."""

    def javaScriptConsoleMessage(self, level, message, line, source):
        tag = {
            QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel:    "JS",
            QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "JS WARN",
            QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:   "JS ERR",
        }.get(level, "JS")
        print(f"[{tag}] {source}:{line}  {message}", file=sys.stderr)


class MapView(QWebEngineView):
    file_dropped = pyqtSignal(str, float, float)  # file_path, lat, lon

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _: None)
        self.setAcceptDrops(True)

        # Flush any stale map.html / lib asset already in WebEngine's persistent
        # disk cache so local edits are picked up. (Online map tiles still cache
        # normally — the local server sends Cache-Control: no-store itself, so
        # only its own responses are excluded going forward.)
        QWebEngineProfile.defaultProfile().clearHttpCache()

        self._page = _DebugPage(self)
        self.setPage(self._page)

        # DIAGNOSTIC: if the map blacks out because the WebEngine render/GPU
        # process dies, this prints exactly that (no front-end fix can help a
        # crashed renderer). Remove once the black-out cause is confirmed.
        self._page.renderProcessTerminated.connect(
            lambda status, code: print(
                f"[MapView] *** RENDER PROCESS TERMINATED *** status={status} exitCode={code}",
                file=sys.stderr,
            )
        )

        # Grant geolocation permission so navigator.geolocation works
        self._page.permissionRequested.connect(self._on_permission_requested)

        # Match page background to the map CSS background — prevents white/black
        # flash when the page renders before tiles arrive
        self._page.setBackgroundColor(QColor("#0d1117"))

        s = self._page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        self.bridge = MapBridge(self)

        # Wire QWebChannel
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("bridge", self.bridge)
        self._page.setWebChannel(self._channel)

        # Inject qwebchannel.js before page scripts run
        self._inject_qwebchannel()

        # Log load result + start repaint guard
        self._page.loadFinished.connect(self._on_load_finished)

        # Periodic safety-net: keep the Qt compositor from showing a stale
        # WebEngine frame.  self.update() is deliberately the only call here —
        # no JS — so it never interferes with tile loading.  Reactive JS repaints
        # (map.invalidateSize) are fired once by notify_menu_closed / contextMenuEvent.
        self._repaint_guard = QTimer(self)
        self._repaint_guard.setInterval(250)
        self._repaint_guard.timeout.connect(self.update)
        self._repaint_guard.start()

        # Load the map via the local HTTP server (http://127.0.0.1:PORT/map)
        # instead of file:// — avoids the Qt6/macOS Metal compositor black-screen
        # bug that only manifests on the file:// compositor code-path.
        # map_url is set by MapView.set_map_server_port() once the server starts.
        self._map_server_port: int = 0

        # Auth + photo cache for geo-pinned tactical-object images.
        self._server_url: str = ""
        self._token: str = ""
        self._photo_cache: dict[str, str] = {}
        self._img_threads: list = []

    def set_map_server_port(self, port: int):
        """Call once the MBTilesServer is running before showing the window."""
        self._map_server_port = port
        url = f"http://127.0.0.1:{port}/map"
        print(f"[MapView] Loading: {url}", file=sys.stderr)
        self.load(QUrl(url))

    def _force_repaint(self):
        """Nudge the Qt widget to repaint the WebEngine surface.

        IMPORTANT: this used to toggle document.body opacity (1 → 0.9999 → back)
        to "force a fresh frame". That was the cause of the permanent map
        black-out on macOS: setting opacity < 1 on <body> promotes the WHOLE
        page (including the #map GPU layer) into a single new compositing layer,
        and on the Qt6/macOS Metal backend that loses the GPU surface for good.
        We now only ask Qt to repaint the widget — no DOM layer promotion.
        """
        self.update()

    def notify_menu_closed(self):
        """Call when any native QMenu that appeared over this view has closed.

        Uses a longer delay than contextMenuEvent because macOS NSMenu has a
        fade-out animation (~50ms) that keeps the native surface alive; firing
        before it fully closes would repaint into the wrong compositor state.
        """
        QTimer.singleShot(80,  self._force_repaint)
        QTimer.singleShot(300, self._force_repaint)

    def focusInEvent(self, event):
        """Repaint when focus returns — covers the QMenu-close focus transition."""
        super().focusInEvent(event)
        QTimer.singleShot(50,  self._force_repaint)
        QTimer.singleShot(200, self._force_repaint)

    def contextMenuEvent(self, event):
        # Swallow the Qt context-menu event so no native menu appears over the
        # WebEngine view (a native overlay would drop the Metal framebuffer).
        print("[MapView] contextMenuEvent (right-click) fired", file=sys.stderr)  # DIAGNOSTIC
        event.accept()
        self._force_repaint()
        QTimer.singleShot(40,  self._force_repaint)
        QTimer.singleShot(200, self._force_repaint)

    def _on_permission_requested(self, permission):
        try:
            if permission.permissionType() == QWebEnginePermission.PermissionType.Geolocation:
                permission.grant()
        except Exception:
            pass

    def _on_load_finished(self, ok: bool):
        if ok:
            print("[MapView] Page loaded OK", file=sys.stderr)
            self._page.runJavaScript(
                "typeof L !== 'undefined' ? 'Leaflet OK' : 'Leaflet MISSING'",
                lambda r: print(f"[MapView] {r}", file=sys.stderr)
            )
            # Install drag-drop event filter on the viewport child widget
            vp = self.focusProxy() or self.viewport()
            if vp:
                vp.setAcceptDrops(True)
                vp.installEventFilter(self)
        else:
            print("[MapView] ERROR: Page failed to load", file=sys.stderr)

    # ---- qwebchannel.js injection ----------------------------------------

    def _inject_qwebchannel(self):
        source = self._find_qwebchannel_js()
        if not source:
            print("[MapView] WARNING: qwebchannel.js not found — bridge disabled", file=sys.stderr)
            return
        print(f"[MapView] qwebchannel.js injected ({len(source)} bytes)", file=sys.stderr)
        script = QWebEngineScript()
        script.setName("qwebchannel.js")
        script.setSourceCode(source)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        self._page.scripts().insert(script)

    @staticmethod
    def _find_qwebchannel_js() -> str:
        # 1. Qt resource system
        f = QFile(":/qtwebchannel/qwebchannel.js")
        if f.open(QIODevice.OpenModeFlag.ReadOnly):
            content = bytes(f.readAll()).decode("utf-8")
            f.close()
            if content.strip():
                return content

        # 2. Local bundled copy
        local = Path(__file__).parent / "html" / "qwebchannel.js"
        if local.exists():
            return local.read_text(encoding="utf-8")

        # 3. PyQt6 installation path
        try:
            import PyQt6
            candidate = (
                Path(PyQt6.__file__).parent
                / "Qt6" / "resources" / "qtwebchannel" / "qwebchannel.js"
            )
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        except Exception:
            pass

        return ""

    # ---- Python → JavaScript helpers ------------------------------------

    def _js(self, code: str):
        self._page.runJavaScript(code)

    def eval_js(self, code: str, callback):
        """Run JS and deliver the result to `callback` (used for readiness probes)."""
        self._page.runJavaScript(code, callback)

    def update_track(self, track: dict):
        self._js(f"updateTrack({json.dumps(track)})")

    def remove_track(self, track_id: str):
        self._js(f"removeTrack({json.dumps(track_id)})")

    def add_graphic(self, graphic: dict):
        self._js(f"addGraphic({json.dumps(graphic)})")

    def remove_graphic(self, graphic_id: str):
        self._js(f"removeGraphic({json.dumps(graphic_id)})")

    def add_alert_marker(self, alert: dict):
        self._js(f"addAlertMarker({json.dumps(alert)})")

    def set_draw_mode(self, mode: str):
        self._js(f"setDrawMode({json.dumps(mode)})")

    def set_base_layer(self, name: str):
        self._js(f"setBaseLayer({json.dumps(name)})")

    def toggle_layer(self, name: str, visible: bool):
        self._js(f"toggleLayer({json.dumps(name)}, {json.dumps(visible)})")

    def fit_tracks(self):
        self._js("fitTracks()")

    def center_on(self, lat: float, lon: float, zoom: int = 14):
        self._js(f"centerOn({lat}, {lon}, {zoom})")

    def add_mbtiles_layer(self, mbt_id: str, tile_url: str,
                          min_zoom: int = 0, max_zoom: int = 18, name: str = ""):
        self._js(
            f"addMBTilesLayer({json.dumps(mbt_id)}, {json.dumps(tile_url)}, "
            f"{min_zoom}, {max_zoom}, {json.dumps(name)})"
        )

    def remove_mbtiles_layer(self, mbt_id: str):
        self._js(f"removeMBTilesLayer({json.dumps(mbt_id)})")

    def toggle_mbtiles_layer(self, mbt_id: str, visible: bool):
        self._js(f"toggleMBTilesLayer({json.dumps(mbt_id)}, {json.dumps(visible)})")

    def update_cot_track(self, track: dict):
        self._js(f"updateCotTrack({json.dumps(track)})")

    def set_auth(self, server_url: str, token: str):
        """Provide backend URL + JWT so the map can fetch auth-gated photos."""
        self._server_url = (server_url or "").rstrip("/")
        self._token = token or ""

    def add_tactical_object(self, obj: dict):
        self._js(f"addTacticalObject({json.dumps(obj)})")
        # Geo-pinned photo: fetch with Bearer auth, then inject the data-URI.
        pid = obj.get("photo_id")
        if pid and self._server_url and self._token:
            self._fetch_obj_photo(obj.get("id"), pid)

    def _fetch_obj_photo(self, obj_id, photo_id):
        from front.panels.messages.panel import _ImageFetchThread
        url = f"{self._server_url}/photos/{photo_id}"
        cached = self._photo_cache.get(url)
        if cached:
            self._js(f"setObjPhoto({json.dumps(obj_id)}, {json.dumps(cached)})")
            return
        if url in self._photo_cache:   # in-flight (marked with "")
            return
        self._photo_cache[url] = ""
        t = _ImageFetchThread(url, self._token)
        t.loaded.connect(lambda u, data, oid=obj_id: self._on_obj_photo(oid, u, data))
        t.start()
        self._img_threads.append(t)

    def _on_obj_photo(self, obj_id, url: str, data: bytes):
        if not data:
            return
        if data[:4] == b"\x89PNG":
            mime = "image/png"
        elif data[:3] == b"GIF":
            mime = "image/gif"
        elif b"WEBP" in data[:12]:
            mime = "image/webp"
        else:
            mime = "image/jpeg"
        uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        self._photo_cache[url] = uri
        self._js(f"setObjPhoto({json.dumps(obj_id)}, {json.dumps(uri)})")

    def remove_tactical_object(self, obj_id: str):
        self._js(f"removeTacticalObject({json.dumps(obj_id)})")

    def update_vehicle(self, vehicle: dict):
        self._js(f"updateVehicle({json.dumps(vehicle)})")

    def remove_vehicle(self, vehicle_id: int):
        self._js(f"removeVehicle({json.dumps(vehicle_id)})")

    def add_fire_mission(self, fm: dict):
        self._js(f"addFireMission({json.dumps(fm)})")

    def add_kml_layer(self, kml: dict):
        self._js(f"addKmlLayer({json.dumps(kml)})")

    def remove_kml_layer(self, layer_id: str):
        self._js(f"removeKmlLayer({json.dumps(layer_id)})")

    def add_cbrn_zone(self, report: dict):
        self._js(f"addCbrnZone({json.dumps(report)})")

    def open_symbol_picker(self, lat: float, lon: float, affiliation: str = "FRIENDLY"):
        self._js(f"openSymbolPicker({lat}, {lon}, {json.dumps(affiliation)})")

    def set_gps_config(self, enabled: bool, high_accuracy: bool, max_age_ms: int,
                       center_on_fix: bool, show_accuracy: bool):
        self._js(
            f"setGPSConfig({json.dumps(enabled)}, {json.dumps(high_accuracy)}, "
            f"{int(max_age_ms)}, {json.dumps(center_on_fix)}, {json.dumps(show_accuracy)})"
        )

    def set_own_position_native(self, lat: float, lon: float, accuracy: float,
                                heading: float, source: str):
        """Push a fix obtained from native OS location services (macOS Core
        Location) into the own-position HUD, bypassing the in-page geolocation
        watcher that does not resolve under QtWebEngine on macOS."""
        self._js(
            f"setOwnPositionNative({json.dumps(float(lat))}, {json.dumps(float(lon))}, "
            f"{json.dumps(float(accuracy))}, {json.dumps(float(heading))}, "
            f"{json.dumps(source)})"
        )

    def set_own_position_status(self, text: str):
        """Update the own-position HUD label when there is no usable fix."""
        self._js(f"setOwnPositionStatus({json.dumps(text)})")

    def set_weather_layer(self, layer_name: str, visible: bool):
        self._js(f"setWeatherLayer({json.dumps(layer_name)}, {json.dumps(visible)})")

    def fetch_weather(self):
        self._js("fetchWeatherAtCenter()")

    def set_draw_graphic(self, graphic_type: str, affiliation: str):
        self._js(f"setDrawGraphic({json.dumps(graphic_type)}, {json.dumps(affiliation)})")

    def set_free_draw(self, tool: str, color: str, thickness: int):
        self._js(f"setFreeDraw({json.dumps(tool)}, {json.dumps(color)}, {int(thickness)})")

    def free_draw_undo(self):
        self._js("undoFreeDraw()")

    def free_draw_clear(self):
        self._js("clearFreeDrawLayer()")

    # ---- Route planning -------------------------------------------------

    def start_route_drawing(self, route_id: str, color: str):
        self._js(f"startRouteDrawing({json.dumps(route_id)}, {json.dumps(color)})")

    def cancel_route_drawing(self):
        self._js("cancelRouteDrawing()")

    def add_route(self, route: dict):
        self._js(f"addRoute({json.dumps(route)})")

    def remove_route(self, route_id: str):
        self._js(f"removeRoute({json.dumps(route_id)})")

    def set_route_visible(self, route_id: str, visible: bool):
        self._js(f"setRouteVisible({json.dumps(route_id)}, {json.dumps(visible)})")

    def center_on_route(self, route_id: str):
        self._js(f"centerOnRoute({json.dumps(route_id)})")

    # ---- Navigation -------------------------------------------------

    def start_navigation(self, route: dict):
        self._js(f"startNavigation({json.dumps(route)})")

    def stop_navigation(self):
        self._js("stopNavigation()")

    def pause_navigation(self):
        self._js("pauseNavigation()")

    def resume_navigation(self):
        self._js("resumeNavigation()")

    def nav_go_home(self):
        self._js("_navGoHome()")

    # ---- Drag-and-drop (media files → map) --------------------------------

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.DragEnter:
            mime = event.mimeData()
            if mime.hasUrls() and any(_is_media_file(u.toLocalFile()) for u in mime.urls()):
                event.acceptProposedAction()
                return True
        elif t == QEvent.Type.DragMove:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
        elif t == QEvent.Type.Drop:
            mime = event.mimeData()
            if mime.hasUrls():
                files = [u.toLocalFile() for u in mime.urls() if _is_media_file(u.toLocalFile())]
                if files:
                    event.acceptProposedAction()
                    pos = event.position().toPoint()
                    x, y = pos.x(), pos.y()
                    fp = files[0]
                    self._page.runJavaScript(
                        f"(function(){{try{{var ll=map.containerPointToLatLng([{x},{y}]);"
                        f"return [ll.lat,ll.lng];}}catch(e){{return null;}}}})()",
                        lambda r, p=fp: self._emit_drop(r, p),
                    )
                    return True
        return super().eventFilter(obj, event)

    def _emit_drop(self, latlng, file_path: str):
        if latlng and isinstance(latlng, list) and len(latlng) == 2:
            self.file_dropped.emit(file_path, float(latlng[0]), float(latlng[1]))
