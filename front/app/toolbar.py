"""Main toolbar — map tools, layer controls, alert button."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QToolBar, QToolButton, QLabel, QComboBox, QMenu, QSizePolicy,
    QCheckBox, QWidgetAction, QWidget, QVBoxLayout, QFileDialog, QMessageBox,
)
import sys
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QIcon

from front.panels.layers.panel import LayersDialog


class MainToolbar(QToolBar):
    # Emitted when the user picks a map tool/draw mode
    mode_changed    = pyqtSignal(str)        # 'pointer','measure', or graphic type
    # Emitted when layer visibility toggles
    layer_toggled   = pyqtSignal(str, bool)  # layer name, visible
    # Base layer selection
    base_changed    = pyqtSignal(str)        # 'OSM','DARK','SATELLITE','TOPO'
    # MBTiles file selected
    mbtiles_selected = pyqtSignal(str)       # file path
    # Fit all tracks
    fit_requested    = pyqtSignal()
    weather_fetch    = pyqtSignal()
    weather_toggled  = pyqtSignal(str, bool)  # layer name, visible
    # Emergency alert
    alert_requested  = pyqtSignal(str)        # alert type

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(False)
        self.setObjectName("mainToolbar")
        self._mode_btns: dict[str, QToolButton] = {}
        self._build()

    def _build(self):
        # ---- Pointer / Measure -----------------------------------------
        self._add_mode_btn("⊹", "pointer", "Pointer (navigate)")
        self.addSeparator()

        # ---- Measure dropdown ------------------------------------------
        meas_btn = QToolButton()
        meas_btn.setText("📏 MEASURE ▾")
        meas_btn.setObjectName("toolButton")
        meas_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        meas_menu = QMenu(self)
        for label, mode, tip in [
            ("⟷  Distance chain",    "measure_dist",  "Click points to measure distance"),
            ("↗  Azimuth (2 points)", "measure_az",    "Click 2 points for bearing + mils"),
            ("⊙  Range circles",      "measure_range", "Draw range rings from a center"),
            ("✕  Clear measurements", "meas_clear",    "Remove all measurements"),
        ]:
            act = meas_menu.addAction(label)
            act.setToolTip(tip)
            act.triggered.connect(lambda checked, m=mode: self.mode_changed.emit(m))
        meas_btn.setMenu(meas_menu)
        self.addWidget(meas_btn)
        self.addSeparator()

        # ---- Draw drop-down -----------------------------------------
        draw_btn = QToolButton()
        draw_btn.setText("DRAW ▾")
        draw_btn.setObjectName("toolButton")
        draw_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        draw_menu = QMenu(self)

        LINES = [
            ("PHASE_LINE", "PL  Phase Line"),
            ("BOUNDARY",   "BD  Boundary"),
            ("FSCL",       "FSCL  Fire Support Coord Line"),
            ("CFL",        "CFL  Coordinated Fire Line"),
            ("NFL",        "NFL  No-Fire Line"),
            ("AXIS",       "AX  Axis of Advance"),
            ("ROUTE",      "RT  Route"),
        ]
        AREAS = [
            ("NFA",             "NFA  No-Fire Area"),
            ("FFA",             "FFA  Free-Fire Area"),
            ("OBJECTIVE",       "OBJ  Objective"),
            ("ENGAGEMENT_AREA", "EA   Engagement Area"),
            ("NAI",             "NAI  Named Area of Interest"),
            ("TAI",             "TAI  Targeted Area of Interest"),
            ("ASSEMBLY_AREA",   "AA   Assembly Area"),
        ]

        draw_menu.addSection("Lines")
        for gtype, label in LINES:
            act = draw_menu.addAction(label)
            act.triggered.connect(lambda checked, g=gtype: self._set_mode(g))

        draw_menu.addSection("Areas")
        for gtype, label in AREAS:
            act = draw_menu.addAction(label)
            act.triggered.connect(lambda checked, g=gtype: self._set_mode(g))

        draw_btn.setMenu(draw_menu)
        self.addWidget(draw_btn)
        self.addSeparator()

        # ---- Layers button → opens visibility panel ---------------------
        self._layers_dialog = LayersDialog()
        self._layers_dialog.layer_toggled.connect(self.layer_toggled)

        layers_btn = QToolButton()
        layers_btn.setText("LAYERS ▾")
        layers_btn.setObjectName("toolButton")
        layers_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layers_menu = QMenu(self)

        layers_menu.addSection("Base Map")
        for name in ("OSM", "DARK", "SATELLITE", "TOPO"):
            act = layers_menu.addAction(name)
            act.triggered.connect(lambda checked, n=name: self.base_changed.emit(n))

        layers_menu.addSeparator()
        mbt_act = layers_menu.addAction("📂  Load MBTiles…")
        mbt_act.triggered.connect(self._load_mbtiles)

        layers_menu.addSeparator()
        vis_act = layers_menu.addAction("🗂  Map Visibility…")
        vis_act.triggered.connect(self._layers_dialog.show)
        vis_act.triggered.connect(self._layers_dialog.raise_)

        layers_btn.setMenu(layers_menu)
        self.addWidget(layers_btn)

        # ---- Fit tracks -----------------------------------------------
        fit_btn = QToolButton()
        fit_btn.setText("⊡  FIT")
        fit_btn.setObjectName("toolButton")
        fit_btn.clicked.connect(self.fit_requested.emit)
        self.addWidget(fit_btn)

        # ---- Weather drop-down ---------------------------------------
        wx_btn = QToolButton()
        wx_btn.setText("☁ WX ▾")
        wx_btn.setObjectName("toolButton")
        wx_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        wx_menu = QMenu(self)
        wx_menu.addSection("Overlay")
        for layer, label in [("rain_radar","🌧 Rain Radar (live)"),("precipitation_new","🌂 Precipitation"),("clouds_new","☁ Cloud Cover"),("wind_new","💨 Wind Speed"),("temp_new","🌡 Temperature")]:
            act = wx_menu.addAction(label)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, l=layer: self.weather_toggled.emit(l, checked))
        wx_menu.addSeparator()
        wx_fetch = wx_menu.addAction("⟳  Fetch current weather")
        wx_fetch.triggered.connect(self.weather_fetch.emit)
        wx_btn.setMenu(wx_menu)
        self.addWidget(wx_btn)
        self.addSeparator()

        # ---- Spacer ---------------------------------------------------
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

        # ---- App label -------------------------------------------------
        lbl = QLabel("ARROW FRONT")
        lbl.setStyleSheet(
            "color:#3fb950;font-family:'Courier New',monospace;"
            "font-size:13px;font-weight:bold;letter-spacing:3px;padding:0 12px;"
        )
        self.addWidget(lbl)

        # ---- Emergency alert button ------------------------------------
        self.addSeparator()
        alert_btn = QToolButton()
        alert_btn.setText("⚡  TIC")
        alert_btn.setObjectName("toolButton")
        alert_btn.setStyleSheet(
            "QToolButton{background:#8b1538;border:1px solid #da3633;color:#ffffff;"
            "font-weight:700;font-size:11px;padding:4px 12px;letter-spacing:1px;}"
            "QToolButton:hover{background:#da3633;}"
        )
        alert_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        alert_menu = QMenu(self)
        for atype in ("TIC", "MEDICAL", "EVAC", "LOST_COMMS"):
            act = alert_menu.addAction(atype)
            act.triggered.connect(lambda checked, a=atype: self.alert_requested.emit(a))
        alert_btn.setMenu(alert_menu)
        self.addWidget(alert_btn)

        # ---- Exit button -----------------------------------------------
        self.addSeparator()
        exit_btn = QToolButton()
        exit_btn.setText("✕")
        exit_btn.setToolTip("Exit Arrow Front")
        exit_btn.setStyleSheet(
            "QToolButton{background:transparent;border:none;color:#484f58;"
            "font-size:16px;font-weight:bold;padding:4px 10px;}"
            "QToolButton:hover{color:#f85149;background:#21262d;}"
        )
        exit_btn.clicked.connect(self._confirm_exit)
        self.addWidget(exit_btn)

        # Set pointer as default
        self._set_mode("pointer", emit=False)

    # ---- Mode management -------------------------------------------------

    def _add_mode_btn(self, icon_text: str, mode: str, tooltip: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(icon_text)
        btn.setToolTip(tooltip)
        btn.setObjectName("toolButton")
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self._set_mode(mode))
        self.addWidget(btn)
        self._mode_btns[mode] = btn
        return btn

    def _set_mode(self, mode: str, emit: bool = True):
        for m, btn in self._mode_btns.items():
            btn.setChecked(m == mode)
        if emit:
            self.mode_changed.emit(mode)

    def _confirm_exit(self):
        ans = QMessageBox.question(
            None, "Exit Arrow Front", "Exit Arrow Front?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Yes:
            sys.exit(0)

    def _load_mbtiles(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Open MBTiles", "", "MBTiles files (*.mbtiles *.mb)"
        )
        if path:
            self.mbtiles_selected.emit(path)
