"""QWebChannel bridge — all Python↔JS slots and signals."""
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class MapBridge(QObject):
    map_ready        = pyqtSignal()
    coords_changed   = pyqtSignal(float, float, str)
    track_clicked    = pyqtSignal(str)
    map_clicked      = pyqtSignal(float, float)
    graphic_drawn    = pyqtSignal(str, str, str)   # type, geojson, affiliation
    measure_done     = pyqtSignal(str, str)
    radial_action    = pyqtSignal(str, float, float)
    symbol_selected  = pyqtSignal(str, str, float, float)  # sidc, designation, lat, lon
    free_draw_saved  = pyqtSignal(str, str, str)   # type, geom_json, notes_json

    @pyqtSlot()
    def onReady(self):
        self.map_ready.emit()

    @pyqtSlot(float, float, str)
    def onCoordsChanged(self, lat, lon, mgrs):
        self.coords_changed.emit(lat, lon, mgrs)

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

    @pyqtSlot(str, str, str)
    def onFreeDrawSaved(self, obj_type: str, geom_json: str, notes_json: str):
        self.free_draw_saved.emit(obj_type, geom_json, notes_json)
