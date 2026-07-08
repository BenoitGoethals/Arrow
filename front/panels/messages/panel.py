"""Messaging Panel — broadcast / direct / mission-scoped chat."""

from __future__ import annotations
import base64
import urllib.request
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QFrame,
    QFileDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent

SCOPE_BROADCAST = "BROADCAST"
SCOPE_DIRECT = "DIRECT"
SCOPE_ROOM = "ROOM"


class _ImageFetchThread(QThread):
    """Download one image with Bearer auth; emit raw bytes on the main thread."""

    loaded = pyqtSignal(str, bytes)  # url, data

    def __init__(self, url: str, token: str):
        super().__init__()
        self._url = url
        self._token = token

    def run(self):
        try:
            req = urllib.request.Request(
                self._url,
                headers={"Authorization": f"Bearer {self._token}"},
            )
            from front.utils.ssl_utils import NO_VERIFY_CTX

            with urllib.request.urlopen(req, timeout=15, context=NO_VERIFY_CTX) as resp:
                data = resp.read()
            self.loaded.emit(self._url, data)
        except Exception:
            pass


class MessagesPanel(QWidget):
    """Compose and display messages with scope selection."""

    message_send_requested = pyqtSignal(str, str, object, object, object)
    # (content, message_type, receiver_id_or_None, target_id_or_None, file_path_or_None)
    # target_id carries the chatroom_id when message_type == "ROOM".
    manage_rooms_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._operators: list[dict] = []
        self._missions: list[dict] = []
        self._rooms: list[dict] = []
        self._my_callsign: str = ""
        self._pending_file: str | None = None
        self._server_url: str = ""
        self._token: str = ""
        # Message history and image cache (url → data-URI)
        self._msg_data: list[dict] = []
        self._img_cache: dict[str, str] = {}
        self._img_threads: list[_ImageFetchThread] = []
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
            QLabel(
                "TO:",
                styleSheet="color:#6e7681;font-size:12px;font-weight:700;letter-spacing:1px;",
            )
        )

        self._scope_combo = QComboBox()
        self._scope_combo.addItems(["BROADCAST", "DIRECT", "ROOM"])
        self._scope_combo.setFixedHeight(24)
        self._scope_combo.setStyleSheet(
            "QComboBox{font-family:'Courier New',monospace;font-size:13px;}"
        )
        self._scope_combo.currentTextChanged.connect(self._on_scope_changed)
        scope_layout.addWidget(self._scope_combo)

        self._recipient_combo = QComboBox()
        self._recipient_combo.setFixedHeight(24)
        self._recipient_combo.setMinimumWidth(140)
        self._recipient_combo.setStyleSheet(
            "QComboBox{font-family:'Courier New',monospace;font-size:13px;}"
        )
        self._recipient_combo.setVisible(False)
        scope_layout.addWidget(self._recipient_combo, 1)

        # Manage chat rooms (create / add / remove members)
        self._rooms_btn = QPushButton("⚙ Rooms")
        self._rooms_btn.setFixedHeight(24)
        self._rooms_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #30363d;color:#c9d1d9;"
            "font-size:12px;border-radius:2px;padding:0 8px;}"
            "QPushButton:hover{border-color:#388bfd;}"
        )
        self._rooms_btn.clicked.connect(self.manage_rooms_requested.emit)
        scope_layout.addWidget(self._rooms_btn)

        root.addWidget(scope_bar)

        # ── Message history ───────────────────────────────────────────────
        self._history = QTextEdit()
        self._history.setReadOnly(True)
        self._history.setFont(QFont("Courier New", 13))
        self._history.setStyleSheet(
            "QTextEdit{background:#0d1117;border:none;color:#c9d1d9;}"
        )
        root.addWidget(self._history, 1)

        # ── Separator ────────────────────────────────────────────────────
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#21262d;")
        root.addWidget(sep)

        # ── Attachment preview strip ─────────────────────────────────────
        self._attach_bar = QFrame()
        self._attach_bar.setStyleSheet(
            "background:#161b22;border-top:1px solid #21262d;"
        )
        attach_layout = QHBoxLayout(self._attach_bar)
        attach_layout.setContentsMargins(6, 3, 6, 3)
        attach_layout.setSpacing(6)
        self._attach_label = QLabel()
        self._attach_label.setStyleSheet("color:#8b949e;font-size:12px;")
        attach_layout.addWidget(self._attach_label, 1)
        clear_btn = QPushButton("✕")
        clear_btn.setFixedSize(18, 18)
        clear_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#8b949e;border:none;font-size:13px;}"
            "QPushButton:hover{color:#f85149;}"
        )
        clear_btn.clicked.connect(self._clear_attachment)
        attach_layout.addWidget(clear_btn)
        self._attach_bar.setVisible(False)
        root.addWidget(self._attach_bar)

        # ── Compose row ──────────────────────────────────────────────────
        compose = QHBoxLayout()
        compose.setContentsMargins(6, 5, 6, 5)
        compose.setSpacing(5)

        attach_btn = QPushButton("📎")
        attach_btn.setFixedSize(28, 28)
        attach_btn.setToolTip("Attach photo or video")
        attach_btn.setStyleSheet(
            "QPushButton{background:#161b22;border:1px solid #30363d;"
            "color:#c9d1d9;font-size:15px;border-radius:2px;}"
            "QPushButton:hover{border-color:#388bfd;}"
        )
        attach_btn.clicked.connect(self._pick_attachment)

        self._input = _ComposeField()
        self._input.setPlaceholderText("Type message…  Enter to send")
        self._input.setFont(QFont("Courier New", 13))
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
            "color:#fff;font-size:15px;border-radius:2px;}"
            "QPushButton:hover{background:#388bfd;}"
        )
        send_btn.clicked.connect(self._send)

        compose.addWidget(attach_btn)
        compose.addWidget(self._input, 1)
        compose.addWidget(send_btn)
        root.addLayout(compose)

        self._on_scope_changed("BROADCAST")

    # ---- Public API -------------------------------------------------------

    def set_my_callsign(self, callsign: str):
        self._my_callsign = callsign

    def set_server(self, server_url: str, token: str):
        self._server_url = server_url
        self._token = token

    def set_operators(self, operators: list[dict]):
        self._operators = operators
        self._refresh_recipient_list()

    def set_missions(self, missions: list[dict]):
        self._missions = missions
        self._refresh_recipient_list()

    def set_rooms(self, rooms: list[dict]):
        self._rooms = rooms or []
        self._refresh_recipient_list()

    def add_message(self, data: dict):
        self._msg_data.append(data)
        self._maybe_fetch_image(data)
        self._rebuild_history(scroll_to_bottom=True)

    def load_messages(self, messages: list[dict]):
        for m in messages:
            self._msg_data.append(m)
            self._maybe_fetch_image(m)
        self._rebuild_history(scroll_to_bottom=True)

    # ---- Image fetching ---------------------------------------------------

    def _maybe_fetch_image(self, data: dict):
        photo_id = data.get("photo_id")
        mime_type = data.get("photo_mime_type", "")
        if not photo_id or not self._server_url or not self._token:
            return
        if mime_type and mime_type.startswith("video/"):
            return
        url = f"{self._server_url}/photos/{photo_id}"
        if url in self._img_cache:
            return
        # Mark as in-flight so we don't launch duplicates
        self._img_cache[url] = ""
        t = _ImageFetchThread(url, self._token)
        t.loaded.connect(self._on_image_loaded)
        t.start()
        self._img_threads.append(t)

    def _on_image_loaded(self, url: str, data: bytes):
        """Main-thread slot: convert bytes → base64 data-URI, then redraw."""
        if not data:
            return
        # Detect image type from magic bytes
        if data[:4] == b"\x89PNG":
            mime = "image/png"
        elif data[:3] == b"GIF":
            mime = "image/gif"
        elif data[:4] in (b"RIFF", b"WEBP") or b"WEBP" in data[:12]:
            mime = "image/webp"
        else:
            mime = "image/jpeg"
        b64 = base64.b64encode(data).decode("ascii")
        self._img_cache[url] = f"data:{mime};base64,{b64}"
        self._rebuild_history(scroll_to_bottom=False)

    # ---- Rendering --------------------------------------------------------

    def _rebuild_history(self, scroll_to_bottom: bool = False):
        sb = self._history.verticalScrollBar()
        was_at_bottom = sb.value() >= sb.maximum() - 4

        parts = ["<html><body style='background:#0d1117;margin:0;padding:4px;'>"]
        for m in self._msg_data:
            parts.append(self._render_msg(m))
        parts.append("</body></html>")

        self._history.setHtml("".join(parts))

        if scroll_to_bottom or was_at_bottom:
            sb.setValue(sb.maximum())

    def _render_msg(self, data: dict) -> str:
        sender = data.get("sender") or data.get("callsign") or "?"
        content = data.get("content", "")
        ts_raw = data.get("timestamp") or data.get("created_at") or ""
        ts = ts_raw[11:16] if len(ts_raw) >= 16 else ts_raw
        scope = data.get("message_type", "BROADCAST")
        is_mine = sender == self._my_callsign
        photo_id = data.get("photo_id")
        mime_type = data.get("photo_mime_type", "")

        scope_tag = ""
        if scope == "DIRECT":
            scope_tag = " [DM]"
        elif scope == "ROOM":
            rid = data.get("chatroom_id")
            rname = next(
                (r.get("name") for r in self._rooms if r.get("id") == rid), None
            )
            scope_tag = f" [# {rname}]" if rname else " [ROOM]"

        # Origin marker: ARROW (native) / JDSS (coalition) / TAK (ATAK CoT).
        src = (data.get("source") or "ARROW").upper()
        src_label = "TAK" if src == "ATAK" else src
        src_fg, src_bg = {
            "JDSS": ("#fcd34d", "#78350f"),
            "ATAK": ("#7dd3fc", "#0c4a6e"),
        }.get(src, ("#86efac", "#14532d"))
        src_badge = (
            f'<span style="color:{src_fg};background:{src_bg};font-size:10px;'
            f'font-weight:bold;padding:0 4px;border-radius:3px;">{src_label}</span>&nbsp;'
        )

        color_sender = "#388bfd" if is_mine else "#3fb950"
        align = "right" if is_mine else "left"

        media_html = ""
        if photo_id and self._server_url:
            url = f"{self._server_url}/photos/{photo_id}"
            if mime_type and mime_type.startswith("video/"):
                media_html = (
                    f'<br><span style="color:#8b949e;font-size:12px">'
                    f'&#9654; <a href="{_esc(url)}" style="color:#58a6ff;">Video attachment</a>'
                    f"</span>"
                )
            else:
                data_uri = self._img_cache.get(url, "")
                if data_uri:
                    media_html = (
                        f'<br><img src="{data_uri}" '
                        f'width="200" style="border-radius:4px;margin-top:4px;" />'
                    )
                else:
                    media_html = (
                        '<br><span style="color:#484f58;font-size:12px;">'
                        "[image loading…]</span>"
                    )

        return (
            f'<div style="margin:3px 0;text-align:{align}">'
            f'<span style="color:#484f58;font-size:12px">{ts}{scope_tag}&nbsp;</span>'
            f"{src_badge}"
            f'<b style="color:{color_sender}">{_esc(sender)}</b>'
            f'<br><span style="color:#c9d1d9;font-size:13px">'
            f"&nbsp;&nbsp;{_esc(content)}"
            f"</span>"
            f"{media_html}"
            f"</div>"
        )

    # ---- Private ----------------------------------------------------------

    def _on_scope_changed(self, scope: str):
        show_recipient = scope in (SCOPE_DIRECT, SCOPE_ROOM)
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
        elif scope == SCOPE_ROOM:
            for r in self._rooms:
                n = r.get("name", "?")
                # Mark ATAK-imported rooms; native (ARROW) rooms stay unmarked.
                tag = " · TAK" if (r.get("origin") or "ARROW").upper() == "ATAK" else ""
                self._recipient_combo.addItem(f"# {n}{tag}", userData=r.get("id"))
        self._recipient_combo.blockSignals(False)

    def _pick_attachment(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach Photo or Video",
            "",
            "Media (*.jpg *.jpeg *.png *.gif *.webp *.mp4 *.webm *.mov *.ogv);;All Files (*)",
        )
        if path:
            self._pending_file = path
            self._attach_label.setText(f"📎 {Path(path).name}")
            self._attach_bar.setVisible(True)

    def _clear_attachment(self):
        self._pending_file = None
        self._attach_bar.setVisible(False)

    def _send(self):
        content = self._input.toPlainText().strip()
        file_path = self._pending_file
        if not content and file_path is None:
            return
        scope = self._scope_combo.currentText()
        receiver_id = None
        target_id = None  # chatroom_id for ROOM scope

        if scope == SCOPE_DIRECT:
            receiver_id = self._recipient_combo.currentData()
            if receiver_id is None:
                return
        elif scope == SCOPE_ROOM:
            target_id = self._recipient_combo.currentData()
            if target_id is None:
                return

        self.message_send_requested.emit(
            content, scope, receiver_id, target_id, file_path
        )
        self._input.clear()
        self._clear_attachment()


class _ComposeField(QTextEdit):
    send_triggered = pyqtSignal()

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            e.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.send_triggered.emit()
        else:
            super().keyPressEvent(e)


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
