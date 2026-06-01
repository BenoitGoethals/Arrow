"""Messaging Panel — broadcast / direct / mission-scoped chat."""
from __future__ import annotations
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QLabel, QComboBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent

SCOPE_BROADCAST = "BROADCAST"
SCOPE_DIRECT    = "DIRECT"
SCOPE_MISSION   = "MISSION"


class MessagesPanel(QWidget):
    """Compose and display messages with scope selection."""

    message_send_requested = pyqtSignal(str, str, object, object)
    # (content, message_type, receiver_id_or_None, mission_id_or_None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._operators: list[dict] = []   # [{id, callsign, ...}]
        self._missions:  list[dict] = []   # [{id, name, ...}]
        self._my_callsign: str = ""
        self._build_ui()

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Scope bar ────────────────────────────────────────────────────
        scope_bar = QFrame()
        scope_bar.setStyleSheet("background:#161b22;border-bottom:1px solid #21262d;")
        scope_layout = QHBoxLayout(scope_bar)
        scope_layout.setContentsMargins(6, 4, 6, 4)
        scope_layout.setSpacing(4)

        scope_layout.addWidget(
            QLabel("TO:", styleSheet="color:#6e7681;font-size:9px;font-weight:700;letter-spacing:1px;")
        )

        self._scope_combo = QComboBox()
        self._scope_combo.addItems(["BROADCAST", "DIRECT", "MISSION"])
        self._scope_combo.setFixedHeight(24)
        self._scope_combo.setStyleSheet(
            "QComboBox{font-family:'Courier New',monospace;font-size:10px;}"
        )
        self._scope_combo.currentTextChanged.connect(self._on_scope_changed)
        scope_layout.addWidget(self._scope_combo)

        # Recipient selector (visible for DIRECT and MISSION)
        self._recipient_combo = QComboBox()
        self._recipient_combo.setFixedHeight(24)
        self._recipient_combo.setMinimumWidth(140)
        self._recipient_combo.setStyleSheet(
            "QComboBox{font-family:'Courier New',monospace;font-size:10px;}"
        )
        self._recipient_combo.setVisible(False)
        scope_layout.addWidget(self._recipient_combo, 1)

        root.addWidget(scope_bar)

        # ── Message history ───────────────────────────────────────────────
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFont(QFont("Courier New", 10))
        self._history.setStyleSheet(
            "QTextEdit{background:#0d1117;border:none;color:#c9d1d9;}"
        )
        root.addWidget(self._history, 1)

        # ── Separator ────────────────────────────────────────────────────
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#21262d;")
        root.addWidget(sep)

        # ── Compose row ──────────────────────────────────────────────────
        compose = QHBoxLayout()
        compose.setContentsMargins(6, 5, 6, 5)
        compose.setSpacing(5)

        self._input = _ComposeField()
        self._input.setPlaceholderText("Type message…  Enter to send")
        self._input.setFont(QFont("Courier New", 10))
        self._input.setFixedHeight(46)
        self._input.setStyleSheet(
            "QTextEdit{background:#161b22;border:1px solid #30363d;"
            "border-radius:2px;color:#c9d1d9;padding:4px;}"
            "QTextEdit:focus{border-color:#388bfd;}"
        )
        self._input.send_triggered.connect(self._send)

        send_btn = QPushButton("▶")
        send_btn.setFixedSize(36, 36)
        send_btn.setObjectName("primaryButton")
        send_btn.setStyleSheet(
            "QPushButton{background:#1f6feb;border:1px solid #388bfd;"
            "color:#fff;font-size:14px;border-radius:2px;}"
            "QPushButton:hover{background:#388bfd;}"
        )
        send_btn.clicked.connect(self._send)

        compose.addWidget(self._input, 1)
        compose.addWidget(send_btn)
        root.addLayout(compose)

        # Scope: start on BROADCAST
        self._on_scope_changed("BROADCAST")

    # ---- Public API -------------------------------------------------------

    def set_my_callsign(self, callsign: str):
        self._my_callsign = callsign

    def set_operators(self, operators: list[dict]):
        self._operators = operators
        self._refresh_recipient_list()

    def set_missions(self, missions: list[dict]):
        self._missions = missions
        self._refresh_recipient_list()

    def add_message(self, data: dict):
        sender   = data.get("sender") or data.get("callsign") or "?"
        content  = data.get("content", "")
        ts_raw   = data.get("timestamp") or data.get("created_at") or ""
        ts       = ts_raw[11:16] if len(ts_raw) >= 16 else ts_raw
        scope    = data.get("message_type", "BROADCAST")
        is_mine  = (sender == self._my_callsign)

        scope_tag = ""
        if scope == "DIRECT":
            scope_tag = " [DM]"
        elif scope == "GROUP":
            scope_tag = " [GRP]"

        if is_mine:
            color_sender = "#388bfd"
            align = "right"
        else:
            color_sender = "#3fb950"
            align = "left"

        html = (
            f'<div style="margin:3px 0;text-align:{align}">'
            f'<span style="color:#484f58;font-size:9px">{ts}{scope_tag}&nbsp;</span>'
            f'<b style="color:{color_sender}">{sender}</b>'
            f'<br><span style="color:#c9d1d9;font-size:10px">'
            f'&nbsp;&nbsp;{_esc(content)}'
            f'</span></div>'
        )
        self._history.append(html)
        sb = self._history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def load_messages(self, messages: list[dict]):
        for m in messages:
            self.add_message(m)

    # ---- Private ----------------------------------------------------------

    def _on_scope_changed(self, scope: str):
        show_recipient = scope in (SCOPE_DIRECT, SCOPE_MISSION)
        self._recipient_combo.setVisible(show_recipient)
        self._refresh_recipient_list()

    def _refresh_recipient_list(self):
        scope = self._scope_combo.currentText()
        self._recipient_combo.blockSignals(True)
        self._recipient_combo.clear()
        if scope == SCOPE_DIRECT:
            for op in self._operators:
                cs = op.get("callsign", "?")
                self._recipient_combo.addItem(cs, userData=op.get("id"))
        elif scope == SCOPE_MISSION:
            for m in self._missions:
                self._recipient_combo.addItem(m.get("name", "?"), userData=m.get("id"))
        self._recipient_combo.blockSignals(False)

    def _send(self):
        content = self._input.toPlainText().strip()
        if not content:
            return
        scope = self._scope_combo.currentText()
        receiver_id = None
        mission_id  = None

        if scope == SCOPE_DIRECT:
            receiver_id = self._recipient_combo.currentData()
            if receiver_id is None:
                return  # no recipient selected
        elif scope == SCOPE_MISSION:
            mission_id = self._recipient_combo.currentData()

        self.message_send_requested.emit(content, scope, receiver_id, mission_id)
        self._input.clear()


class _ComposeField(QTextEdit):
    send_triggered = pyqtSignal()

    def keyPressEvent(self, e: QKeyEvent):
        if (e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self.send_triggered.emit()
        else:
            super().keyPressEvent(e)


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))
