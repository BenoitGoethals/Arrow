"""QWebChannel bridge — all Python↔JS slots and signals."""

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class MapBridge(QObject):
    map_ready = pyqtSignal()
    coords_changed = pyqtSignal(float, float, str)
    own_position = pyqtSignal(float, float, float)  # lat, lon, accuracy (m)
    track_clicked = pyqtSignal(str)
    map_clicked = pyqtSignal(float, float)
    graphic_drawn = pyqtSignal(str, str, str)  # type, geojson, affiliation
    measure_done = pyqtSignal(str, str)
    radial_action = pyqtSignal(str, float, float)
    symbol_selected = pyqtSignal(str, str, float, float)  # sidc, designation, lat, lon
    # type, geom_json, notes_json, active_overlay_id (0 = none / not single-active)
    free_draw_saved = pyqtSignal(str, str, str, int)
    # Saved-overlays panel → Python (all fire-and-forget; results return via setOverlays)
    overlay_create_requested = pyqtSignal(str)  # json {name, description, object_ids}
    overlay_patch_requested = pyqtSignal(int, str)  # overlay_id, json fields
    overlay_delete_requested = pyqtSignal(int)  # overlay_id
    layer_export_requested = pyqtSignal(str, int)  # kind ("OVERLAY"|"KML"), source_id
    layer_import_requested = pyqtSignal()  # triggers native open-file dialog
    tactical_object_action = pyqtSignal(str, int)  # action ("delete"), obj_id
    tactical_object_move = pyqtSignal(
        int, float, float, str
    )  # obj_id, lat, lon, geometry_json
    route_drawn = pyqtSignal(str, str)  # route_id, waypoints_json
    route_draw_cancelled = pyqtSignal(str)  # route_id
    nav_waypoint_reached = pyqtSignal(str, int)  # route_id, wp_idx
    nav_completed = pyqtSignal(str)  # route_id
    nav_stopped = pyqtSignal()

    @pyqtSlot()
    def onReady(self):
        self.map_ready.emit()

    @pyqtSlot(float, float, str)
    def onCoordsChanged(self, lat, lon, mgrs):
        self.coords_changed.emit(lat, lon, mgrs)

    @pyqtSlot(float, float, float)
    def onOwnPosition(self, lat, lon, accuracy):
        self.own_position.emit(lat, lon, accuracy)

    @pyqtSlot(str)
    def onTrackClicked(self, track_id):
        self.track_clicked.emit(track_id)

    @pyqtSlot(float, float)
    def onMapClicked(self, lat, lon):
        self.map_clicked.emit(lat, lon)

    @pyqtSlot(str, str, str)
    def onGraphicDrawn(self, graphic_type, geojson, affiliation):
        self.graphic_drawn.emit(graphic_type, geojson, affiliation)

    @pyqtSlot(str, str)
    def onMeasureComplete(self, distance_str, bearing_str):
        self.measure_done.emit(distance_str, bearing_str)

    @pyqtSlot(str, float, float)
    def onRadialAction(self, action, lat, lon):
        self.radial_action.emit(action, lat, lon)

    @pyqtSlot(str, str, float, float)
    def onSymbolSelected(self, sidc, designation, lat, lon):
        self.symbol_selected.emit(sidc, designation, lat, lon)

    @pyqtSlot(str, str, str, int)
    def onFreeDrawSaved(
        self,
        obj_type: str,
        geom_json: str,
        notes_json: str,
        active_overlay_id: int = 0,
    ):
        self.free_draw_saved.emit(obj_type, geom_json, notes_json, active_overlay_id)

    @pyqtSlot(str)
    def onOverlayCreate(self, json_str: str):
        self.overlay_create_requested.emit(json_str)

    @pyqtSlot(int, str)
    def onOverlayPatch(self, overlay_id: int, json_str: str):
        self.overlay_patch_requested.emit(overlay_id, json_str)

    @pyqtSlot(int)
    def onOverlayDelete(self, overlay_id: int):
        self.overlay_delete_requested.emit(overlay_id)

    @pyqtSlot(str, int)
    def onLayerExport(self, kind: str, source_id: int):
        self.layer_export_requested.emit(kind, source_id)

    @pyqtSlot()
    def onLayerImport(self):
        self.layer_import_requested.emit()

    @pyqtSlot(str, int)
    def onTacticalObjectAction(self, action: str, obj_id: int):
        self.tactical_object_action.emit(action, obj_id)

    @pyqtSlot(int, float, float, str)
    def onTacticalObjectMove(
        self, obj_id: int, lat: float, lon: float, geometry_json: str = ""
    ):
        self.tactical_object_move.emit(obj_id, lat, lon, geometry_json)

    @pyqtSlot(str, str)
    def onRouteDrawn(self, route_id: str, waypoints_json: str):
        self.route_drawn.emit(route_id, waypoints_json)

    @pyqtSlot(str)
    def onRouteDrawCancelled(self, route_id: str):
        self.route_draw_cancelled.emit(route_id)

    @pyqtSlot(str, int)
    def onNavWaypointReached(self, route_id: str, wp_idx: int):
        self.nav_waypoint_reached.emit(route_id, wp_idx)

    @pyqtSlot(str)
    def onNavCompleted(self, route_id: str):
        self.nav_completed.emit(route_id)

    @pyqtSlot()
    def onNavStopped(self):
        self.nav_stopped.emit()
