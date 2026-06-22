"""Devices Panel — live roster of online devices, split into two sources.

* FRONT — Arrow operators reporting GPS through the app / desktop front / web
  (anything that POSTs to ``/tracking/position``). Sourced from
  ``GET /tracking/live`` and filtered to the computed ``online`` flag.
* ATAK  — Cursor-on-Target TCP clients currently connected to the backend's
  CoT server. Sourced from ``GET /cot/clients`` (``_Pool.client_list()``).

Clicking a FRONT row centres the map on that operator; clicking an ATAK row
centres on the device's last reported CoT position.
"""

from __future__ import annotations
from typing import List

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QLabel,
    QHeaderView,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont


class DevicesPanel(QWidget):
    operator_focus_requested = pyqtSignal(int)  # FRONT device → operator id
    coord_focus_requested = pyqtSignal(float, float)  # ATAK device → lat, lon

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QLabel("DEVICES ONLINE")
        hdr.setObjectName("panelHeader")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hdr)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(2)
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(14)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemClicked.connect(self._on_click)
        self._tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._tree.setColumnWidth(1, 48)
        layout.addWidget(self._tree)

        # Persistent group rows — children are repopulated on every refresh.
        self._front_group = self._make_item("▣  FRONT", "0", bold=True, color="#79c0ff")
        self._atak_group = self._make_item("▣  ATAK", "0", bold=True, color="#d2a8ff")
        self._tree.addTopLevelItem(self._front_group)
        self._tree.addTopLevelItem(self._atak_group)
        self._front_group.setExpanded(True)
        self._atak_group.setExpanded(True)

        self._summary = QLabel("No devices")
        self._summary.setObjectName("statusSmall")
        self._summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._summary.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._summary)

    # ---- Public API -------------------------------------------------------

    def load_front(self, operators: List[dict]):
        """Populate the FRONT group from a ``GET /tracking/live`` payload."""
        self._front_group.takeChildren()
        online = [o for o in operators if o.get("online")]
        online.sort(key=lambda o: (o.get("callsign") or "").lower())
        for op in online:
            self._front_group.addChild(self._make_front_item(op))
        self._front_group.setText(1, str(len(online)))
        self._update_summary()

    def load_atak(self, clients: List[dict]):
        """Populate the ATAK group from a ``GET /cot/clients`` payload."""
        self._atak_group.takeChildren()
        clients = sorted(
            clients, key=lambda c: (c.get("callsign") or c.get("uid") or "").lower()
        )
        for cl in clients:
            self._atak_group.addChild(self._make_atak_item(cl))
        self._atak_group.setText(1, str(len(clients)))
        self._update_summary()

    # ---- Item builders ----------------------------------------------------

    def _make_front_item(self, op: dict) -> QTreeWidgetItem:
        rank = op.get("rank", "")
        src = (op.get("position_source") or "APP").upper()
        label = f"  {rank}  {op['callsign']}" if rank else f"  {op['callsign']}"
        item = self._make_item(label, "●", color="#c9d1d9")
        item.setForeground(1, QBrush(QColor("#3fb950")))
        item.setData(0, Qt.ItemDataRole.UserRole, ("op", op.get("id")))
        item.setToolTip(0, f"{src} · last seen {op.get('last_seen', '')}")
        return item

    def _make_atak_item(self, cl: dict) -> QTreeWidgetItem:
        name = cl.get("callsign") or cl.get("uid") or "ATAK"
        plat = cl.get("platform") or ""
        label = f"  {name}  ·  {plat}" if plat else f"  {name}"
        item = self._make_item(label, "●", color="#c9d1d9")
        item.setForeground(1, QBrush(QColor("#3fb950")))
        lat = float(cl.get("last_lat") or 0.0)
        lon = float(cl.get("last_lon") or 0.0)
        item.setData(0, Qt.ItemDataRole.UserRole, ("coord", lat, lon))
        ago = cl.get("last_seen_ago_s")
        ip = cl.get("ip", "")
        tip = f"{ip} · last seen {ago}s ago" if ago is not None else ip
        item.setToolTip(0, tip)
        return item

    @staticmethod
    def _make_item(
        col0: str, col1: str, bold=False, color="#c9d1d9"
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([col0, col1])
        item.setForeground(0, QBrush(QColor(color)))
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
        if bold:
            f = QFont()
            f.setBold(True)
            item.setFont(0, f)
        return item

    def _update_summary(self):
        f = self._front_group.childCount()
        a = self._atak_group.childCount()
        self._summary.setText(f"■ {f} FRONT  ·  {a} ATAK")

    # ---- Interaction ------------------------------------------------------

    def _on_click(self, item: QTreeWidgetItem, _col):
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            if item.childCount() > 0:
                item.setExpanded(not item.isExpanded())
            return
        kind = payload[0]
        if kind == "op" and payload[1] is not None:
            self.operator_focus_requested.emit(int(payload[1]))
        elif kind == "coord" and (payload[1] or payload[2]):
            self.coord_focus_requested.emit(float(payload[1]), float(payload[2]))
