"""Missions Panel — read-only selector. Missions are managed via the Arrow web dashboard."""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QFrame, QTreeWidget, QTreeWidgetItem, QSplitter,
    QMessageBox,
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
    mission_selected     = pyqtSignal(object)  # mission dict
    mission_cleared      = pyqtSignal()
    refresh_requested    = pyqtSignal()
    delete_all_requested = pyqtSignal()        # confirmed — delete all missions

    def __init__(self, parent=None):
        super().__init__(parent)
        self._missions: list[dict] = []
        self._active_id: int | None = None
        self._build_ui()

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        top = QHBoxLayout()
        top.setContentsMargins(8, 6, 8, 4)
        top.addWidget(QLabel("MISSIONS",
            styleSheet="color:#8b949e;font-size:9px;font-weight:700;letter-spacing:2px;"))
        top.addStretch()

        refresh_btn = QPushButton("⟳")
        refresh_btn.setToolTip("Reload missions from server")
        refresh_btn.setFixedSize(26, 24)
        refresh_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#8b949e;font-size:13px;border-radius:2px;}"
            "QPushButton:hover{background:#30363d;color:#c9d1d9;}"
        )
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        top.addWidget(refresh_btn)

        clear_btn = QPushButton("CLEAR")
        clear_btn.setFixedHeight(24)
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

        # Detail pane — assigned operators
        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)

        self._detail_header = QLabel("  SELECT A MISSION")
        self._detail_header.setObjectName("panelHeader")
        dl.addWidget(self._detail_header)

        self._ops_tree = QTreeWidget()
        self._ops_tree.setHeaderHidden(True)
        self._ops_tree.setFont(QFont("Courier New", 10))
        self._ops_tree.setAlternatingRowColors(True)
        dl.addWidget(self._ops_tree, 1)

        splitter.addWidget(detail)
        splitter.setSizes([280, 160])
        layout.addWidget(splitter, 1)

        self._counter = QLabel("No missions")
        self._counter.setObjectName("statusSmall")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._counter)

    # ---- Public API -------------------------------------------------------

    def load_missions(self, missions: list[dict], role: str = "OPERATOR"):
        self._missions = missions
        self._list.clear()

        if not missions:
            def _placeholder(text: str, color: str = "#484f58", size: int = 10):
                it = QListWidgetItem(text)
                it.setForeground(QBrush(QColor(color)))
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                it.setFont(QFont("Courier New", size))
                self._list.addItem(it)

            if role in ("ADMIN", "BATTLE_CAPTAIN"):
                _placeholder("  No missions on server")
                _placeholder("  Create missions in the Arrow web dashboard", "#30363d", 9)
            else:
                _placeholder("  No mission assigned to your account", "#d29922")
                _placeholder(f"  Role: {role}", "#30363d", 9)
                _placeholder("  Ask BATTLE_CAPTAIN to assign you", "#30363d", 9)
                _placeholder("  or log in as BATTLE_CAPTAIN to see all", "#30363d", 9)

            self._counter.setText(f"Role: {role}  ·  0 missions visible")
            return

        for m in missions:
            status = m.get("status", "PLANNING")
            icon   = STATUS_ICON.get(status, "?")
            color  = STATUS_COLOR.get(status, "#8b949e")
            item   = QListWidgetItem(
                f"  {icon}  {m.get('name', '?')}   [{status}]"
            )
            item.setForeground(QBrush(QColor(color)))
            item.setData(Qt.ItemDataRole.UserRole, m)
            if m.get("id") == self._active_id:
                f = QFont("Courier New", 10); f.setBold(True)
                item.setFont(f)
            self._list.addItem(item)

        n = len(missions)
        self._counter.setText(f"{n} mission{'s' if n != 1 else ''}")

    def load_operators(self, operators: list[dict]):
        self._ops_tree.clear()
        for op in operators:
            online = op.get("status", "") == "ONLINE"
            color  = "#3fb950" if online else "#6e7681"
            led    = "●" if online else "○"
            item   = QTreeWidgetItem(
                [f"  {led}  {op.get('callsign','?')}  {op.get('rank','')}"]
            )
            item.setForeground(0, QBrush(QColor(color)))
            self._ops_tree.addTopLevelItem(item)

    def set_active_mission(self, mission: dict | None):
        self._active_id = mission.get("id") if mission else None
        if mission:
            status = mission.get("status", "PLANNING")
            color  = STATUS_COLOR.get(status, "#8b949e")
            self._detail_header.setText(
                f"  {STATUS_ICON.get(status,'?')}  {mission.get('name','')}  "
                f"<span style='color:{color}'>[{status}]</span>"
            )
            self._detail_header.setTextFormat(Qt.TextFormat.RichText)
        else:
            self._detail_header.setText("  SELECT A MISSION")
            self._ops_tree.clear()

    # ---- Private ----------------------------------------------------------

    def _on_select(self, item: QListWidgetItem):
        mission = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(mission, dict):
            return
        if mission.get("id") == self._active_id:
            self._clear()
            return
        f_bold = QFont("Courier New", 10); f_bold.setBold(True)
        f_norm = QFont("Courier New", 10); f_norm.setBold(False)
        for i in range(self._list.count()):
            it = self._list.item(i)
            it.setFont(f_bold if it is item else f_norm)
        self.set_active_mission(mission)
        self.mission_selected.emit(mission)

    def _confirm_delete_all(self):
        n = len(self._missions)
        if n == 0:
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete All Missions")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            f"<b style='color:#f85149'>Delete ALL {n} mission{'s' if n!=1 else ''}?</b>"
            f"<br><br>This will permanently remove every mission from the server.<br>"
            f"This action <b>cannot be undone</b>.<br><br>"
            f"<span style='color:#8b949e;font-size:10px'>Requires ADMIN role.</span>"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        yes_btn = msg.button(QMessageBox.StandardButton.Yes)
        yes_btn.setText(f"  DELETE ALL {n}  ")
        yes_btn.setStyleSheet(
            "QPushButton{background:#da3633;border:1px solid #f85149;"
            "color:#fff;font-weight:700;padding:6px 12px;}"
            "QPushButton:hover{background:#f85149;}"
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.delete_all_requested.emit()

    def _clear(self):
        self._active_id = None
        self._list.clearSelection()
        self._list.setCurrentItem(None)
        f = QFont("Courier New", 10); f.setBold(False)
        for i in range(self._list.count()):
            self._list.item(i).setFont(f)
        self.set_active_mission(None)
        self.mission_cleared.emit()
