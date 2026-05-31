"""Alerts Panel — live alert feed with priority styling."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QLabel,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from front.models.report import PRIORITY_COLORS

ALERT_COLOR = {
    "TIC":           "#f85149",
    "MEDICAL":       "#ff9e64",
    "EVAC":          "#ffa500",
    "LOST_COMMS":    "#d29922",
    "DRONE_SPOTTED": "#d2a8ff",
}

ALERT_ICON = {
    "TIC":           "⚡",
    "MEDICAL":       "🚑",
    "EVAC":          "🚁",
    "LOST_COMMS":    "📡",
    "DRONE_SPOTTED": "🛸",
}


class AlertsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._count = 0

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setFont(QFont("Courier New", 10))
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list, 1)

        self._counter = QLabel("No alerts")
        self._counter.setObjectName("statusSmall")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._counter)

    # ---- Public API -------------------------------------------------------

    def add_alert(self, data: dict):
        alert_type = data.get("type", "UNKNOWN")
        operator   = data.get("operator") or data.get("callsign") or "?"
        ts         = (data.get("timestamp") or data.get("created_at") or "")[:16]
        icon       = ALERT_ICON.get(alert_type, "⚠")
        color      = ALERT_COLOR.get(alert_type, "#f85149")

        item = QListWidgetItem(
            f"{icon}  {alert_type:<16}  {operator:<12}  {ts}"
        )
        item.setForeground(QColor(color))
        font = QFont("Courier New", 10)
        font.setBold(True)
        item.setFont(font)

        self._list.insertItem(0, item)
        self._count += 1
        self._counter.setText(f"{self._count} alert{'s' if self._count != 1 else ''}")
