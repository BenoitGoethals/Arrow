"""Status bar — MGRS coordinates, Zulu time, server connection LED."""

from __future__ import annotations
from datetime import datetime, timezone

from PyQt6.QtWidgets import QStatusBar, QLabel
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont


class StatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self._build()

    def _build(self):
        mono = QFont("Courier New", 10)

        # MGRS coordinate (left)
        self._mgrs = QLabel("MGRS: —")
        self._mgrs.setFont(mono)
        self._mgrs.setMinimumWidth(200)
        self.addWidget(self._mgrs)

        self.addWidget(_sep())

        # Permanent: server status
        self._server = QLabel("● SERVER")
        self._server.setFont(mono)
        self._server.setStyleSheet("color:#6e7681;padding:0 8px;")
        self.addPermanentWidget(self._server)

        # Permanent: Zulu clock
        self._clock = QLabel("—:—:—Z")
        self._clock.setFont(mono)
        self._clock.setStyleSheet("color:#8b949e;padding:0 8px;")
        self.addPermanentWidget(self._clock)

        # Clock timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    # ---- Public API ------------------------------------------------------

    def update_coords(self, lat: float, lon: float, mgrs: str):
        self._mgrs.setText(f"MGRS: {mgrs}")

    def set_connected(self, connected: bool):
        if connected:
            self._server.setText("● SERVER")
            self._server.setStyleSheet("color:#3fb950;padding:0 8px;font-weight:bold;")
        else:
            self._server.setText("○ NO LINK")
            self._server.setStyleSheet("color:#f85149;padding:0 8px;")

    # ---- Private ---------------------------------------------------------

    def _tick(self):
        now = datetime.now(timezone.utc)
        self._clock.setText(now.strftime("%H:%M:%SZ"))


def _sep() -> QLabel:
    s = QLabel("│")
    s.setStyleSheet("color:#30363d;padding:0 4px;")
    return s
