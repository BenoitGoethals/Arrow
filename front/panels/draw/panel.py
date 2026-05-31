"""Tactical Graphics Panel — matches Frontline screenshot 2.
Pick a graphic type, then draw it on the map.
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QScrollArea, QButtonGroup,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

# (display_name, graphic_type_key, affiliation F/H, icon_char)
FRIENDLY_GRAPHICS = [
    ("Attack",         "ATK_F",  "F", "▶"),
    ("Counterattack",  "CTR_F",  "F", "↺"),
    ("Defense",        "DEF_F",  "F", "⊢"),
    ("Ambush",         "AMB_F",  "F", "∨"),
    ("Block",          "BND_F",  "F", "⊥"),
    ("Bypass",         "CTR_F",  "F", "↗"),
    ("Withdraw",       "DEF_F",  "F", "↩"),
    ("Objective area", "OBJ_F",  "F", "⊡"),
    ("Boundary",       "BOUNDARY","F", "+"),
    ("FLOT",           "FLOT",   "F", "—"),
    ("FLET",           "FLET",   "H", "—"),
    ("Phase line",     "PHASE_LINE","F","—"),
]

ENEMY_GRAPHICS = [
    ("Attack",         "ATK_H",  "H", "▶"),
    ("Counterattack",  "CTR_H",  "H", "↺"),
    ("Defense",        "DEF_H",  "H", "⊢"),
    ("Ambush",         "AMB_H",  "H", "∨"),
    ("Block",          "BND_H",  "H", "⊥"),
    ("Bypass",         "CTR_H",  "H", "↗"),
    ("Withdraw",       "DEF_H",  "H", "↩"),
    ("Objective area", "OBJ_H",  "H", "⊡"),
    ("Boundary",       "BOUNDARY","H", "+"),
    ("FLOT",           "FLOT",   "H", "—"),
    ("FLET",           "FLET",   "H", "—"),
    ("Phase line",     "PHASE_LINE","H","—"),
]

CONTROL_GRAPHICS = [
    ("FSCL",            "FSCL",            "F", "—"),
    ("CFL",             "CFL",             "F", "—"),
    ("No-Fire Line",    "NFL",             "F", "—"),
    ("No-Fire Area",    "NFA",             "H", "□"),
    ("Free-Fire Area",  "FFA",             "F", "□"),
    ("Engagement Area", "ENGAGEMENT_AREA", "H", "□"),
    ("NAI",             "NAI",             "F", "□"),
    ("TAI",             "TAI",             "H", "□"),
    ("Axis of Advance", "AXIS",            "F", "→"),
    ("Route",           "ROUTE",           "F", "—"),
]

ECHELON_LABELS = [("—", "--"), ("TM", "A-"), ("SEC", "D-"), ("PL", "E-"), ("COY", "F-")]

_BLUE  = "#3b82f6"
_RED   = "#ef4444"
_AMBER = "#f59e0b"


class DrawPanel(QWidget):
    """Replicates the Frontline tactical graphics selection panel."""

    draw_mode_changed = pyqtSignal(str)   # type_key passed to map
    draw_graphic      = pyqtSignal(str, str)  # type_key, affiliation (F/H)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_type: str | None = None
        self._active_aff:  str = "F"
        self._echelon: str = "--"
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Instruction header
        hdr = QLabel("  Pick a graphic, then click on the map.")
        hdr.setStyleSheet("color:#8b949e;font-size:10px;padding:6px 8px;background:#161b22;border-bottom:1px solid #21262d;")
        outer.addWidget(hdr)

        # Echelon row
        ech_row = QHBoxLayout()
        ech_row.setContentsMargins(8, 6, 8, 4)
        ech_row.setSpacing(4)
        ech_row.addWidget(QLabel("ECHELON", styleSheet="color:#6e7681;font-size:9px;font-weight:700;letter-spacing:1.5px;"))
        self._ech_group = QButtonGroup(self)
        for label, code in ECHELON_LABELS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedSize(42, 26)
            btn.setStyleSheet(self._ech_style(label == "—"))
            self._ech_group.addButton(btn)
            ech_row.addWidget(btn)
            btn.setProperty("echcode", code)
            btn.clicked.connect(lambda checked, b=btn: self._set_echelon(b))
        ech_row.addStretch()
        outer.addLayout(ech_row)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFixedHeight(1)
        outer.addWidget(sep)

        # Scrollable graphic list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Friendly section
        layout.addWidget(self._section_header("FRIENDLY GRAPHICS", _BLUE))
        self._friendly_btns = self._graphic_grid(layout, FRIENDLY_GRAPHICS, _BLUE)

        # Enemy section
        layout.addWidget(self._section_header("ENEMY GRAPHICS", _RED))
        self._enemy_btns = self._graphic_grid(layout, ENEMY_GRAPHICS, _RED)

        # Fire Support / Control section
        layout.addWidget(self._section_header("FIRE SUPPORT / CONTROL MEASURES", _AMBER))
        self._control_btns = self._graphic_grid(layout, CONTROL_GRAPHICS, _AMBER)

        layout.addStretch()

        # Cancel button
        self._cancel_btn = QPushButton("✕  Cancel drawing")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#3d1c1c;border:1px solid #f85149;color:#f85149;padding:8px;font-size:10px;font-weight:600;}"
            "QPushButton:hover{background:#f85149;color:#fff;}"
            "QPushButton:disabled{background:#21262d;border-color:#30363d;color:#484f58;}"
        )
        self._cancel_btn.clicked.connect(self._cancel)
        layout.addWidget(self._cancel_btn)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    # ---- Builders --------------------------------------------------------

    def _section_header(self, title: str, color: str) -> QLabel:
        lbl = QLabel(f"  {title}")
        lbl.setStyleSheet(
            f"color:{color};font-size:10px;font-weight:700;letter-spacing:1px;"
            f"padding:5px 4px 3px;border-left:3px solid {color};background:#0d1117;"
        )
        return lbl

    def _graphic_grid(self, parent_layout, items, color: str) -> list[QPushButton]:
        grid = QGridLayout()
        grid.setSpacing(4)
        btns = []
        for idx, (label, gtype, aff, icon) in enumerate(items):
            btn = QPushButton(f" {icon}  {label}")
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.setStyleSheet(self._gfx_btn_style(color, False))
            btn.setProperty("gtype", gtype)
            btn.setProperty("aff", aff)
            btn.setProperty("color", color)
            btn.clicked.connect(lambda checked, b=btn: self._select_graphic(b))
            grid.addWidget(btn, idx // 2, idx % 2)
            btns.append(btn)
        parent_layout.addLayout(grid)
        return btns

    # ---- Logic -----------------------------------------------------------

    def _set_echelon(self, btn: QPushButton):
        for b in self._ech_group.buttons():
            b.setStyleSheet(self._ech_style(b is btn))
        self._echelon = btn.property("echcode") or "--"

    def _select_graphic(self, btn: QPushButton):
        # Deselect all others
        all_btns = self._friendly_btns + self._enemy_btns + self._control_btns
        for b in all_btns:
            if b is not btn:
                b.setChecked(False)
                b.setStyleSheet(self._gfx_btn_style(b.property("color"), False))

        gtype = btn.property("gtype")
        aff   = btn.property("aff")
        color = btn.property("color")

        if btn.isChecked():
            self._active_type = gtype
            self._active_aff  = aff
            btn.setStyleSheet(self._gfx_btn_style(color, True))
            self._cancel_btn.setEnabled(True)
            self.draw_graphic.emit(gtype, aff)
            self.draw_mode_changed.emit(gtype)
        else:
            self._cancel()

    def _cancel(self):
        for b in self._friendly_btns + self._enemy_btns + self._control_btns:
            b.setChecked(False)
            b.setStyleSheet(self._gfx_btn_style(b.property("color"), False))
        self._cancel_btn.setEnabled(False)
        self._active_type = None
        self.draw_mode_changed.emit("pointer")

    # ---- Style helpers ---------------------------------------------------

    @staticmethod
    def _ech_style(active: bool) -> str:
        if active:
            return "QPushButton{background:#1c2d3f;border:1px solid #1f6feb;color:#79c0ff;font-size:10px;font-weight:700;}"
        return "QPushButton{background:#21262d;border:1px solid #30363d;color:#8b949e;font-size:10px;}"

    @staticmethod
    def _gfx_btn_style(color: str, active: bool) -> str:
        if active:
            return (f"QPushButton{{background:{color}22;border:1px solid {color};"
                    f"color:{color};font-size:10px;text-align:left;padding:0 6px;font-weight:600;}}")
        return (f"QPushButton{{background:#161b22;border:1px solid #30363d;"
                f"color:#8b949e;font-size:10px;text-align:left;padding:0 6px;}}"
                f"QPushButton:hover{{background:{color}15;border-color:{color};color:{color};}}")
