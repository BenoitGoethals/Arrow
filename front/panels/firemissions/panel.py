"""Fire Missions panel — live FDC queue tracking every call-for-fire.

Lists all fire missions (own and others) with their status, and follows their
progress in real time as ``fire-mission`` WS events arrive (submitted / updated).
Selecting a mission shows the full call-for-fire detail; BATTLE_CAPTAIN / ADMIN
operators can advance the status straight from the panel (PATCH /fire-missions).
"""

from __future__ import annotations
from typing import Dict, Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QGridLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont

STATUS_COLOR = {
    "PENDING": "#f85149",
    "ACKNOWLEDGED": "#d29922",
    "IN_PROGRESS": "#1f6feb",
    "FIRED": "#ff8800",
    "COMPLETED": "#3fb950",
    "CANCELLED": "#6e7681",
}
STATUS_ICON = {
    "PENDING": "○",
    "ACKNOWLEDGED": "◔",
    "IN_PROGRESS": "◑",
    "FIRED": "◉",
    "COMPLETED": "✓",
    "CANCELLED": "✕",
}
TYPE_ABBR = {
    "ADJUST_FIRE": "AF",
    "FIRE_FOR_EFFECT": "FFE",
    "SUPPRESSION": "SUPP",
    "ILLUMINATION": "ILLUM",
    "IMMEDIATE_SUPPRESSION": "IMMED",
}
# FDC transitions an operator with the right role may apply.
STATUS_FLOW = [
    ("ACK", "ACKNOWLEDGED"),
    ("FIRING", "IN_PROGRESS"),
    ("DONE", "COMPLETED"),
    ("CANCEL", "CANCELLED"),
]


class FireMissionsPanel(QWidget):
    refresh_requested = pyqtSignal()
    locate_requested = pyqtSignal(float, float)
    status_change_requested = pyqtSignal(int, str)  # (fm_id, new_status)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._missions: Dict[int, dict] = {}
        self._operators: Dict[int, str] = {}  # operator_id → callsign
        self._role: str = "OPERATOR"
        self._my_id: Optional[int] = None
        self._selected_id: Optional[int] = None
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 6, 8, 4)
        hdr.addWidget(
            QLabel(
                "FIRE MISSIONS",
                styleSheet="color:#8b949e;font-size:12px;font-weight:700;letter-spacing:2px;",
            )
        )
        hdr.addStretch()
        self._pending_lbl = QLabel("")
        self._pending_lbl.setStyleSheet(
            "color:#f85149;font-size:11px;font-weight:700;font-family:'Courier New',monospace;"
        )
        hdr.addWidget(self._pending_lbl)

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
        root.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        self._list = QListWidget()
        self._list.setFont(QFont("Courier New", 13))
        self._list.setAlternatingRowColors(True)
        self._list.setFixedHeight(200)
        self._list.itemClicked.connect(self._on_select)
        root.addWidget(self._list)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFixedHeight(1)
        root.addWidget(sep2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._detail_widget = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_widget)
        self._detail_layout.setContentsMargins(8, 8, 8, 8)
        self._detail_layout.setSpacing(6)
        self._placeholder()
        scroll.setWidget(self._detail_widget)
        root.addWidget(scroll, 1)

        self._counter = QLabel("No fire missions")
        self._counter.setObjectName("statusSmall")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setContentsMargins(6, 4, 6, 4)
        root.addWidget(self._counter)

    # ── Public API ─────────────────────────────────────────────────────────
    def set_role(self, role: str, my_operator_id: Optional[int] = None):
        self._role = role or "OPERATOR"
        if my_operator_id is not None:
            self._my_id = my_operator_id

    def set_operators(self, operators: list):
        self._operators = {
            o.get("id"): o.get("callsign", "")
            for o in operators
            if o.get("id") is not None
        }

    def load_missions(self, missions: list):
        self._missions = {m["id"]: m for m in missions if m.get("id") is not None}
        self._rebuild()

    def upsert_mission(self, fm: dict):
        """Add or update a single mission (from a WS fire-mission event)."""
        fid = fm.get("id")
        if fid is None:
            return
        # WS payloads carry callsign; cache it so the list can label the sender.
        cs = fm.get("callsign")
        if cs and fm.get("operator_id") is not None:
            self._operators[fm["operator_id"]] = cs
        existing = self._missions.get(fid, {})
        self._missions[fid] = {**existing, **fm}
        self._rebuild()
        if self._selected_id == fid:
            self._show_detail(self._missions[fid])

    # ── List rendering ───────────────────────────────────────────────────────
    def _rebuild(self):
        self._list.clear()
        if not self._missions:
            item = QListWidgetItem("  No fire missions")
            item.setForeground(QBrush(QColor("#484f58")))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self._counter.setText("No fire missions")
            self._pending_lbl.setText("")
            return

        # Newest first by id (ids increase with time).
        ordered = sorted(
            self._missions.values(), key=lambda m: m.get("id", 0), reverse=True
        )
        pending = 0
        for m in ordered:
            status = (m.get("status") or "PENDING").upper()
            if status == "PENDING":
                pending += 1
            icon = STATUS_ICON.get(status, "?")
            color = STATUS_COLOR.get(status, "#8b949e")
            typ = TYPE_ABBR.get(m.get("mission_type", ""), m.get("mission_type", "?"))
            ammo = m.get("ammunition", "?")
            qty = m.get("quantity", "?")
            who = self._callsign_for(m)
            own = (
                "★"
                if self._my_id is not None and m.get("operator_id") == self._my_id
                else " "
            )
            label = f" {own}{icon} #{m.get('id')} {typ} · {ammo}×{qty} · {who}"
            item = QListWidgetItem(label)
            item.setForeground(QBrush(QColor(color)))
            item.setData(Qt.ItemDataRole.UserRole, m.get("id"))
            self._list.addItem(item)

        n = len(self._missions)
        self._counter.setText(
            f"{n} mission{'s' if n != 1 else ''}  ·  {pending} pending"
        )
        self._pending_lbl.setText(f"⦿ {pending}" if pending else "")

    def _callsign_for(self, m: dict) -> str:
        op_id = m.get("operator_id")
        cs = m.get("callsign")
        if not cs and op_id is not None:
            cs = self._operators.get(op_id)
        return cs or f"OP{op_id if op_id is not None else '?'}"

    # ── Detail pane ────────────────────────────────────────────────────────
    def _on_select(self, item: QListWidgetItem):
        fid = item.data(Qt.ItemDataRole.UserRole)
        if fid is None:
            return
        self._selected_id = int(fid)
        self._show_detail(self._missions.get(int(fid), {}))

    def _placeholder(self):
        self._detail_layout.addWidget(
            QLabel(
                "Select a fire mission",
                styleSheet="color:#484f58;font-size:13px;font-family:'Courier New',monospace;",
            ),
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

    def _clear_detail(self):
        def _clear(lay):
            while lay.count():
                child = lay.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
                elif child.layout():
                    _clear(child.layout())

        _clear(self._detail_layout)

    def _show_detail(self, m: dict):
        self._clear_detail()
        if not m:
            self._placeholder()
            return

        status = (m.get("status") or "PENDING").upper()
        color = STATUS_COLOR.get(status, "#8b949e")

        def _lbl(
            txt,
            style="color:#8b949e;font-size:11px;font-weight:700;letter-spacing:1px;",
        ):
            l = QLabel(txt)
            l.setStyleSheet(style)
            return l

        def _val(
            txt,
            style="color:#c9d1d9;font-size:13px;font-family:'Courier New',monospace;",
        ):
            l = QLabel(str(txt))
            l.setStyleSheet(style)
            l.setWordWrap(True)
            return l

        # Title row: status icon + id + type
        typ = TYPE_ABBR.get(m.get("mission_type", ""), m.get("mission_type", "?"))
        title = QLabel(f"  {STATUS_ICON.get(status,'?')}  FM #{m.get('id')}  ·  {typ}")
        title.setStyleSheet(
            f"color:{color};font-size:14px;font-weight:700;"
            f"font-family:'Courier New',monospace;"
        )
        self._detail_layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#21262d;")
        sep.setFixedHeight(1)
        self._detail_layout.addWidget(sep)

        # Stats grid
        grid = QGridLayout()
        grid.setSpacing(4)
        from front.utils.mgrs_util import to_mgrs

        try:
            mgrs = to_mgrs(m.get("latitude", 0.0), m.get("longitude", 0.0))
        except Exception:
            mgrs = f"{m.get('latitude')}, {m.get('longitude')}"
        rows = [
            ("STATUS", status),
            ("FROM", self._callsign_for(m)),
            ("GRID", mgrs),
            ("AMMO", f"{m.get('ammunition','?')} × {m.get('quantity','?')}"),
            ("DIRECTION", f"{m.get('direction','?')}°"),
            ("ALTITUDE", f"{m.get('altitude','?')} m"),
        ]
        for i, (k, v) in enumerate(rows):
            grid.addWidget(_lbl(k), i, 0)
            vstyle = "color:#c9d1d9;font-size:13px;font-family:'Courier New',monospace;"
            if k == "STATUS":
                vstyle = f"color:{color};font-size:13px;font-weight:700;font-family:'Courier New',monospace;"
            grid.addWidget(_val(v, vstyle), i, 1)
        self._detail_layout.addLayout(grid)

        if m.get("description"):
            self._detail_layout.addWidget(_lbl("DESCRIPTION"))
            self._detail_layout.addWidget(_val(m["description"]))
        if m.get("notes"):
            self._detail_layout.addWidget(_lbl("FDC NOTES"))
            self._detail_layout.addWidget(
                _val(m["notes"], "color:#79c0ff;font-size:12px;")
            )
        if m.get("timestamp"):
            self._detail_layout.addWidget(
                _val(
                    str(m["timestamp"]).replace("T", " ")[:19],
                    "color:#6e7681;font-size:11px;font-family:'Courier New',monospace;",
                )
            )

        # Locate button
        locate = QPushButton("◎  CENTER ON MAP")
        locate.setStyleSheet(
            "QPushButton{background:#1c2d3f;border:1px solid #1f6feb;color:#79c0ff;"
            "font-size:12px;font-weight:700;padding:5px;border-radius:2px;}"
            "QPushButton:hover{background:#1f6feb;color:#fff;}"
        )
        lat, lon = m.get("latitude"), m.get("longitude")
        locate.clicked.connect(
            lambda: self.locate_requested.emit(float(lat or 0), float(lon or 0))
        )
        self._detail_layout.addWidget(locate)

        # FDC status controls — only for roles the backend will accept.
        if self._role in ("ADMIN", "BATTLE_CAPTAIN") and status not in (
            "COMPLETED",
            "CANCELLED",
        ):
            self._detail_layout.addWidget(_lbl("FDC — UPDATE STATUS"))
            btn_row = QHBoxLayout()
            btn_row.setSpacing(4)
            for label, new_status in STATUS_FLOW:
                if new_status == status:
                    continue
                b = QPushButton(label)
                sc = STATUS_COLOR.get(new_status, "#8b949e")
                b.setStyleSheet(
                    f"QPushButton{{background:#161b22;border:1px solid {sc};color:{sc};"
                    "font-size:11px;font-weight:700;padding:4px 6px;border-radius:2px;}}"
                    f"QPushButton:hover{{background:{sc};color:#0d1117;}}"
                )
                fid = m.get("id")
                b.clicked.connect(
                    lambda _=False, s=new_status, i=fid: self.status_change_requested.emit(
                        int(i), s
                    )
                )
                btn_row.addWidget(b)
            self._detail_layout.addLayout(btn_row)

        self._detail_layout.addStretch()
