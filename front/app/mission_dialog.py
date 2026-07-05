"""Arrow Front — mandatory mission selection.

Shown at startup for ADMINs (the only role that may pick/create a mission).
Non-admins are auto-locked to their assigned mission by the launcher and never
see this dialog. The chosen id is exposed as ``selected_id`` after ``exec()``.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

#: Must match backend/classification.py.
CLASS_NAMES = ["UNCLASSIFIED", "RESTRICTED", "CONFIDENTIAL", "SECRET", "TOP SECRET"]
CLASS_COLORS = ["#16a34a", "#0e7490", "#2563eb", "#dc2626", "#ea580c"]


def class_name(level: int | None) -> str:
    return CLASS_NAMES[max(0, min(4, int(level or 0)))]


class MissionDialog(QDialog):
    """ADMIN mission picker / creator. ``selected_id`` is set on accept."""

    def __init__(self, parent=None, *, client, clearance: int = 0):
        super().__init__(parent)
        self._client = client
        self._clearance = max(0, min(4, int(clearance or 0)))
        self.selected_id: int | None = None

        self.setWindowTitle("Arrow Front — Select Mission")
        self.setMinimumSize(480, 540)
        self.setModal(True)
        self._build()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet("background:#161b22;border-bottom:1px solid #30363d;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 18, 0)
        title = QLabel("🎯  SELECT MISSION")
        title.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        title.setStyleSheet("color:#3fb950;letter-spacing:2px;")
        hl.addWidget(title)
        root.addWidget(hdr)

        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(10)
        note = QLabel("You must be in a mission to use Arrow. Pick one or create a new one.")
        note.setStyleSheet("color:#8b949e;font-size:11px;")
        note.setWordWrap(True)
        body.addWidget(note)

        self._list = QListWidget()
        self._list.setFont(QFont("Courier New", 12))
        self._list.itemDoubleClicked.connect(lambda _i: self._enter_selected())
        body.addWidget(self._list, 1)

        enter_btn = QPushButton("Enter selected mission")
        enter_btn.setObjectName("primaryButton")
        enter_btn.clicked.connect(self._enter_selected)
        body.addWidget(enter_btn)

        # ── Create a new mission (levels ≤ the admin's clearance) ─────────
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#21262d;")
        body.addWidget(line)

        crow = QHBoxLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("New mission name…")
        crow.addWidget(self._name, 1)
        self._class = QComboBox()
        for lvl in range(self._clearance + 1):
            self._class.addItem(CLASS_NAMES[lvl], lvl)
        crow.addWidget(self._class)
        create_btn = QPushButton("Create")
        create_btn.clicked.connect(self._create)
        crow.addWidget(create_btn)
        body.addLayout(crow)

        self._err = QLabel("")
        self._err.setStyleSheet("color:#f85149;font-size:10px;")
        body.addWidget(self._err)

        root.addLayout(body)

    # ── Data ──────────────────────────────────────────────────────────────
    def _load(self):
        try:
            missions = self._client.missions()
        except Exception as exc:
            self._err.setText(f"Could not load missions: {exc}")
            return
        self._list.clear()
        active = [m for m in missions if m.get("status") != "ENDED"]
        for m in active:
            lvl = int(m.get("classification", 0) or 0)
            item = QListWidgetItem(f"{m.get('name', '?')}   [{m.get('status', '')}]   · {class_name(lvl)}")
            item.setData(Qt.ItemDataRole.UserRole, m.get("id"))
            self._list.addItem(item)
        if active:
            self._list.setCurrentRow(0)

    def _enter_selected(self):
        item = self._list.currentItem()
        if item is None:
            self._err.setText("Select a mission first, or create one below.")
            return
        self.selected_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.accept()

    def _create(self):
        name = self._name.text().strip()
        if not name:
            self._err.setText("Enter a mission name.")
            return
        try:
            m = self._client.create_mission(name, "", int(self._class.currentData() or 0))
        except Exception as exc:
            self._err.setText(f"Create failed: {exc}")
            return
        self.selected_id = int(m["id"])
        self.accept()
