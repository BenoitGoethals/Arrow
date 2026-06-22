"""Log viewer panel — shows recent Arrow Front log entries in real time."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QComboBox,
    QLabel,
)
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont, QColor, QTextCharFormat

from front.utils.log_setup import get_recent_lines, log_file_path

_MONO = QFont("Courier New", 12)

# Colour map by log level keyword
_LEVEL_COLORS: dict[str, str] = {
    "DEBUG   ": "#484f58",
    "INFO    ": "#79c0ff",
    "WARNING ": "#d29922",
    "ERROR   ": "#f85149",
    "CRITICAL": "#ff0000",
}


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused = False
        self._last_count = 0
        self._build()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── Toolbar ──────────────────────────────────────────────────────
        tb = QHBoxLayout()

        lbl = QLabel("LEVEL")
        lbl.setStyleSheet("color:#484f58;font-size:12px;font-weight:700;")
        tb.addWidget(lbl)

        self._level_filter = QComboBox()
        self._level_filter.addItems(["ALL", "DEBUG", "INFO", "WARNING", "ERROR"])
        self._level_filter.setCurrentText("INFO")
        self._level_filter.setFixedWidth(90)
        self._level_filter.currentTextChanged.connect(self._refresh)
        tb.addWidget(self._level_filter)

        tb.addStretch()

        self._pause_btn = QPushButton("⏸ Pause")
        self._pause_btn.setFixedWidth(72)
        self._pause_btn.setObjectName("toolButton")
        self._pause_btn.clicked.connect(self._toggle_pause)
        tb.addWidget(self._pause_btn)

        clear_btn = QPushButton("✕ Clear")
        clear_btn.setFixedWidth(66)
        clear_btn.setObjectName("toolButton")
        clear_btn.clicked.connect(self._clear)
        tb.addWidget(clear_btn)

        open_btn = QPushButton("📂")
        open_btn.setFixedWidth(30)
        open_btn.setToolTip(f"Open log file: {log_file_path()}")
        open_btn.setObjectName("toolButton")
        open_btn.clicked.connect(self._open_file)
        tb.addWidget(open_btn)

        root.addLayout(tb)

        # ── Log view ──────────────────────────────────────────────────────
        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setFont(_MONO)
        self._view.setStyleSheet(
            "QPlainTextEdit{"
            "  background:#0d1117;border:1px solid #21262d;"
            "  color:#8b949e;"
            "}"
        )
        self._view.setMaximumBlockCount(2000)
        root.addWidget(self._view)

        # ── Status bar ───────────────────────────────────────────────────
        self._status = QLabel(f"Log: {log_file_path()}")
        self._status.setStyleSheet("color:#484f58;font-size:11px;")
        self._status.setFont(QFont("Courier New", 11))
        root.addWidget(self._status)

    # ── Refresh ───────────────────────────────────────────────────────────

    def _refresh(self):
        if self._paused:
            return
        level = self._level_filter.currentText()
        _ORDER = {
            "DEBUG": 0,
            "INFO": 1,
            "WARNING": 2,
            "ERROR": 3,
            "CRITICAL": 4,
            "ALL": -1,
        }
        min_level = _ORDER.get(level, -1)

        lines = get_recent_lines(500)
        if len(lines) == self._last_count:
            return
        self._last_count = len(lines)

        filtered = []
        for line in lines:
            if min_level >= 0:
                matched = False
                for lvl, ord_ in _ORDER.items():
                    if lvl != "ALL" and lvl in line and ord_ >= min_level:
                        matched = True
                        break
                if not matched:
                    continue
            filtered.append(line)

        self._view.clear()
        cursor = self._view.textCursor()
        for line in filtered:
            fmt = QTextCharFormat()
            color = "#8b949e"
            for key, col in _LEVEL_COLORS.items():
                if key.strip() in line:
                    color = col
                    break
            fmt.setForeground(QColor(color))
            cursor.setCharFormat(fmt)
            cursor.insertText(line + "\n")

        # Scroll to bottom
        sb = self._view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _toggle_pause(self):
        self._paused = not self._paused
        self._pause_btn.setText("▶ Resume" if self._paused else "⏸ Pause")

    def _clear(self):
        self._view.clear()
        self._last_count = 0

    def _open_file(self):
        import subprocess
        import sys

        path = str(log_file_path())
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Console", path])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", path])
        else:
            subprocess.Popen(["notepad", path])
