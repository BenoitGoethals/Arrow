"""Map process — runs in its own OS process, hosting a pywebview window that
loads the same front/map/html/map.html (Leaflet + milsymbol) used by the
PyQt6 front.

Why a separate process: Kivy and pywebview each require exclusive main-thread
ownership of their native window/event loop and cannot share one process
(verified empirically on macOS — Kivy's window crashes if created off the
main thread; pywebview raises `WebViewException('pywebview must be run on a
main thread.')` outright). So the Kivy shell (front_kivy/app) spawns this
module as a `multiprocessing.Process` and talks to it purely over two
`multiprocessing.Queue`s:

  cmd_queue  (shell -> this process): {"action": "eval_js"|"move"|"resize", ...}
  evt_queue  (this process -> shell): {"event": <bridge slot name>, ...}

JS <-> Python bridge: the original PyQt6 front wires `front/map/bridge.py`
(MapBridge, a QObject exposing pyqtSlots) into map.html through QWebChannel.
pywebview has no QWebChannel; instead `Api` below is exposed as
`window.pywebview.api` via `js_api=`, and `_BRIDGE_SHIM_JS` defines a
script-scope `bridge` object (map.html declares `let bridge=null` at the top
of its single classic <script> block, so any later classic <script> in the
same document can still assign to it) whose methods match every
`bridge.onXxx(...)` call site in map.html one-for-one, each forwarding to
`window.pywebview.api.onXxx(...)`. map.html itself is unmodified.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Mirrors every `bridge.onXxx(...)` call site in front/map/html/map.html and
# every @pyqtSlot in front/map/bridge.py — kept 1:1 so future panel ports can
# wire these events without touching this shim again.
_BRIDGE_SHIM_JS = """
(function(){
  function fwd(name){
    return function(){
      var args = Array.prototype.slice.call(arguments);
      window.pywebview.api[name].apply(window.pywebview.api, args);
    };
  }
  bridge = {
    onReady: fwd('onReady'),
    onCoordsChanged: fwd('onCoordsChanged'),
    onOwnPosition: fwd('onOwnPosition'),
    onTrackClicked: fwd('onTrackClicked'),
    onMapClicked: fwd('onMapClicked'),
    onGraphicDrawn: fwd('onGraphicDrawn'),
    onMeasureComplete: fwd('onMeasureComplete'),
    onRadialAction: fwd('onRadialAction'),
    onSymbolSelected: fwd('onSymbolSelected'),
    onFreeDrawSaved: fwd('onFreeDrawSaved'),
    onOverlayCreate: fwd('onOverlayCreate'),
    onOverlayPatch: fwd('onOverlayPatch'),
    onOverlayDelete: fwd('onOverlayDelete'),
    onLayerExport: fwd('onLayerExport'),
    onLayerImport: fwd('onLayerImport'),
    onTacticalObjectAction: fwd('onTacticalObjectAction'),
    onTacticalObjectMove: fwd('onTacticalObjectMove'),
    onRouteDrawn: fwd('onRouteDrawn'),
    onRouteDrawCancelled: fwd('onRouteDrawCancelled'),
    onNavWaypointReached: fwd('onNavWaypointReached'),
    onNavCompleted: fwd('onNavCompleted'),
    onNavStopped: fwd('onNavStopped')
  };
  bridge.onReady();
  console.log('[ArrowFrontKivy] Bridge shim ready');
})();
"""


class Api:
    """Exposed to JS as `window.pywebview.api` — one method per bridge slot.

    Each method just forwards the call to the shell process via evt_queue;
    matches the (event_name, *args) shape front_kivy/map/view.py expects.
    """

    def __init__(self, evt_queue):
        self._evt_queue = evt_queue

    def _emit(self, event: str, **data):
        self._evt_queue.put({"event": event, **data})

    def onReady(self):
        self._emit("map_ready")

    def onCoordsChanged(self, lat, lon, mgrs):
        self._emit("coords_changed", lat=lat, lon=lon, mgrs=mgrs)

    def onOwnPosition(self, lat, lon, accuracy):
        self._emit("own_position", lat=lat, lon=lon, accuracy=accuracy)

    def onTrackClicked(self, track_id):
        self._emit("track_clicked", track_id=track_id)

    def onMapClicked(self, lat, lon):
        self._emit("map_clicked", lat=lat, lon=lon)

    def onGraphicDrawn(self, graphic_type, geojson, affiliation, active_overlay_id=0):
        self._emit(
            "graphic_drawn",
            graphic_type=graphic_type,
            geojson=geojson,
            affiliation=affiliation,
            active_overlay_id=active_overlay_id,
        )

    def onMeasureComplete(self, distance_str, bearing_str):
        self._emit("measure_done", distance=distance_str, bearing=bearing_str)

    def onRadialAction(self, action, lat, lon):
        self._emit("radial_action", action=action, lat=lat, lon=lon)

    def onSymbolSelected(self, sidc, designation, lat, lon, active_overlay_id=0):
        self._emit(
            "symbol_selected",
            sidc=sidc,
            designation=designation,
            lat=lat,
            lon=lon,
            active_overlay_id=active_overlay_id,
        )

    def onFreeDrawSaved(self, obj_type, geom_json, notes_json, active_overlay_id=0):
        self._emit(
            "free_draw_saved",
            obj_type=obj_type,
            geom_json=geom_json,
            notes_json=notes_json,
            active_overlay_id=active_overlay_id,
        )

    def onOverlayCreate(self, json_str):
        self._emit("overlay_create_requested", json_str=json_str)

    def onOverlayPatch(self, overlay_id, json_str):
        self._emit("overlay_patch_requested", overlay_id=overlay_id, json_str=json_str)

    def onOverlayDelete(self, overlay_id):
        self._emit("overlay_delete_requested", overlay_id=overlay_id)

    def onLayerExport(self, kind, source_id):
        self._emit("layer_export_requested", kind=kind, source_id=source_id)

    def onLayerImport(self):
        self._emit("layer_import_requested")

    def onTacticalObjectAction(self, action, obj_id):
        self._emit("tactical_object_action", action=action, obj_id=obj_id)

    def onTacticalObjectMove(self, obj_id, lat, lon, geometry_json=""):
        self._emit(
            "tactical_object_move",
            obj_id=obj_id,
            lat=lat,
            lon=lon,
            geometry_json=geometry_json,
        )

    def onRouteDrawn(self, route_id, waypoints_json):
        self._emit("route_drawn", route_id=route_id, waypoints_json=waypoints_json)

    def onRouteDrawCancelled(self, route_id):
        self._emit("route_draw_cancelled", route_id=route_id)

    def onNavWaypointReached(self, route_id, wp_idx):
        self._emit("nav_waypoint_reached", route_id=route_id, wp_idx=wp_idx)

    def onNavCompleted(self, route_id):
        self._emit("nav_completed", route_id=route_id)

    def onNavStopped(self):
        self._emit("nav_stopped")


def _command_pump(window, cmd_queue, evt_queue):
    """Background thread inside the map process (not the main thread) —
    pywebview's documented pattern: `webview.start(func)` runs `func` in a
    worker thread while the GUI loop occupies the main thread, and
    `window.evaluate_js()` from that worker thread is supported."""
    while True:
        cmd = cmd_queue.get()
        if cmd is None:
            window.destroy()
            return
        action = cmd.get("action")
        try:
            if action == "eval_js":
                window.evaluate_js(cmd["code"])
            elif action == "move":
                window.move(cmd["x"], cmd["y"])
            elif action == "resize":
                window.resize(cmd["width"], cmd["height"])
        except Exception as exc:
            log.warning("map process command %r failed: %s", action, exc)


def run_map_process(cmd_queue, evt_queue, x: int, y: int, width: int, height: int):
    """Entry point run inside the child process via multiprocessing.Process."""
    import webview

    from front.map.setup_libs import ensure_libs
    from front.map.tile_server import MBTilesServer

    ensure_libs()
    tile_server = MBTilesServer()
    port = tile_server.start()

    api = Api(evt_queue)
    window = webview.create_window(
        "arrow-map",
        url=f"http://127.0.0.1:{port}/map",
        js_api=api,
        x=x,
        y=y,
        width=width,
        height=height,
        frameless=True,
    )

    def _on_loaded():
        window.evaluate_js(_BRIDGE_SHIM_JS)

    window.events.loaded += _on_loaded

    webview.start(_command_pump, (window, cmd_queue, evt_queue), debug=False)
    tile_server.stop()
