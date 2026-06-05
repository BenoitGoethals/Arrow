"""Strike Package panel — list, select, load map overlay, open planner."""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QFrame, QScrollArea, QGridLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont

STATUS_COLOR = {
    "PLANNING": "#d29922",
    "ACTIVE":   "#3fb950",
    "COMPLETE": "#6e7681",
    "ABORTED":  "#f85149",
}
STATUS_ICON = {
    "PLANNING": "○",
    "ACTIVE":   "●",
    "COMPLETE": "✓",
    "ABORTED":  "✕",
}


class StrikePackagePanel(QWidget):
    package_selected     = pyqtSignal(dict)      # full bundle
    package_cleared      = pyqtSignal()
    overlay_requested    = pyqtSignal(dict)      # load tact objects on map
    planner_requested    = pyqtSignal(dict)      # open planning window
    refresh_requested    = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._packages: list[dict] = []
        self._active_id: int | None = None
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 6, 8, 4)
        hdr.addWidget(QLabel("STRIKE PACKAGES",
            styleSheet="color:#8b949e;font-size:12px;font-weight:700;letter-spacing:2px;"))
        hdr.addStretch()

        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedSize(26, 24)
        refresh_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#8b949e;font-size:15px;border-radius:2px;}"
            "QPushButton:hover{color:#c9d1d9;background:#30363d;}"
        )
        refresh_btn.setToolTip("Reload from server")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        hdr.addWidget(refresh_btn)

        clear_btn = QPushButton("CLEAR")
        clear_btn.setFixedHeight(24); clear_btn.setFixedWidth(52)
        clear_btn.setStyleSheet("font-size:12px;padding:0 4px;")
        clear_btn.clicked.connect(self._clear)
        hdr.addWidget(clear_btn)
        root.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFixedHeight(1)
        root.addWidget(sep)

        # Package list
        self._list = QListWidget()
        self._list.setFont(QFont("Courier New", 13))
        self._list.setAlternatingRowColors(True)
        self._list.setFixedHeight(180)
        self._list.itemClicked.connect(self._on_select)
        root.addWidget(self._list)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine); sep2.setFixedHeight(1)
        root.addWidget(sep2)

        # Detail pane
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._detail_widget = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_widget)
        self._detail_layout.setContentsMargins(8, 8, 8, 8)
        self._detail_layout.setSpacing(6)
        self._detail_layout.addWidget(
            QLabel("Select a strike package",
                   styleSheet="color:#484f58;font-size:13px;font-family:'Courier New',monospace;"),
            alignment=Qt.AlignmentFlag.AlignCenter
        )
        scroll.setWidget(self._detail_widget)
        root.addWidget(scroll, 1)

        # Action buttons
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(6, 6, 6, 6)
        btn_bar.setSpacing(6)

        self._overlay_btn = QPushButton("⊕  LOAD OVERLAY")
        self._overlay_btn.setEnabled(False)
        self._overlay_btn.setStyleSheet(
            "QPushButton{background:#1a3020;border:1px solid #3fb950;color:#3fb950;"
            "font-size:12px;font-weight:700;padding:5px;border-radius:2px;}"
            "QPushButton:hover:!disabled{background:#3fb950;color:#0d1117;}"
            "QPushButton:disabled{color:#30363d;border-color:#21262d;}"
        )
        self._overlay_btn.clicked.connect(self._load_overlay)

        self._planner_btn = QPushButton("◆  OPEN PLANNER")
        self._planner_btn.setEnabled(False)
        self._planner_btn.setStyleSheet(
            "QPushButton{background:#1c2d3f;border:1px solid #1f6feb;color:#79c0ff;"
            "font-size:12px;font-weight:700;padding:5px;border-radius:2px;}"
            "QPushButton:hover:!disabled{background:#1f6feb;color:#fff;}"
            "QPushButton:disabled{color:#30363d;border-color:#21262d;}"
        )
        self._planner_btn.clicked.connect(self._open_planner)

        btn_bar.addWidget(self._overlay_btn)
        btn_bar.addWidget(self._planner_btn)
        root.addLayout(btn_bar)

        self._counter = QLabel("No packages")
        self._counter.setObjectName("statusSmall")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setContentsMargins(6, 4, 6, 4)
        root.addWidget(self._counter)

    # ── Public API ─────────────────────────────────────────────────────────

    def load_packages(self, packages: list[dict]):
        self._packages = packages
        self._list.clear()
        if not packages:
            item = QListWidgetItem("  No strike packages on server")
            item.setForeground(QBrush(QColor("#484f58")))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self._counter.setText("No packages")
            return
        for p in packages:
            status = p.get("status", "PLANNING")
            icon   = STATUS_ICON.get(status, "?")
            color  = STATUS_COLOR.get(status, "#8b949e")
            op_c   = len(p.get("operator_ids", []))
            item   = QListWidgetItem(f"  {icon}  {p.get('name','?')}   [{status}]  ·  {op_c} ops")
            item.setForeground(QBrush(QColor(color)))
            item.setData(Qt.ItemDataRole.UserRole, p)
            self._list.addItem(item)
        n = len(packages)
        self._counter.setText(f"{n} package{'s' if n!=1 else ''}")

    def update_package(self, bundle: dict):
        """Called after fetching the full bundle for a selected package."""
        self._show_detail(bundle)

    # ── Private ────────────────────────────────────────────────────────────

    def _on_select(self, item: QListWidgetItem):
        pkg = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(pkg, dict):
            return
        if pkg.get("id") == self._active_id:
            self._clear(); return
        self._active_id = pkg.get("id")
        self._overlay_btn.setEnabled(True)
        self._planner_btn.setEnabled(True)
        self.package_selected.emit(pkg)

    def _show_detail(self, bundle: dict):
        # Clear ALL previous widgets recursively (nested layouts survive takeAt)
        def _clear_layout(lay):
            while lay.count():
                child = lay.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
                elif child.layout():
                    _clear_layout(child.layout())
        _clear_layout(self._detail_layout)

        name    = bundle.get("name", "?")
        status  = bundle.get("status", "PLANNING")
        color   = STATUS_COLOR.get(status, "#8b949e")
        tdesc   = bundle.get("target_description", "")
        tlat    = bundle.get("target_lat")
        tlon    = bundle.get("target_lon")
        # Bundle endpoint returns expanded lists; list endpoint returns id lists
        ops   = bundle.get("operators")   or bundle.get("operator_ids",         [])
        tobjs = bundle.get("tactical_objects") or bundle.get("tactical_object_ids", [])
        fms   = bundle.get("fire_missions")    or bundle.get("fire_mission_ids",    [])
        assets  = bundle.get("assets", {})

        def _lbl(txt, style="color:#8b949e;font-size:12px;"):
            l = QLabel(txt); l.setStyleSheet(style); return l

        def _val(txt):
            l = QLabel(txt)
            l.setStyleSheet("color:#c9d1d9;font-size:13px;font-family:'Courier New',monospace;")
            l.setWordWrap(True)
            return l

        # Name / status
        name_lbl = QLabel(f"  {STATUS_ICON.get(status,'?')}  {name}")
        name_lbl.setStyleSheet(f"color:{color};font-size:13px;font-weight:700;"
                               f"font-family:'Courier New',monospace;")
        self._detail_layout.addWidget(name_lbl)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#21262d;"); sep.setFixedHeight(1)
        self._detail_layout.addWidget(sep)

        # Target
        if tdesc:
            self._detail_layout.addWidget(_lbl("TARGET"))
            self._detail_layout.addWidget(_val(tdesc))

        if tlat and tlon:
            self._detail_layout.addWidget(_lbl("GRID"))
            from front.utils.mgrs_util import to_mgrs
            self._detail_layout.addWidget(_val(to_mgrs(tlat, tlon)))

        # Stats grid
        grid = QGridLayout(); grid.setSpacing(4)
        stats = [
            ("OPERATORS",  str(len(ops))),
            ("MAP OBJECTS", str(len(tobjs))),
            ("FIRE MSNS",  str(len(fms))),
            ("DRONES",     str(len(assets.get("drones", [])))),
            ("AIR SUPP",   str(len(assets.get("air_support", [])))),
            ("SNIPERS",    str(len(assets.get("sniper_overwatch", [])))),
        ]
        for i, (k, v) in enumerate(stats):
            grid.addWidget(_lbl(k), i // 2, (i % 2) * 2)
            vl = _val(v); vl.setStyleSheet("color:#79c0ff;font-size:13px;font-weight:700;")
            grid.addWidget(vl, i // 2, (i % 2) * 2 + 1)
        self._detail_layout.addLayout(grid)
        self._detail_layout.addStretch()

    def _clear(self):
        self._active_id = None
        self._overlay_btn.setEnabled(False)
        self._planner_btn.setEnabled(False)
        while self._detail_layout.count():
            c = self._detail_layout.takeAt(0)
            if c.widget(): c.widget().deleteLater()
        self._detail_layout.addWidget(
            QLabel("Select a strike package",
                   styleSheet="color:#484f58;font-size:13px;"),
            alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.package_cleared.emit()

    def _load_overlay(self):
        pkg = self._current_pkg()
        if pkg:
            self.overlay_requested.emit(pkg)

    def _open_planner(self):
        pkg = self._current_pkg()
        if pkg:
            self.planner_requested.emit(pkg)

    def _current_pkg(self) -> dict | None:
        for i in range(self._list.count()):
            it = self._list.item(i)
            d = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(d, dict) and d.get("id") == self._active_id:
                return d
        return None
