"""Main-process facade for the map — owns the child map process and the two
IPC queues, and re-exposes the same call surface as front/map/view.py's
MapView, translated from `runJavaScript` calls into `cmd_queue` messages.

Bridge events (map.html -> Python) arrive on `evt_queue`, are drained on a
background thread, and are re-dispatched on Kivy's Clock as EventDispatcher
events — the same marshaling pattern used for the WS listener
(front_kivy/client/ws_listener.py), replacing the pyqtSignal cross-thread
delivery the PyQt6 front relies on.
"""

from __future__ import annotations

import json
import multiprocessing
import threading

from kivy.clock import Clock
from kivy.event import EventDispatcher

from front_kivy.map.map_process import run_map_process

# One event per bridge slot in front/map/bridge.py / front/map/html/map.html.
_EVENTS = [
    "on_map_ready",
    "on_coords_changed",
    "on_own_position",
    "on_track_clicked",
    "on_map_clicked",
    "on_graphic_drawn",
    "on_measure_done",
    "on_radial_action",
    "on_symbol_selected",
    "on_free_draw_saved",
    "on_overlay_create_requested",
    "on_overlay_patch_requested",
    "on_overlay_delete_requested",
    "on_layer_export_requested",
    "on_layer_import_requested",
    "on_tactical_object_action",
    "on_tactical_object_move",
    "on_route_drawn",
    "on_route_draw_cancelled",
    "on_nav_waypoint_reached",
    "on_nav_completed",
    "on_nav_stopped",
]

# evt_queue event name -> EventDispatcher event name
_EVENT_NAME_MAP = {
    "map_ready": "on_map_ready",
    "coords_changed": "on_coords_changed",
    "own_position": "on_own_position",
    "track_clicked": "on_track_clicked",
    "map_clicked": "on_map_clicked",
    "graphic_drawn": "on_graphic_drawn",
    "measure_done": "on_measure_done",
    "radial_action": "on_radial_action",
    "symbol_selected": "on_symbol_selected",
    "free_draw_saved": "on_free_draw_saved",
    "overlay_create_requested": "on_overlay_create_requested",
    "overlay_patch_requested": "on_overlay_patch_requested",
    "overlay_delete_requested": "on_overlay_delete_requested",
    "layer_export_requested": "on_layer_export_requested",
    "layer_import_requested": "on_layer_import_requested",
    "tactical_object_action": "on_tactical_object_action",
    "tactical_object_move": "on_tactical_object_move",
    "route_drawn": "on_route_drawn",
    "route_draw_cancelled": "on_route_draw_cancelled",
    "nav_waypoint_reached": "on_nav_waypoint_reached",
    "nav_completed": "on_nav_completed",
    "nav_stopped": "on_nav_stopped",
}


class MapHandle(EventDispatcher):
    """Kivy-side handle to the map process. Bind to `on_*` events like a
    pyqtSignal (`map_handle.bind(on_map_clicked=callback)`); call the
    `update_track`/`center_on`/... methods like the old MapView's methods."""

    __events__ = tuple(_EVENTS)

    def __init__(self, x: int, y: int, width: int, height: int, **kwargs):
        super().__init__(**kwargs)
        self._cmd_queue: multiprocessing.Queue = multiprocessing.Queue()
        self._evt_queue: multiprocessing.Queue = multiprocessing.Queue()
        self._proc = multiprocessing.Process(
            target=run_map_process,
            args=(self._cmd_queue, self._evt_queue, x, y, width, height),
            daemon=True,
        )
        self._proc.start()
        self._drain_thread = threading.Thread(target=self._drain_events, daemon=True)
        self._drain_thread.start()

    # ---- lifecycle --------------------------------------------------------

    def stop(self):
        self._cmd_queue.put(None)
        self._proc.join(timeout=2)

    def move(self, x: int, y: int):
        self._cmd_queue.put({"action": "move", "x": x, "y": y})

    def resize(self, width: int, height: int):
        self._cmd_queue.put({"action": "resize", "width": width, "height": height})

    # ---- event drain (background thread -> Kivy Clock) ---------------------

    def _drain_events(self):
        while True:
            evt = self._evt_queue.get()
            Clock.schedule_once(lambda dt, e=evt: self._handle_event(e), 0)

    def _handle_event(self, evt: dict):
        kind = evt.pop("event", None)
        ev_name = _EVENT_NAME_MAP.get(kind)
        if ev_name:
            self.dispatch(ev_name, evt)

    # required no-op default handlers for each declared event
    def on_map_ready(self, *a):
        pass

    def on_coords_changed(self, *a):
        pass

    def on_own_position(self, *a):
        pass

    def on_track_clicked(self, *a):
        pass

    def on_map_clicked(self, *a):
        pass

    def on_graphic_drawn(self, *a):
        pass

    def on_measure_done(self, *a):
        pass

    def on_radial_action(self, *a):
        pass

    def on_symbol_selected(self, *a):
        pass

    def on_free_draw_saved(self, *a):
        pass

    def on_overlay_create_requested(self, *a):
        pass

    def on_overlay_patch_requested(self, *a):
        pass

    def on_overlay_delete_requested(self, *a):
        pass

    def on_layer_export_requested(self, *a):
        pass

    def on_layer_import_requested(self, *a):
        pass

    def on_tactical_object_action(self, *a):
        pass

    def on_tactical_object_move(self, *a):
        pass

    def on_route_drawn(self, *a):
        pass

    def on_route_draw_cancelled(self, *a):
        pass

    def on_nav_waypoint_reached(self, *a):
        pass

    def on_nav_completed(self, *a):
        pass

    def on_nav_stopped(self, *a):
        pass

    # ---- Python -> JavaScript (fire-and-forget, mirrors front/map/view.py) -

    def _js(self, code: str):
        self._cmd_queue.put({"action": "eval_js", "code": code})

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

    def set_group_level(self, level: str):
        self._js(f"setGroupLevel({json.dumps(level)})")

    def set_hierarchy(self, data: dict):
        self._js(f"setHierarchy({json.dumps(data)})")

    def set_group_auto(self, auto: bool):
        self._js(f"setGroupAuto({json.dumps(auto)})")

    def fit_tracks(self):
        self._js("fitTracks()")

    def center_on(self, lat: float, lon: float, zoom: int = 14):
        self._js(f"centerOn({lat}, {lon}, {zoom})")

    def add_mbtiles_layer(
        self,
        mbt_id: str,
        tile_url: str,
        min_zoom: int = 0,
        max_zoom: int = 18,
        name: str = "",
    ):
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

    def add_tactical_object(self, obj: dict):
        self._js(f"addTacticalObject({json.dumps(obj)})")

    def remove_tactical_object(self, obj_id: str):
        self._js(f"removeTacticalObject({json.dumps(obj_id)})")

    def clear_all_graphics(self):
        self._js("clearAllGraphics()")

    def update_vehicle(self, vehicle: dict):
        self._js(f"updateVehicle({json.dumps(vehicle)})")

    def remove_vehicle(self, vehicle_id: int):
        self._js(f"removeVehicle({json.dumps(vehicle_id)})")

    def add_fire_mission(self, fm: dict):
        self._js(f"addFireMission({json.dumps(fm)})")

    def add_kml_layer(self, kml: dict):
        self._js(f"addKmlLayer({json.dumps(kml)})")

    def set_overlays(self, overlays: list, can_edit: bool = False):
        self._js(f"setOverlays({json.dumps(overlays)}, {json.dumps(bool(can_edit))})")

    def set_overlay_active(self, overlay_id, on: bool = True):
        self._js(f"setOverlayActive({json.dumps(overlay_id)}, {json.dumps(bool(on))})")

    def remove_kml_layer(self, layer_id: str):
        self._js(f"removeKmlLayer({json.dumps(layer_id)})")

    def add_cbrn_zone(self, report: dict):
        self._js(f"addCbrnZone({json.dumps(report)})")

    def open_symbol_picker(self, lat: float, lon: float, affiliation: str = "FRIENDLY"):
        self._js(f"openSymbolPicker({lat}, {lon}, {json.dumps(affiliation)})")

    def arm_symbol_placement(self, affiliation: str = "FRIENDLY"):
        self._js(f"armSymbolPlacement({json.dumps(affiliation)})")

    def disarm_symbol_placement(self):
        self._js("disarmSymbolPlacement()")

    def set_gps_config(
        self,
        enabled: bool,
        high_accuracy: bool,
        max_age_ms: int,
        center_on_fix: bool,
        show_accuracy: bool,
    ):
        self._js(
            f"setGPSConfig({json.dumps(enabled)}, {json.dumps(high_accuracy)}, "
            f"{int(max_age_ms)}, {json.dumps(center_on_fix)}, {json.dumps(show_accuracy)})"
        )

    def set_own_position_native(
        self, lat: float, lon: float, accuracy: float, heading: float, source: str
    ):
        self._js(
            f"setOwnPositionNative({json.dumps(float(lat))}, {json.dumps(float(lon))}, "
            f"{json.dumps(float(accuracy))}, {json.dumps(float(heading))}, "
            f"{json.dumps(source)})"
        )

    def set_own_position_status(self, text: str):
        self._js(f"setOwnPositionStatus({json.dumps(text)})")

    def set_weather_layer(self, layer_name: str, visible: bool):
        self._js(f"setWeatherLayer({json.dumps(layer_name)}, {json.dumps(visible)})")

    def fetch_weather(self):
        self._js("fetchWeatherAtCenter()")

    def set_draw_graphic(self, graphic_type: str, affiliation: str):
        self._js(
            f"setDrawGraphic({json.dumps(graphic_type)}, {json.dumps(affiliation)})"
        )

    def set_free_draw(self, tool: str, color: str, thickness: int):
        self._js(
            f"setFreeDraw({json.dumps(tool)}, {json.dumps(color)}, {int(thickness)})"
        )

    def free_draw_undo(self):
        self._js("undoFreeDraw()")

    def free_draw_clear(self):
        self._js("clearFreeDrawLayer()")

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
