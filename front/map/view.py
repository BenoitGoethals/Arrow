"""MapView — QWebEngineView hosting the Leaflet tactical COP."""
from __future__ import annotations
import json
import sys
from pathlib import Path

from PyQt6.QtCore import QUrl, QFile, QIODevice, Qt, QEvent, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineScript, QWebEnginePage, QWebEngineSettings
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

        # Suppress Qt's default right-click context menu so JS radial menu fires
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setAcceptDrops(True)

        self._page = _DebugPage(self)
        self.setPage(self._page)

        # Allow file:// pages to fetch remote tile URLs (OSM, etc.)
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

        # Log load result
        self._page.loadFinished.connect(self._on_load_finished)

        # Load the map HTML
        map_html = Path(__file__).parent / "html" / "map.html"
        print(f"[MapView] Loading: {map_html.resolve()}", file=sys.stderr)
        self.load(QUrl.fromLocalFile(str(map_html.resolve())))

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

    def load_mbtiles(self, tile_url: str, min_zoom: int = 0, max_zoom: int = 18):
        self._js(f"loadMBTiles({json.dumps(tile_url)}, {min_zoom}, {max_zoom})")

    def update_cot_track(self, track: dict):
        self._js(f"updateCotTrack({json.dumps(track)})")

    def add_tactical_object(self, obj: dict):
        self._js(f"addTacticalObject({json.dumps(obj)})")

    def remove_tactical_object(self, obj_id: str):
        self._js(f"removeTacticalObject({json.dumps(obj_id)})")

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
