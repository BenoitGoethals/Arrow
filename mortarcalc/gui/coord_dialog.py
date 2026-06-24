"""Fallback-dialog voor manuele coördinaten-invoer (lat/lon of MGRS).

Wordt gebruikt als CoreLocation niet beschikbaar is of geweigerd wordt.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QDoubleSpinBox,
    QPushButton, QTabWidget, QWidget, QLabel, QMessageBox,
)

from ..geo import Position, latlon_to_utm, mgrs_to_utm
from .mgrs_field import MgrsLineEdit


class CoordDialog(QDialog):
    """Dialog die de gebruiker laat kiezen tussen lat/lon decimaal of MGRS plakken."""

    def __init__(self, parent=None, default_altitude: float = 0.0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coördinaten invoeren")
        self.result_position: Position | None = None

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "CoreLocation is niet beschikbaar of geweigerd. Voer de positie "
            "manueel in (bv. uit telefoon-GPS, Garmin of kaartapp)."
        ))

        tabs = QTabWidget()
        tabs.addTab(self._build_latlon_tab(default_altitude), "Lat / Lon (decimaal)")
        tabs.addTab(self._build_mgrs_tab(default_altitude), "MGRS")
        root.addWidget(tabs)
        self.tabs = tabs

        btn_row = QHBoxLayout()
        b_ok = QPushButton("OK"); b_ok.clicked.connect(self._on_ok)
        b_cancel = QPushButton("Annuleer"); b_cancel.clicked.connect(self.reject)
        btn_row.addStretch(1); btn_row.addWidget(b_ok); btn_row.addWidget(b_cancel)
        root.addLayout(btn_row)

    def _build_latlon_tab(self, default_alt: float) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        self.in_lat = QDoubleSpinBox(); self.in_lat.setDecimals(6); self.in_lat.setRange(-90, 90)
        self.in_lon = QDoubleSpinBox(); self.in_lon.setDecimals(6); self.in_lon.setRange(-180, 180)
        self.in_alt_ll = QDoubleSpinBox(); self.in_alt_ll.setRange(-500, 9000); self.in_alt_ll.setSuffix(" m"); self.in_alt_ll.setValue(default_alt)
        f.addRow("Latitude (°N)", self.in_lat)
        f.addRow("Longitude (°E)", self.in_lon)
        f.addRow("Hoogte", self.in_alt_ll)
        return w

    def _build_mgrs_tab(self, default_alt: float) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        self.in_mgrs = MgrsLineEdit()
        self.in_alt_m = QDoubleSpinBox(); self.in_alt_m.setRange(-500, 9000); self.in_alt_m.setSuffix(" m"); self.in_alt_m.setValue(default_alt)
        f.addRow("MGRS", self.in_mgrs)
        f.addRow("Hoogte", self.in_alt_m)
        return w

    def _on_ok(self) -> None:
        if self.tabs.currentIndex() == 0:
            try:
                self.result_position = latlon_to_utm(
                    lat=self.in_lat.value(), lon=self.in_lon.value(),
                    altitude_m=self.in_alt_ll.value(),
                )
            except Exception as e:
                QMessageBox.warning(self, "Lat/Lon", str(e)); return
        else:
            try:
                self.result_position = mgrs_to_utm(self.in_mgrs.text().strip(),
                                                   altitude_m=self.in_alt_m.value())
            except Exception as e:
                QMessageBox.warning(self, "MGRS", str(e)); return
        self.accept()


def prompt_position(parent=None, default_altitude: float = 0.0) -> Position | None:
    """Toon de dialog en geef de Position terug of None bij annuleer/fout."""
    dlg = CoordDialog(parent, default_altitude=default_altitude)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.result_position
    return None
