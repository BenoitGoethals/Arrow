"""Toast notification manager — slide-in alerts in the bottom-right corner."""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QMainWindow,
)
from PyQt6.QtCore import Qt, QTimer, QRect, QObject, pyqtSignal

SEVERITY = {
    "tic": ("#f85149", "⚡"),
    "alert": ("#f85149", "⚠"),
    "medevac": ("#ff9e64", "🚁"),
    "drone": ("#d2a8ff", "🛸"),
    "report": ("#d29922", "📋"),
    "message": ("#79c0ff", "◎"),
    "info": ("#3fb950", "●"),
    "mission": ("#1f6feb", "◈"),
    "cbrn": ("#ff4400", "☢"),
}

_W = 340  # toast width
_GAP = 6  # gap between toasts


class _Toast(QFrame):
    closed = pyqtSignal(object)

    def __init__(self, icon: str, title: str, body: str, color: str, parent):
        super().__init__(parent)
        self._color = color
        self.setFixedWidth(_W)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            QFrame {{
                background: rgba(22,27,34,0.97);
                border: 1px solid #30363d;
                border-left: 3px solid {color};
                border-radius: 3px;
            }}
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 8, 8)
        root.setSpacing(10)

        # Icon
        ico = QLabel(icon)
        ico.setStyleSheet(f"color:{color};font-size:18px;border:none;background:none;")
        ico.setFixedWidth(22)
        ico.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(ico)

        # Text
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        ttl = QLabel(title.upper())
        ttl.setStyleSheet(
            f"color:{color};font-family:'Courier New',monospace;"
            f"font-size:10px;font-weight:700;letter-spacing:1px;border:none;background:none;"
        )
        ttl.setWordWrap(False)
        text_col.addWidget(ttl)

        if body:
            bdy = QLabel(body)
            bdy.setStyleSheet(
                "color:#c9d1d9;font-family:'Courier New',monospace;"
                "font-size:10px;border:none;background:none;"
            )
            bdy.setWordWrap(True)
            bdy.setMaximumWidth(240)
            text_col.addWidget(bdy)

        root.addLayout(text_col, 1)

        # Close button
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(18, 18)
        close_btn.setStyleSheet(
            "QPushButton{background:none;border:none;color:#484f58;font-size:11px;padding:0;}"
            "QPushButton:hover{color:#f85149;}"
        )
        close_btn.clicked.connect(self._dismiss)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)

        self.adjustSize()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start(7000)

    def _dismiss(self):
        self._timer.stop()
        self.closed.emit(self)
        self.deleteLater()

    def mousePressEvent(self, _):
        self._dismiss()


class ToastManager(QObject):
    """Attach to a QMainWindow; call show() from anywhere to display toasts."""

    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self._window = window
        self._toasts: list[_Toast] = []

    # ---- Public API -------------------------------------------------------

    def show(self, kind: str, title: str, body: str = ""):
        color, icon = SEVERITY.get(kind, ("#8b949e", "●"))
        toast = _Toast(icon, title, body, color, self._window)
        toast.closed.connect(self._on_closed)
        self._toasts.append(toast)
        toast.show()
        toast.raise_()
        self._restack()

    def alert(self, alert_type: str, operator: str = "", location: str = ""):
        kind_map = {
            "TIC": "tic",
            "MEDICAL": "medevac",
            "EVAC": "alert",
            "LOST_COMMS": "alert",
            "DRONE_SPOTTED": "drone",
        }
        kind = kind_map.get(alert_type, "alert")
        body_parts = [p for p in [operator, location] if p]
        self.show(kind, alert_type.replace("_", " "), "  ".join(body_parts))

    def report(self, report_type: str, sender: str = ""):
        self.show("report", f"REPORT: {report_type}", sender)

    def message(self, sender: str, preview: str = ""):
        self.show("message", f"MSG from {sender}", preview[:80])

    # ---- Layout -----------------------------------------------------------

    def _on_closed(self, toast: _Toast):
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._restack()

    def _restack(self):
        w = self._window
        sb = w.statusBar().height() if w.statusBar() else 24
        pad = 10
        bottom = w.height() - sb - pad
        for i, t in enumerate(reversed(self._toasts)):
            h = t.sizeHint().height()
            x = w.width() - _W - pad
            y = bottom - h
            t.setGeometry(QRect(x, y, _W, h))
            bottom -= h + _GAP

    def restack(self):
        self._restack()
