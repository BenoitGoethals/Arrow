"""OPORD Panel — list OPORDs, open viewer/editor."""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont

STATUS_COLOR = {"DRAFT": "#d29922", "PUBLISHED": "#3fb950"}
STATUS_ICON  = {"DRAFT": "○",       "PUBLISHED": "●"}


class OpordPanel(QWidget):
    open_requested    = pyqtSignal(dict)   # open viewer for existing OPORD
    create_requested  = pyqtSignal()       # open editor for new OPORD
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opords: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 6, 8, 4)
        hdr.addWidget(QLabel("OPERATION ORDERS",
            styleSheet="color:#8b949e;font-size:9px;font-weight:700;letter-spacing:2px;"))
        hdr.addStretch()

        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedSize(26, 24)
        refresh_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#8b949e;font-size:13px;border-radius:2px;}"
            "QPushButton:hover{color:#c9d1d9;background:#30363d;}")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        hdr.addWidget(refresh_btn)

        new_btn = QPushButton("+ NEW")
        new_btn.setFixedHeight(24)
        new_btn.setFixedWidth(56)
        new_btn.setStyleSheet(
            "QPushButton{background:#1f6feb;border:1px solid #388bfd;"
            "color:#fff;font-size:9px;font-weight:700;border-radius:2px;}"
            "QPushButton:hover{background:#388bfd;}")
        new_btn.clicked.connect(self.create_requested.emit)
        hdr.addWidget(new_btn)
        root.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFixedHeight(1)
        root.addWidget(sep)

        self._list = QListWidget()
        self._list.setFont(QFont("Courier New", 10))
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._on_open)
        root.addWidget(self._list, 1)

        self._counter = QLabel("No OPORDs")
        self._counter.setObjectName("statusSmall")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setContentsMargins(6, 4, 6, 4)
        root.addWidget(self._counter)

    def load_opords(self, opords: list[dict]):
        self._opords = opords
        self._list.clear()
        if not opords:
            it = QListWidgetItem("  No OPORDs on server")
            it.setForeground(QBrush(QColor("#484f58")))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(it)
            self._counter.setText("No OPORDs")
            return
        for o in opords:
            status = o.get("status", "DRAFT")
            icon   = STATUS_ICON.get(status, "?")
            color  = STATUS_COLOR.get(status, "#8b949e")
            num    = o.get("opord_number", "")
            title  = o.get("title", "?")
            dtg    = o.get("dtg", "")
            text   = f"  {icon}  {num+'  ' if num else ''}{title}"
            if dtg:
                text += f"   [{dtg}]"
            item = QListWidgetItem(text)
            item.setForeground(QBrush(QColor(color)))
            item.setData(Qt.ItemDataRole.UserRole, o)
            self._list.addItem(item)
        n = len(opords)
        self._counter.setText(f"{n} OPORD{'s' if n!=1 else ''}")

    def _on_open(self, item: QListWidgetItem):
        o = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(o, dict):
            self.open_requested.emit(o)
