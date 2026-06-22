"""Route planning panel — draw routes, import GPX, manage routes."""

from __future__ import annotations
import math
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QPushButton,
    QLabel,
    QFrame,
    QDialog,
    QLineEdit,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QAbstractItemView,
    QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

# ── Constants ──────────────────────────────────────────────────────────────────

WP_TYPES = ["START", "WP", "IP", "RV", "CP", "RP", "HOLD", "END"]

ROUTE_COLORS = ["#3fb950", "#79c0ff", "#d29922", "#f85149", "#d2a8ff", "#ff9e64"]
_COLOR_IDX = 0


def _next_color() -> str:
    global _COLOR_IDX
    c = ROUTE_COLORS[_COLOR_IDX % len(ROUTE_COLORS)]
    _COLOR_IDX += 1
    return c


def _haversine(a: dict, b: dict) -> float:
    R = 6_371_000
    dlat = math.radians(b["lat"] - a["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    la1, la2 = math.radians(a["lat"]), math.radians(b["lat"])
    x = (
        math.sin(dlat / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(max(0.0, x)))


def _route_distance(waypoints: list) -> float:
    total = 0.0
    for i in range(len(waypoints) - 1):
        total += _haversine(waypoints[i], waypoints[i + 1])
    return total


def _fmt_dist(m: float) -> str:
    if m >= 10_000:
        return f"{m / 1000:.1f} km"
    if m >= 1_000:
        return f"{m / 1000:.2f} km"
    return f"{m:.0f} m"


def _fmt_time(secs: float) -> str:
    if secs < 60:
        return f"{secs:.0f}s"
    m = int(secs // 60)
    if m < 60:
        return f"{m}m {int(secs % 60):02d}s"
    return f"{m // 60}h {m % 60:02d}m"


# ── GPX parser ─────────────────────────────────────────────────────────────────


def parse_gpx(text: str) -> list[dict]:
    """Return [{lat, lon, label, type, notes}] from a GPX string."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    # Detect namespace
    ns_uri = ""
    if root.tag.startswith("{"):
        ns_uri = root.tag.split("}")[0][1:]

    def _tag(name: str) -> str:
        return f"{{{ns_uri}}}{name}" if ns_uri else name

    def _find(el, name: str):
        return el.find(_tag(name))

    def _text(el, name: str, default: str = "") -> str:
        child = _find(el, name)
        return (child.text or "").strip() if child is not None else default

    def _guess_type(label: str) -> str:
        u = label.upper()
        if any(k in u for k in ("START", "BEGIN", "RP ", "RP-")):
            return "START"
        if any(k in u for k in ("END", "OBJ", "TARGET")):
            return "END"
        if "IP" in u:
            return "IP"
        if "RV" in u:
            return "RV"
        if "CP" in u:
            return "CP"
        if "RP" in u:
            return "RP"
        if "HOLD" in u:
            return "HOLD"
        return "WP"

    wps: list[dict] = []

    # Named waypoints <wpt>
    for wpt in root.findall(_tag("wpt")):
        lat = float(wpt.get("lat", 0))
        lon = float(wpt.get("lon", 0))
        if not lat and not lon:
            continue
        label = _text(wpt, "name")
        notes = _text(wpt, "desc") or _text(wpt, "cmt")
        wps.append(
            {
                "lat": lat,
                "lon": lon,
                "label": label,
                "type": _guess_type(label),
                "notes": notes,
            }
        )

    # Track points <trk>/<trkseg>/<trkpt> — only when no named wpts
    if not wps:
        for trk in root.findall(_tag("trk")):
            for seg in trk.findall(_tag("trkseg")):
                for i, tpt in enumerate(seg.findall(_tag("trkpt"))):
                    lat = float(tpt.get("lat", 0))
                    lon = float(tpt.get("lon", 0))
                    if not lat and not lon:
                        continue
                    label = _text(tpt, "name") or f"WP{i + 1}"
                    wps.append(
                        {
                            "lat": lat,
                            "lon": lon,
                            "label": label,
                            "type": "WP",
                            "notes": "",
                        }
                    )

    if wps:
        wps[0]["type"] = "START"
        wps[-1]["type"] = "END"

    return wps


# ── Route properties dialog ────────────────────────────────────────────────────

_DLG_STYLE = """
QDialog, QWidget      { background:#0d1117; color:#c9d1d9; }
QLabel                { color:#c9d1d9; font-family:'Courier New',monospace; font-size:13px; }
QLineEdit, QDoubleSpinBox {
    background:#161b22; border:1px solid #30363d; color:#c9d1d9;
    padding:4px 8px; border-radius:2px;
    font-family:'Courier New',monospace; font-size:13px;
}
QLineEdit:focus, QDoubleSpinBox:focus { border-color:#388bfd; }
QTableWidget {
    background:#161b22; border:1px solid #30363d;
    gridline-color:#21262d; font-family:'Courier New',monospace; font-size:13px;
}
QHeaderView::section {
    background:#0d1117; border:1px solid #21262d;
    color:#8b949e; font-size:12px; font-weight:700; letter-spacing:1px; padding:3px;
}
QComboBox {
    background:#161b22; border:1px solid #30363d; color:#c9d1d9;
    padding:2px 6px; border-radius:2px; font-family:'Courier New',monospace;
}
QComboBox QAbstractItemView {
    background:#161b22; color:#c9d1d9; selection-background-color:#1c2d3f;
}
QPushButton {
    background:#21262d; border:1px solid #30363d; color:#c9d1d9;
    padding:5px 12px; border-radius:2px;
    font-family:'Courier New',monospace; font-size:13px;
}
QPushButton:hover { background:#30363d; }
"""


class RoutePropertiesDialog(QDialog):
    """Edit name, color, speed, and waypoint types/labels for a route."""

    def __init__(self, route: dict, parent=None):
        super().__init__(parent)
        self._route = dict(route)
        self._color = route.get("color", ROUTE_COLORS[0])
        self.setWindowTitle("Route Properties")
        self.setMinimumWidth(580)
        self.setMinimumHeight(440)
        self.setStyleSheet(_DLG_STYLE)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(14, 14, 14, 14)

        # ── Name / Color ──────────────────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("NAME"))
        self._name_edit = QLineEdit(self._route.get("name", "Route"))
        self._name_edit.setPlaceholderText("Route name…")
        row1.addWidget(self._name_edit, 1)

        row1.addWidget(QLabel("  COLOR"))
        self._color_btn = QPushButton("■")
        self._color_btn.setFixedWidth(36)
        self._color_btn.setStyleSheet(
            f"color:{self._color};font-size:18px;background:#21262d;"
            "border:1px solid #30363d;border-radius:2px;"
        )
        self._color_btn.clicked.connect(self._pick_color)
        row1.addWidget(self._color_btn)
        lay.addLayout(row1)

        # ── Speed ─────────────────────────────────────────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("SPEED"))
        self._speed = QDoubleSpinBox()
        self._speed.setRange(1, 500)
        self._speed.setSuffix(" km/h")
        self._speed.setValue(self._route.get("speed_kmh", 30.0))
        self._speed.setFixedWidth(130)
        row2.addWidget(self._speed)
        row2.addStretch()
        lay.addLayout(row2)

        # ── Waypoints table ───────────────────────────────────────────────────
        sep = QLabel("WAYPOINTS")
        sep.setStyleSheet(
            "color:#8b949e;font-size:12px;font-weight:700;"
            "letter-spacing:1.5px;font-family:'Courier New',monospace;"
        )
        lay.addWidget(sep)

        self._tbl = QTableWidget()
        self._tbl.setColumnCount(4)
        self._tbl.setHorizontalHeaderLabels(["TYPE", "LABEL", "NOTES", "COORDS"])
        hdr = self._tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._tbl.verticalHeader().hide()
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tbl.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self._tbl.setMinimumHeight(180)

        wps = self._route.get("waypoints", [])
        self._tbl.setRowCount(len(wps))
        for i, wp in enumerate(wps):
            cmb = QComboBox()
            cmb.addItems(WP_TYPES)
            cmb.setCurrentText(wp.get("type", "WP"))
            self._tbl.setCellWidget(i, 0, cmb)
            self._tbl.setItem(i, 1, QTableWidgetItem(wp.get("label", "")))
            self._tbl.setItem(i, 2, QTableWidgetItem(wp.get("notes", "")))
            coords_item = QTableWidgetItem(f"{wp['lat']:.5f}, {wp['lon']:.5f}")
            coords_item.setFlags(
                Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            )
            coords_item.setForeground(QColor("#6e7681"))
            self._tbl.setItem(i, 3, coords_item)

        lay.addWidget(self._tbl, 1)

        # ── Stats preview ─────────────────────────────────────────────────────
        self._stats_lbl = QLabel()
        self._stats_lbl.setStyleSheet(
            "color:#6e7681;font-size:12px;font-family:'Courier New',monospace;"
        )
        self._update_stats(wps, self._speed.value())
        self._speed.valueChanged.connect(
            lambda v: self._update_stats(self._route.get("waypoints", []), v)
        )
        lay.addWidget(self._stats_lbl)

        # ── Buttons ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = btns.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Save Route")
        ok.setStyleSheet(
            "background:#1f6feb;border:1px solid #388bfd;color:#fff;"
            "padding:6px 18px;border-radius:2px;font-family:'Courier New',monospace;"
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _pick_color(self):
        menu = QMenu(self)
        for c in ROUTE_COLORS:
            act = menu.addAction(f"■   {c}")
            act.setData(c)
            act.triggered.connect(lambda checked, col=c: self._set_color(col))
        menu.exec(self._color_btn.mapToGlobal(self._color_btn.rect().bottomLeft()))

    def _set_color(self, color: str):
        self._color = color
        self._color_btn.setStyleSheet(
            f"color:{color};font-size:18px;background:#21262d;"
            "border:1px solid #30363d;border-radius:2px;"
        )

    def _update_stats(self, wps: list, speed: float):
        if len(wps) < 2:
            self._stats_lbl.setText(
                f"{len(wps)} waypoint(s) — draw more points for distance"
            )
            return
        d = _route_distance(wps)
        spd = speed or 30.0
        self._stats_lbl.setText(
            f"📏 {_fmt_dist(d)}  ·  ⏱ {_fmt_time(d / 1000 / spd * 3600)} @ {spd:.0f} km/h  "
            f"·  {len(wps)} waypoints"
        )

    def get_result(self) -> dict:
        wps = []
        orig_wps = self._route.get("waypoints", [])
        for i in range(self._tbl.rowCount()):
            orig = orig_wps[i] if i < len(orig_wps) else {}
            cmb = self._tbl.cellWidget(i, 0)
            label_item = self._tbl.item(i, 1)
            notes_item = self._tbl.item(i, 2)
            wps.append(
                {
                    **orig,
                    "type": cmb.currentText() if cmb else orig.get("type", "WP"),
                    "label": label_item.text() if label_item else orig.get("label", ""),
                    "notes": notes_item.text() if notes_item else orig.get("notes", ""),
                }
            )
        return {
            **self._route,
            "name": self._name_edit.text().strip() or "Route",
            "color": self._color,
            "speed_kmh": self._speed.value(),
            "waypoints": wps,
        }


# ── Route card ─────────────────────────────────────────────────────────────────

_CARD_STYLE = """
QFrame {
    background:#161b22;
    border:1px solid #30363d;
    border-radius:3px;
}
QFrame:hover { border-color:#388bfd; }
QPushButton {
    background:#21262d; border:1px solid #30363d;
    color:#8b949e; border-radius:2px;
    font-size:14px;
}
QPushButton:hover { background:#30363d; color:#e6edf3; }
"""


class _RouteCard(QFrame):
    delete_requested = pyqtSignal(str)
    visibility_toggled = pyqtSignal(str, bool)
    focus_requested = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    navigate_requested = pyqtSignal(str)

    def __init__(self, route: dict, parent=None):
        super().__init__(parent)
        self._route = route
        self._visible = True
        self.setStyleSheet(_CARD_STYLE)
        self._build()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)

        # ── Top row ───────────────────────────────────────────────────────────
        h = QHBoxLayout()
        h.setSpacing(4)

        dot = QLabel("■")
        dot.setStyleSheet(
            f"color:{self._route.get('color', '#3fb950')};"
            "font-size:15px; background:none; border:none;"
        )
        dot.setFixedWidth(16)
        h.addWidget(dot)

        name = QLabel(self._route.get("name", "Route"))
        name.setStyleSheet(
            "color:#e6edf3;font-weight:700;font-size:13px;"
            "font-family:'Courier New',monospace; background:none; border:none;"
        )
        h.addWidget(name, 1)

        for icon, tip, color, cb in [
            (
                "▶",
                "Navigate route",
                "#3fb950",
                lambda: self.navigate_requested.emit(self._route["id"]),
            ),
            (
                "◉",
                "Focus on map",
                "#8b949e",
                lambda: self.focus_requested.emit(self._route["id"]),
            ),
            ("👁", "Toggle visibility", "#8b949e", self._toggle_vis),
            (
                "✏",
                "Edit route",
                "#8b949e",
                lambda: self.edit_requested.emit(self._route["id"]),
            ),
            (
                "🗑",
                "Delete route",
                "#f85149",
                lambda: self.delete_requested.emit(self._route["id"]),
            ),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(24, 24)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                f"background:#21262d;border:1px solid #30363d;"
                f"color:{color};border-radius:2px;"
            )
            btn.clicked.connect(cb)
            if icon == "👁":
                self._eye_btn = btn
            h.addWidget(btn)

        v.addLayout(h)

        # ── Stats ─────────────────────────────────────────────────────────────
        wps = self._route.get("waypoints", [])
        if len(wps) >= 2:
            d = _route_distance(wps)
            spd = self._route.get("speed_kmh", 30) or 30
            txt = (
                f"📏 {_fmt_dist(d)}  ·  "
                f"⏱ {_fmt_time(d / 1000 / spd * 3600)} @ {spd:.0f} km/h  ·  "
                f"{len(wps)} wpts"
            )
        elif wps:
            txt = f"{len(wps)} waypoint — add more points"
        else:
            txt = "No waypoints"
        stats = QLabel(txt)
        stats.setStyleSheet(
            "color:#6e7681;font-size:12px;font-family:'Courier New',monospace;"
            "background:none;border:none;"
        )
        v.addWidget(stats)

        # ── WP type summary ───────────────────────────────────────────────────
        if wps:
            types = " → ".join(w.get("type", "WP") for w in wps[:12])
            if len(wps) > 12:
                types += f" (+{len(wps) - 12})"
            tp = QLabel(types)
            tp.setStyleSheet(
                "color:#484f58;font-size:11px;font-family:'Courier New',monospace;"
                "background:none;border:none;"
            )
            v.addWidget(tp)

    def _toggle_vis(self):
        self._visible = not self._visible
        c = "#e6edf3" if self._visible else "#484f58"
        self._eye_btn.setStyleSheet(
            f"background:#21262d;border:1px solid #30363d;color:{c};border-radius:2px;"
        )
        self.visibility_toggled.emit(self._route["id"], self._visible)


# ── Routes panel ───────────────────────────────────────────────────────────────

_PANEL_BTN = (
    "font-family:'Courier New',monospace;font-size:12px;font-weight:700;"
    "padding:4px 10px;border-radius:2px;letter-spacing:.5px;"
)


class RoutesPanel(QWidget):
    """Route management panel — draw, import, list, edit, delete routes."""

    route_draw_requested = pyqtSignal(str, str)  # route_id, color
    route_draw_cancelled = pyqtSignal()
    route_deleted = pyqtSignal(str)
    route_visibility_changed = pyqtSignal(str, bool)
    route_focus_requested = pyqtSignal(str)
    route_edit_done = pyqtSignal(dict)  # updated route dict
    route_add_requested = pyqtSignal(dict)  # new route (GPX or draw finish)
    navigate_requested = pyqtSignal(str)  # route_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._routes: dict[str, dict] = {}
        self._cards: dict[str, _RouteCard] = {}
        self._drawing_id: Optional[str] = None
        self._build()

    # ── Build ──────────────────────────────────────────────────────────────────
    def _build(self):
        self.setStyleSheet("background:#0d1117;")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Header bar
        hdr = QFrame()
        hdr.setStyleSheet("background:#0d1117;border-bottom:1px solid #21262d;")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(8, 6, 8, 6)
        hh.setSpacing(4)

        title = QLabel("ROUTES & NAVIGATION")
        title.setStyleSheet(
            "color:#8b949e;font-size:12px;font-weight:700;"
            "letter-spacing:2px;font-family:'Courier New',monospace;"
        )
        hh.addWidget(title)
        hh.addStretch()

        self._new_btn = QPushButton("+ ROUTE")
        self._new_btn.setStyleSheet(
            "background:#1c2d3f;border:1px solid #1f6feb;color:#79c0ff;" + _PANEL_BTN
        )
        self._new_btn.clicked.connect(self._start_new_route)
        hh.addWidget(self._new_btn)

        gpx_btn = QPushButton("↑ GPX")
        gpx_btn.setStyleSheet(
            "background:#21262d;border:1px solid #30363d;color:#8b949e;" + _PANEL_BTN
        )
        gpx_btn.setToolTip("Import GPX file")
        gpx_btn.clicked.connect(self._import_gpx)
        hh.addWidget(gpx_btn)

        v.addWidget(hdr)

        # Drawing banner (hidden by default)
        self._draw_row = QFrame()
        self._draw_row.setStyleSheet(
            "background:#1c2d3f;border-bottom:1px solid #388bfd;"
        )
        dr = QHBoxLayout(self._draw_row)
        dr.setContentsMargins(8, 5, 8, 5)
        dr.setSpacing(6)
        draw_lbl = QLabel(
            "🗺  Click map to add waypoints  ·  Right-click or Dbl-click to finish  ·  ESC cancels"
        )
        draw_lbl.setStyleSheet(
            "color:#79c0ff;font-size:12px;font-weight:700;font-family:'Courier New',monospace;"
        )
        draw_lbl.setWordWrap(True)
        dr.addWidget(draw_lbl, 1)
        cancel_btn = QPushButton("✕ CANCEL")
        cancel_btn.setStyleSheet(
            "background:#3d1c1c;border:1px solid #f85149;color:#f85149;"
            "font-size:12px;padding:3px 8px;border-radius:2px;"
            "font-family:'Courier New',monospace;"
        )
        cancel_btn.clicked.connect(self._cancel_draw)
        dr.addWidget(cancel_btn)
        self._draw_row.hide()
        v.addWidget(self._draw_row)

        # Scroll area for route cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:#0d1117;}"
            "QScrollBar:vertical{width:6px;background:#0d1117;}"
            "QScrollBar::handle:vertical{background:#30363d;border-radius:3px;}"
        )
        content = QWidget()
        content.setStyleSheet("background:#0d1117;")
        self._list_lay = QVBoxLayout(content)
        self._list_lay.setContentsMargins(6, 6, 6, 6)
        self._list_lay.setSpacing(4)

        self._empty_lbl = QLabel(
            "No routes yet.\n\nClick  + ROUTE  to draw on map\nor  ↑ GPX  to import a file."
        )
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            "color:#484f58;font-size:13px;font-family:'Courier New',monospace;"
        )
        self._empty_lbl.setWordWrap(True)
        self._list_lay.addWidget(self._empty_lbl)
        self._list_lay.addStretch()

        scroll.setWidget(content)
        v.addWidget(scroll, 1)

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_route(self, route: dict):
        """Insert or replace a route card in the list."""
        rid = route["id"]
        self._routes[rid] = route
        if rid in self._cards:
            old = self._cards.pop(rid)
            idx = self._list_lay.indexOf(old)
            self._list_lay.removeWidget(old)
            old.deleteLater()
        else:
            idx = 0
        card = _RouteCard(route, self)
        card.delete_requested.connect(self._on_delete)
        card.visibility_toggled.connect(self.route_visibility_changed)
        card.focus_requested.connect(self.route_focus_requested)
        card.edit_requested.connect(self._on_edit)
        card.navigate_requested.connect(self.navigate_requested)
        self._cards[rid] = card
        # Insert before the stretch (last item)
        insert_at = max(0, idx) if idx >= 0 else self._list_lay.count() - 1
        self._list_lay.insertWidget(insert_at, card)
        self._empty_lbl.hide()

    def remove_route(self, route_id: str):
        if route_id in self._cards:
            w = self._cards.pop(route_id)
            self._list_lay.removeWidget(w)
            w.deleteLater()
        self._routes.pop(route_id, None)
        if not self._routes:
            self._empty_lbl.show()

    def get_routes(self) -> list[dict]:
        return list(self._routes.values())

    def load_routes(self, routes: list[dict]):
        """Bulk-load saved routes (called on startup)."""
        for r in routes:
            self.add_route(r)

    def set_drawing(self, active: bool):
        self._draw_row.setVisible(active)
        self._new_btn.setEnabled(not active)

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _start_new_route(self):
        rid = str(uuid.uuid4())
        color = _next_color()
        self._drawing_id = rid
        self.set_drawing(True)
        self.route_draw_requested.emit(rid, color)

    def _cancel_draw(self):
        self._drawing_id = None
        self.set_drawing(False)
        self.route_draw_cancelled.emit()

    def on_draw_cancelled_from_map(self):
        """Called when ESC / cancel comes from the map side."""
        self._drawing_id = None
        self.set_drawing(False)

    # ── GPX import ─────────────────────────────────────────────────────────────

    def _import_gpx(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import GPX File", "", "GPX Files (*.gpx);;All Files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "GPX Error", f"Could not read file:\n{exc}")
            return

        wps = parse_gpx(text)
        if not wps:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self, "GPX Error", "No waypoints or track points found in the GPX file."
            )
            return

        route = {
            "id": str(uuid.uuid4()),
            "name": Path(path).stem,
            "color": _next_color(),
            "speed_kmh": 30.0,
            "waypoints": wps,
            "visible": True,
        }
        dlg = RoutePropertiesDialog(route, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            route = dlg.get_result()
            route["visible"] = True
            self.add_route(route)
            self.route_add_requested.emit(route)

    # ── Slot handlers ──────────────────────────────────────────────────────────

    def _on_delete(self, route_id: str):
        self.remove_route(route_id)
        self.route_deleted.emit(route_id)

    def _on_edit(self, route_id: str):
        route = self._routes.get(route_id)
        if not route:
            return
        dlg = RoutePropertiesDialog(route, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_result()
            self.add_route(updated)
            self.route_edit_done.emit(updated)
