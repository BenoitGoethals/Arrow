"""ORBAT Panel — hierarchy tree supporting the actual Arrow response format.

GET /hierarchy returns:
{
  "companies": [{"id", "name", "platoons": [{"sections": [{"teams": [{"operators": [...]}]}]}]}],
  "unassigned_operators": [...],
  "online_window_seconds": 90
}
"""
from __future__ import annotations
from typing import Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPushButton, QMenu, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont, QAction


class ORBATPanel(QWidget):
    operator_focus_requested = pyqtSignal(int)
    message_requested        = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._operators: Dict[int, QTreeWidgetItem] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QLabel("ORBAT")
        hdr.setObjectName("panelHeader")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hdr)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(6, 4, 6, 4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter callsign…")
        self._search.textChanged.connect(self._filter)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setRootIsDecorated(False)   # no ▸ arrows on company rows
        self._tree.setIndentation(14)           # compact indent for sub-levels
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.itemClicked.connect(self._on_click)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Column 0 stretches, column 1 (count) is fixed width
        from PyQt6.QtWidgets import QHeaderView
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._tree.setColumnWidth(1, 48)

        layout.addWidget(self._tree)

        self._summary = QLabel("No data")
        self._summary.setObjectName("statusSmall")
        self._summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._summary.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._summary)

    # ---- Public API -------------------------------------------------------

    def load_hierarchy(self, data: dict):
        """Accept the GET /hierarchy response in its actual format."""
        self._tree.clear()
        self._operators.clear()

        # Actual format: {"companies": [...], "unassigned_operators": [...]}
        # Legacy format: {"name": ..., "platoons": [...]}  (single company)
        companies = data.get("companies") or []
        if not companies and "platoons" in data:
            # Legacy single-company fallback
            companies = [data]
        if not companies and "name" in data:
            companies = [data]

        total_online = 0
        total_all    = 0

        for company in companies:
            online_c, total_c = self._count(company)
            total_online += online_c
            total_all    += total_c

            co_item = self._make_item(
                f"◆  {company.get('name', 'COMPANY')}",
                f"{online_c}/{total_c}",
                bold=True, color="#c9d1d9",
            )
            co_item.setExpanded(True)

            for plt in company.get("platoons", []):
                plt_item = self._make_platoon_item(plt)
                co_item.addChild(plt_item)

            self._tree.addTopLevelItem(co_item)

        # Unassigned operators
        unassigned = data.get("unassigned_operators", [])
        if unassigned:
            ua_item = self._make_item("  ◇  Unassigned", f"{len(unassigned)}", color="#8b949e")
            for op in unassigned:
                ua_item.addChild(self._make_operator_item(op))
            ua_item.setExpanded(False)
            self._tree.addTopLevelItem(ua_item)
            total_all += len(unassigned)

        # Collapse everything, then expand only top-level company nodes
        self._tree.collapseAll()
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setExpanded(True)

        self._summary.setText(f"■ {total_online} ONLINE  ·  {total_all} TOTAL")

    def update_operator_presence(self, operator_id: int, online: bool, last_seen: str = ""):
        item = self._operators.get(operator_id)
        if not item:
            return
        item.setText(1, "●" if online else "○")
        item.setForeground(1, QBrush(QColor("#3fb950" if online else "#6e7681")))
        item.setToolTip(0, last_seen)

    def update_from_tracking(self, data: dict):
        op_id = data.get("operator_id")
        if op_id is not None:
            self.update_operator_presence(int(op_id), online=True)

    # ---- Tree builders ---------------------------------------------------

    def _make_platoon_item(self, plt: dict) -> QTreeWidgetItem:
        online, total = self._count_sections(plt.get("sections", []))
        item = self._make_item(f"▸  {plt['name']}", f"{online}/{total}",
                               bold=True, color="#79c0ff")
        for sec in plt.get("sections", []):
            item.addChild(self._make_section_item(sec))
        return item

    def _make_section_item(self, sec: dict) -> QTreeWidgetItem:
        online, total = self._count_teams(sec.get("teams", []))
        item = self._make_item(f"  ▸  {sec['name']}", f"{online}/{total}", color="#8b949e")
        for tm in sec.get("teams", []):
            item.addChild(self._make_team_item(tm))
        return item

    def _make_team_item(self, tm: dict) -> QTreeWidgetItem:
        ops = tm.get("operators", [])
        online = sum(1 for o in ops if o.get("online"))
        item = self._make_item(f"    ▸  {tm['name']}", f"{online}/{len(ops)}", color="#8b949e")
        for op in ops:
            item.addChild(self._make_operator_item(op))
        return item

    def _make_operator_item(self, op: dict) -> QTreeWidgetItem:
        online  = op.get("online", False)
        col_n   = "#c9d1d9" if online else "#6e7681"
        col_led = "#3fb950" if online else "#6e7681"
        rank    = op.get("rank", "")
        label   = f"       {rank}  {op['callsign']}" if rank else f"       {op['callsign']}"
        item    = self._make_item(label, "●" if online else "○", color=col_n)
        item.setForeground(1, QBrush(QColor(col_led)))
        item.setData(0, Qt.ItemDataRole.UserRole, op["id"])
        item.setToolTip(0, op.get("last_seen") or "")
        self._operators[op["id"]] = item
        return item

    @staticmethod
    def _make_item(col0: str, col1: str, bold=False, color="#c9d1d9") -> QTreeWidgetItem:
        item = QTreeWidgetItem([col0, col1])
        item.setForeground(0, QBrush(QColor(color)))
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
        if bold:
            f = QFont(); f.setBold(True); item.setFont(0, f)
        return item

    # ---- Count helpers ---------------------------------------------------

    def _count(self, company: dict) -> tuple[int, int]:
        return self._count_sections(
            [s for p in company.get("platoons", []) for s in p.get("sections", [])]
        )

    def _count_sections(self, sections: list) -> tuple[int, int]:
        return self._count_teams([t for s in sections for t in s.get("teams", [])])

    @staticmethod
    def _count_teams(teams: list) -> tuple[int, int]:
        ops = [o for t in teams for o in t.get("operators", [])]
        return sum(1 for o in ops if o.get("online")), len(ops)

    # ---- Interaction -----------------------------------------------------

    def _filter(self, text: str):
        text = text.lower()
        def visit(item: QTreeWidgetItem) -> bool:
            child_vis = any(visit(item.child(i)) for i in range(item.childCount()))
            visible = text in item.text(0).lower() or child_vis
            item.setHidden(not visible)
            return visible
        for i in range(self._tree.topLevelItemCount()):
            visit(self._tree.topLevelItem(i))

    def _on_click(self, item: QTreeWidgetItem, _col):
        """Single-click: toggle expand/collapse for non-operator rows."""
        op_id = item.data(0, Qt.ItemDataRole.UserRole)
        if op_id is None and item.childCount() > 0:
            item.setExpanded(not item.isExpanded())

    def _on_double_click(self, item: QTreeWidgetItem, _col):
        op_id = item.data(0, Qt.ItemDataRole.UserRole)
        if op_id is not None:
            self.operator_focus_requested.emit(op_id)

    def _context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        op_id = item.data(0, Qt.ItemDataRole.UserRole)
        if op_id is None:
            return
        menu = QMenu(self)
        a1 = QAction("Center on map", menu)
        a2 = QAction("Send message", menu)
        a1.triggered.connect(lambda: self.operator_focus_requested.emit(op_id))
        a2.triggered.connect(lambda: self.message_requested.emit(op_id))
        menu.addAction(a1); menu.addAction(a2)
        menu.exec(self._tree.viewport().mapToGlobal(pos))
