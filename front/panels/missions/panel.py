"""Missions Panel — list missions, select active, show assigned operators."""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QFrame, QTreeWidget, QTreeWidgetItem, QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont

STATUS_COLOR = {
    "PLANNING": "#d29922",
    "ACTIVE":   "#3fb950",
    "ENDED":    "#6e7681",
}
STATUS_ICON = {
    "PLANNING": "○",
    "ACTIVE":   "●",
    "ENDED":    "✕",
}


class MissionsPanel(QWidget):
    mission_selected = pyqtSignal(object)   # mission dict or None
    mission_cleared  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._missions: list[dict] = []
        self._active_id: int | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar
        top = QHBoxLayout()
        top.setContentsMargins(6, 4, 6, 4)
        top.addWidget(QLabel("MISSIONS", styleSheet="color:#8b949e;font-size:9px;font-weight:700;letter-spacing:2px;"))
        top.addStretch()
        clear_btn = QPushButton("CLEAR")
        clear_btn.setFixedHeight(22)
        clear_btn.setFixedWidth(52)
        clear_btn.setStyleSheet("font-size:9px;padding:0 4px;")
        clear_btn.clicked.connect(self._clear)
        top.addWidget(clear_btn)
        layout.addLayout(top)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFixedHeight(1)
        layout.addWidget(sep)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Mission list
        self._list = QListWidget()
        self._list.setFont(QFont("Courier New", 10))
        self._list.setAlternatingRowColors(True)
        self._list.itemClicked.connect(self._on_select)
        splitter.addWidget(self._list)

        # Mission detail: assigned operators
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)

        self._detail_label = QLabel("Select a mission")
        self._detail_label.setObjectName("panelHeader")
        detail_layout.addWidget(self._detail_label)

        self._ops_tree = QTreeWidget()
        self._ops_tree.setHeaderHidden(True)
        self._ops_tree.setFont(QFont("Courier New", 10))
        self._ops_tree.setAlternatingRowColors(True)
        detail_layout.addWidget(self._ops_tree, 1)

        splitter.addWidget(detail_widget)
        splitter.setSizes([200, 120])
        layout.addWidget(splitter, 1)

        self._counter = QLabel("No missions")
        self._counter.setObjectName("statusSmall")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._counter)

    # ---- Public API -------------------------------------------------------

    def load_missions(self, missions: list[dict]):
        self._missions = missions
        self._list.clear()

        if not missions:
            placeholder = QListWidgetItem("  No missions on server")
            placeholder.setForeground(QBrush(QColor("#484f58")))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)   # not selectable
            self._list.addItem(placeholder)
            self._counter.setText("No missions")
            return

        for m in missions:
            status = m.get("status", "PLANNING")
            icon   = STATUS_ICON.get(status, "?")
            color  = STATUS_COLOR.get(status, "#8b949e")
            item   = QListWidgetItem(
                f"{icon}  {m.get('name', '?')}  [{status}]"
            )
            item.setForeground(QBrush(QColor(color)))
            item.setData(Qt.ItemDataRole.UserRole, m)
            if m.get("id") == self._active_id:
                font = QFont("Courier New", 10); font.setBold(True)
                item.setFont(font)
            self._list.addItem(item)
        self._counter.setText(f"{len(missions)} mission{'s' if len(missions)!=1 else ''}")

    def load_operators(self, operators: list[dict]):
        self._ops_tree.clear()
        for op in operators:
            online = op.get("status", "") == "ONLINE"
            led    = "●" if online else "○"
            color  = "#3fb950" if online else "#6e7681"
            item   = QTreeWidgetItem([f"  {led}  {op.get('callsign','?')}  {op.get('rank','')}"])
            item.setForeground(0, QBrush(QColor(color)))
            self._ops_tree.addTopLevelItem(item)

    def set_active_mission(self, mission: dict | None):
        self._active_id = mission.get("id") if mission else None
        if mission:
            self._detail_label.setText(f"  {mission.get('name','')}  —  ASSIGNED")
        else:
            self._detail_label.setText("Select a mission")
            self._ops_tree.clear()

    # ---- Private ----------------------------------------------------------

    def _on_select(self, item: QListWidgetItem):
        mission = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(mission, dict):
            return   # placeholder / non-selectable item
        if mission.get("id") == self._active_id:
            self._clear()
            return
        self.set_active_mission(mission)
        self.mission_selected.emit(mission)

    def _clear(self):
        self._active_id = None
        self._detail_label.setText("Select a mission")
        self._ops_tree.clear()
        for i in range(self._list.count()):
            it = self._list.item(i)
            font = QFont("Courier New", 10); font.setBold(False)
            it.setFont(font)
        self.mission_cleared.emit()
