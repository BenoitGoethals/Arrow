"""Messages Panel — tactical chat with broadcast / direct support."""
from __future__ import annotations
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent


class MessagesPanel(QWidget):
    message_send_requested = pyqtSignal(str)  # message content

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Chat history
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFont(QFont("Courier New", 10))
        self._history.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self._history, 1)

        # Divider
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#30363d;")
        layout.addWidget(sep)

        # Compose row
        compose = QHBoxLayout()
        compose.setContentsMargins(6, 4, 6, 4)
        compose.setSpacing(4)

        self._input = _ComposeField()
        self._input.setPlaceholderText("Broadcast message…  (Enter to send)")
        self._input.setFont(QFont("Courier New", 10))
        self._input.send_triggered.connect(self._send)

        self._send_btn = QPushButton("SEND")
        self._send_btn.setObjectName("primaryButton")
        self._send_btn.setFixedWidth(64)
        self._send_btn.clicked.connect(self._send)

        compose.addWidget(self._input, 1)
        compose.addWidget(self._send_btn)
        layout.addLayout(compose)

    # ---- Public API -------------------------------------------------------

    def add_message(self, data: dict):
        sender  = data.get("sender") or data.get("callsign") or "?"
        content = data.get("content", "")
        ts      = (data.get("timestamp") or data.get("created_at") or "")[:16]
        is_mine = data.get("is_mine", False)

        color   = "#79c0ff" if is_mine else "#3fb950"
        align   = "right" if is_mine else "left"

        html = (
            f'<div style="text-align:{align};margin:4px 0">'
            f'<span style="color:#6e7681;font-size:9px">{ts}&nbsp;</span>'
            f'<b style="color:{color}">{sender}</b>'
            f'<br><span style="color:#c9d1d9;font-size:10px">{content}</span>'
            f'</div>'
        )
        self._history.append(html)
        self._history.verticalScrollBar().setValue(
            self._history.verticalScrollBar().maximum()
        )

    def load_messages(self, messages: list):
        for m in messages:
            self.add_message(m)

    # ---- Private ----------------------------------------------------------

    def _send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return
        self.message_send_requested.emit(text)
        self._input.clear()


class _ComposeField(QTextEdit):
    """Single-line-feel text field that emits send_triggered on Enter."""
    send_triggered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            e.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.send_triggered.emit()
        else:
            super().keyPressEvent(e)
