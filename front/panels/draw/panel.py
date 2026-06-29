"""Tactical Graphics Panel — matches Frontline screenshot 2.
Pick a graphic type, then draw it on the map.
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QFrame,
    QScrollArea,
    QButtonGroup,
)
from PyQt6.QtCore import pyqtSignal, Qt

# (display_name, graphic_type_key, affiliation F/H, icon_char)
# Canonical tactical-graphic type vocabulary — SHARED with web + android.
# affiliation is a SEPARATE field (FRIENDLY/HOSTILE), NOT baked into the type.
FRIENDLY_GRAPHICS = [
    ("Attack", "ATK_AXIS", "F", "▶"),
    ("Counterattack", "COUNTERATTACK", "F", "↺"),
    ("Defense", "DEF_AREA", "F", "⊢"),
    ("Ambush", "AMBUSH", "F", "∨"),
    ("Block", "BLOCK", "F", "⊥"),
    ("Bypass", "BYPASS", "F", "↗"),
    ("Withdraw", "WITHDRAW", "F", "↩"),
    ("Objective area", "OBJ_AREA", "F", "⊡"),
    ("Boundary", "BOUNDARY", "F", "+"),
    ("FLOT", "FLOT", "F", "—"),
    ("FLET", "FLET", "F", "—"),
    ("Phase line", "PHASE_LINE", "F", "—"),
]

ENEMY_GRAPHICS = [
    ("Attack", "ATK_AXIS", "H", "▶"),
    ("Counterattack", "COUNTERATTACK", "H", "↺"),
    ("Defense", "DEF_AREA", "H", "⊢"),
    ("Ambush", "AMBUSH", "H", "∨"),
    ("Block", "BLOCK", "H", "⊥"),
    ("Bypass", "BYPASS", "H", "↗"),
    ("Withdraw", "WITHDRAW", "H", "↩"),
    ("Objective area", "OBJ_AREA", "H", "⊡"),
    ("Boundary", "BOUNDARY", "H", "+"),
    ("FLOT", "FLOT", "H", "—"),
    ("FLET", "FLET", "H", "—"),
    ("Phase line", "PHASE_LINE", "H", "—"),
]

CONTROL_GRAPHICS = [
    ("FSCL", "FSCL", "F", "—"),
    ("CFL", "CFL", "F", "—"),
    ("No-Fire Line", "NFL", "F", "—"),
    ("No-Fire Area", "NFA", "H", "□"),
    ("Free-Fire Area", "FFA", "F", "□"),
    ("Engagement Area", "ENGAGEMENT_AREA", "H", "□"),
    ("NAI", "NAI", "F", "□"),
    ("TAI", "TAI", "H", "□"),
    ("Axis of Advance", "AXIS", "F", "→"),
    ("Route", "ROUTE", "F", "—"),
]

# Echelon SIDC codes (letter at index 11) — MIL-STD-2525B: A=Team C=Section
# D=Platoon E=Company. Matches symbology.ECHELON and the web client.
ECHELON_LABELS = [("—", "--"), ("TM", "-A"), ("SEC", "-C"), ("PL", "-D"), ("COY", "-E")]

_BLUE = "#3b82f6"
_RED = "#ef4444"
_AMBER = "#f59e0b"


_FD_COLORS = [
    ("#f85149", "Red"),
    ("#ff8800", "Orange"),
    ("#ffd700", "Yellow"),
    ("#3fb950", "Green"),
    ("#00aaff", "Blue"),
    ("#d2a8ff", "Purple"),
    ("#e6edf3", "White"),
    ("#111827", "Black"),
]
_FD_THICK = [1, 2, 3, 5, 8]


class DrawPanel(QWidget):
    """Replicates the Frontline tactical graphics selection panel."""

    draw_mode_changed = pyqtSignal(str)  # type_key passed to map
    draw_graphic = pyqtSignal(str, str)  # type_key, affiliation (F/H)
    free_draw_changed = pyqtSignal(
        str, str, int
    )  # tool ('pen'|'text'|'none'), color, thickness
    free_draw_undo = pyqtSignal()
    free_draw_clear = pyqtSignal()
    delete_all_graphics = pyqtSignal()  # wipe every tactical object/graphic

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_type: str | None = None
        self._active_aff: str = "F"
        self._echelon: str = "--"
        self._fd_color: str = "#f85149"
        self._fd_thick: int = 2
        self._fd_tool: str = "none"
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Instruction header
        hdr = QLabel("  Pick a graphic, then click on the map.")
        hdr.setStyleSheet(
            "color:#8b949e;font-size:13px;padding:6px 8px;background:#161b22;border-bottom:1px solid #21262d;"
        )
        outer.addWidget(hdr)

        # Echelon row
        ech_row = QHBoxLayout()
        ech_row.setContentsMargins(8, 6, 8, 4)
        ech_row.setSpacing(4)
        ech_row.addWidget(
            QLabel(
                "ECHELON",
                styleSheet="color:#6e7681;font-size:12px;font-weight:700;letter-spacing:1.5px;",
            )
        )
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

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
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

        # ── Free Draw section ─────────────────────────────────────
        layout.addWidget(self._section_header("FREE DRAW", "#8b949e"))
        self._build_free_draw_section(layout)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFixedHeight(1)
        layout.addWidget(sep2)

        # Friendly section
        layout.addWidget(self._section_header("FRIENDLY GRAPHICS", _BLUE))
        self._friendly_btns = self._graphic_grid(layout, FRIENDLY_GRAPHICS, _BLUE)

        # Enemy section
        layout.addWidget(self._section_header("ENEMY GRAPHICS", _RED))
        self._enemy_btns = self._graphic_grid(layout, ENEMY_GRAPHICS, _RED)

        # Fire Support / Control section
        layout.addWidget(
            self._section_header("FIRE SUPPORT / CONTROL MEASURES", _AMBER)
        )
        self._control_btns = self._graphic_grid(layout, CONTROL_GRAPHICS, _AMBER)

        layout.addStretch()

        # Cancel button
        self._cancel_btn = QPushButton("✕  Cancel drawing")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#3d1c1c;border:1px solid #f85149;color:#f85149;padding:8px;font-size:13px;font-weight:600;}"
            "QPushButton:hover{background:#f85149;color:#fff;}"
            "QPushButton:disabled{background:#21262d;border-color:#30363d;color:#484f58;}"
        )
        self._cancel_btn.clicked.connect(self._cancel)
        layout.addWidget(self._cancel_btn)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # Pinned at the bottom (always visible): wipe every graphic at once.
        del_all_btn = QPushButton("🗑  DELETE ALL GRAPHICS")
        del_all_btn.setFixedHeight(34)
        del_all_btn.setStyleSheet(
            "QPushButton{background:#3d1c1c;border:1px solid #f85149;color:#f85149;"
            "font-size:13px;font-weight:700;letter-spacing:1px;}"
            "QPushButton:hover{background:#f85149;color:#fff;}"
        )
        del_all_btn.clicked.connect(self.delete_all_graphics.emit)
        outer.addWidget(del_all_btn)

    # ---- Free Draw -------------------------------------------------------

    def _build_free_draw_section(self, layout: QVBoxLayout):
        # Color palette (2 rows × 4)
        color_grid = QGridLayout()
        color_grid.setSpacing(4)
        self._fd_color_btns: list[QPushButton] = []
        for idx, (hex_color, name) in enumerate(_FD_COLORS):
            btn = QPushButton()
            btn.setFixedSize(32, 22)
            btn.setToolTip(name)
            border = "#ffffff" if hex_color == "#111827" else hex_color
            btn.setStyleSheet(
                f"QPushButton{{background:{hex_color};border:2px solid transparent;border-radius:2px;}}"
                f"QPushButton:hover{{border-color:#e6edf3;}}"
            )
            btn.clicked.connect(lambda _, c=hex_color, b=btn: self._set_fd_color(c, b))
            color_grid.addWidget(btn, idx // 4, idx % 4)
            self._fd_color_btns.append(btn)
        layout.addLayout(color_grid)
        # Highlight default color
        self._update_fd_color_btns(self._fd_color)

        # Thickness row
        thick_row = QHBoxLayout()
        thick_row.setSpacing(4)
        thick_row.addWidget(
            QLabel("PX", styleSheet="color:#6e7681;font-size:12px;font-weight:700;")
        )
        self._fd_thick_btns: list[QPushButton] = []
        for t in _FD_THICK:
            btn = QPushButton(str(t))
            btn.setFixedSize(32, 22)
            btn.setStyleSheet(self._fd_thick_style(t == self._fd_thick))
            btn.clicked.connect(lambda _, th=t: self._set_fd_thick(th))
            thick_row.addWidget(btn)
            self._fd_thick_btns.append(btn)
        thick_row.addStretch()
        layout.addLayout(thick_row)

        # Tool buttons row
        tool_row = QHBoxLayout()
        tool_row.setSpacing(4)

        self._fd_pen_btn = QPushButton("✏ Pen")
        self._fd_pen_btn.setCheckable(True)
        self._fd_pen_btn.setFixedHeight(28)
        self._fd_pen_btn.setStyleSheet(self._fd_tool_style(False))
        self._fd_pen_btn.clicked.connect(self._toggle_pen)
        tool_row.addWidget(self._fd_pen_btn)

        self._fd_text_btn = QPushButton("T Text")
        self._fd_text_btn.setCheckable(True)
        self._fd_text_btn.setFixedHeight(28)
        self._fd_text_btn.setStyleSheet(self._fd_tool_style(False))
        self._fd_text_btn.clicked.connect(self._toggle_text)
        tool_row.addWidget(self._fd_text_btn)

        undo_btn = QPushButton("↩ Undo")
        undo_btn.setFixedHeight(28)
        undo_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;color:#8b949e;font-size:13px;padding:0 6px;}"
            "QPushButton:hover{background:#30363d;color:#c9d1d9;}"
        )
        undo_btn.clicked.connect(self.free_draw_undo.emit)
        tool_row.addWidget(undo_btn)

        clr_btn = QPushButton("✕ Clear")
        clr_btn.setFixedHeight(28)
        clr_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;color:#8b949e;font-size:13px;padding:0 6px;}"
            "QPushButton:hover{background:#3d1c1c;border-color:#f85149;color:#f85149;}"
        )
        clr_btn.clicked.connect(self.free_draw_clear.emit)
        tool_row.addWidget(clr_btn)

        layout.addLayout(tool_row)

    def _set_fd_color(self, color: str, clicked_btn: QPushButton):
        self._fd_color = color
        self._update_fd_color_btns(color)
        if self._fd_tool != "none":
            self.free_draw_changed.emit(self._fd_tool, color, self._fd_thick)

    def _update_fd_color_btns(self, active_color: str):
        for btn, (hex_color, _) in zip(self._fd_color_btns, _FD_COLORS):
            if hex_color == active_color:
                btn.setStyleSheet(
                    f"QPushButton{{background:{hex_color};border:2px solid #e6edf3;border-radius:2px;}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background:{hex_color};border:2px solid transparent;border-radius:2px;}}"
                    f"QPushButton:hover{{border-color:#e6edf3;}}"
                )

    def _set_fd_thick(self, thickness: int):
        self._fd_thick = thickness
        for btn in self._fd_thick_btns:
            t = int(btn.text())
            btn.setStyleSheet(self._fd_thick_style(t == thickness))
        if self._fd_tool != "none":
            self.free_draw_changed.emit(self._fd_tool, self._fd_color, thickness)

    def _toggle_pen(self):
        if self._fd_pen_btn.isChecked():
            self._fd_text_btn.setChecked(False)
            self._fd_text_btn.setStyleSheet(self._fd_tool_style(False))
            self._fd_pen_btn.setStyleSheet(self._fd_tool_style(True))
            self._fd_tool = "pen"
            self._cancel_btn.setEnabled(True)
            self.free_draw_changed.emit("pen", self._fd_color, self._fd_thick)
        else:
            self._fd_pen_btn.setStyleSheet(self._fd_tool_style(False))
            self._fd_tool = "none"
            if self._active_type is None:
                self._cancel_btn.setEnabled(False)
            self.free_draw_changed.emit("none", self._fd_color, self._fd_thick)

    def _toggle_text(self):
        if self._fd_text_btn.isChecked():
            self._fd_pen_btn.setChecked(False)
            self._fd_pen_btn.setStyleSheet(self._fd_tool_style(False))
            self._fd_text_btn.setStyleSheet(self._fd_tool_style(True))
            self._fd_tool = "text"
            self._cancel_btn.setEnabled(True)
            self.free_draw_changed.emit("text", self._fd_color, self._fd_thick)
        else:
            self._fd_text_btn.setStyleSheet(self._fd_tool_style(False))
            self._fd_tool = "none"
            if self._active_type is None:
                self._cancel_btn.setEnabled(False)
            self.free_draw_changed.emit("none", self._fd_color, self._fd_thick)

    def _stop_free_draw_tools(self):
        self._fd_pen_btn.setChecked(False)
        self._fd_text_btn.setChecked(False)
        self._fd_pen_btn.setStyleSheet(self._fd_tool_style(False))
        self._fd_text_btn.setStyleSheet(self._fd_tool_style(False))
        self._fd_tool = "none"

    @staticmethod
    def _fd_thick_style(active: bool) -> str:
        if active:
            return (
                "QPushButton{background:#1c2d3f;border:1px solid #1f6feb;"
                "color:#79c0ff;font-size:13px;font-weight:700;}"
            )
        return (
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#8b949e;font-size:13px;}"
            "QPushButton:hover{background:#30363d;color:#c9d1d9;}"
        )

    @staticmethod
    def _fd_tool_style(active: bool) -> str:
        if active:
            return (
                "QPushButton{background:#1c2d3f;border:1px solid #388bfd;"
                "color:#79c0ff;font-size:13px;font-weight:600;padding:0 6px;}"
            )
        return (
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#8b949e;font-size:13px;padding:0 6px;}"
            "QPushButton:hover{background:#30363d;color:#c9d1d9;}"
        )

    # ---- Builders --------------------------------------------------------

    def _section_header(self, title: str, color: str) -> QLabel:
        lbl = QLabel(f"  {title}")
        lbl.setStyleSheet(
            f"color:{color};font-size:13px;font-weight:700;letter-spacing:1px;"
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
        # Stop any active free draw tool
        self._stop_free_draw_tools()
        # Deselect all others
        all_btns = self._friendly_btns + self._enemy_btns + self._control_btns
        for b in all_btns:
            if b is not btn:
                b.setChecked(False)
                b.setStyleSheet(self._gfx_btn_style(b.property("color"), False))

        gtype = btn.property("gtype")
        aff = btn.property("aff")
        color = btn.property("color")

        if btn.isChecked():
            self._active_type = gtype
            self._active_aff = aff
            btn.setStyleSheet(self._gfx_btn_style(color, True))
            self._cancel_btn.setEnabled(True)
            # draw_graphic carries the affiliation (F/H) and already configures
            # the map's draw mode via setDrawGraphic. Do NOT also emit
            # draw_mode_changed here — set_draw_mode → setDrawMode resets the
            # affiliation back to friendly, turning every enemy graphic blue.
            self.draw_graphic.emit(gtype, aff)
        else:
            self._cancel()

    def _cancel(self):
        # Stop free draw tools first
        if self._fd_tool != "none":
            self._stop_free_draw_tools()
            self.free_draw_changed.emit("none", self._fd_color, self._fd_thick)
        # Stop tactical graphic drawing
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
            return "QPushButton{background:#1c2d3f;border:1px solid #1f6feb;color:#79c0ff;font-size:13px;font-weight:700;}"
        return "QPushButton{background:#21262d;border:1px solid #30363d;color:#8b949e;font-size:13px;}"

    @staticmethod
    def _gfx_btn_style(color: str, active: bool) -> str:
        if active:
            return (
                f"QPushButton{{background:{color}22;border:1px solid {color};"
                f"color:{color};font-size:13px;text-align:left;padding:0 6px;font-weight:600;}}"
            )
        return (
            f"QPushButton{{background:#161b22;border:1px solid #30363d;"
            f"color:#8b949e;font-size:13px;text-align:left;padding:0 6px;}}"
            f"QPushButton:hover{{background:{color}15;border-color:{color};color:{color};}}"
        )
