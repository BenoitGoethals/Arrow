"""Media Gallery Panel — browse all photos and videos stored on the server."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QScrollArea,
    QGridLayout,
    QDialog,
    QFileDialog,
    QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont
import urllib.request


class _FetchThread(QThread):
    done = pyqtSignal(list)  # list[dict]
    error = pyqtSignal(str)

    def __init__(self, client):
        super().__init__()
        self._client = client

    def run(self):
        try:
            items = self._client.photos()
            self.done.emit(items)
        except Exception as e:
            self.error.emit(str(e))


_THUMB_BATCH = 4  # max simultaneous thumbnail downloads


class _ThumbThread(QThread):
    # Emit raw bytes only — QPixmap must be created on the main thread
    loaded = pyqtSignal(int, bytes)  # photo_id, image_bytes

    def __init__(self, photo_id: int, url: str, token: str):
        super().__init__()
        self._photo_id = photo_id
        self._url = url
        self._token = token

    def run(self):
        try:
            req = urllib.request.Request(
                self._url,
                headers={"Authorization": f"Bearer {self._token}"},
            )
            from front.utils.ssl_utils import NO_VERIFY_CTX

            with urllib.request.urlopen(req, timeout=10, context=NO_VERIFY_CTX) as resp:
                data = resp.read()
            self.loaded.emit(self._photo_id, data)
        except Exception:
            pass


class _ThumbCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self._item = item
        self.setFixedSize(128, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame{background:#161b22;border:1px solid #21262d;border-radius:4px;}"
            "QFrame:hover{border-color:#388bfd;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._thumb = QLabel()
        self._thumb.setFixedSize(120, 104)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("background:#0d1117;border-radius:2px;")

        is_video = (item.get("mime_type", "")).startswith("video/")
        if is_video:
            self._thumb.setText("▶")
            self._thumb.setStyleSheet(
                "background:#0d1117;color:#388bfd;font-size:32px;border-radius:2px;"
            )

        name = item.get("original_name") or item.get("filename") or ""
        lbl = QLabel(name)
        lbl.setFont(QFont("Courier New", 10))
        lbl.setStyleSheet("color:#8b949e;")
        lbl.setMaximumWidth(120)
        lbl.setWordWrap(False)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        layout.addWidget(self._thumb)
        layout.addWidget(lbl)

    def set_pixmap(self, px: QPixmap):
        self._thumb.setPixmap(px)
        self._thumb.setStyleSheet("background:#0d1117;border-radius:2px;")

    def mousePressEvent(self, _event):
        self.clicked.emit(self._item)


class _ImageViewer(QDialog):
    def __init__(self, url: str, token: str, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(640, 480)
        self.setStyleSheet("background:#000;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel("Loading…")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color:#8b949e;")
        layout.addWidget(self._label)

        # Thread only downloads bytes; pixmap is created here on the main thread
        self._thread = _ThumbThread(0, url, token)
        self._thread.loaded.connect(self._show)
        self._thread.start()

    def _show(self, _photo_id: int, data: bytes):
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            self._label.setPixmap(
                px.scaled(
                    self._label.width() or 640,
                    self._label.height() or 480,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class MediaPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        self._token: str = ""
        self._items: list[dict] = []
        self._thumb_threads: list[_ThumbThread] = []
        self._pending_thumbs: list[tuple[int, str]] = []  # (photo_id, url) queue
        self._active_count: int = 0
        self._cards: dict[int, _ThumbCard] = {}
        self._fetch_thread: _FetchThread | None = None
        self._build_ui()

    def set_client(self, client):
        self._client = client
        self._token = client.token or ""

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ────────────────────────────────────────────────────
        bar = QFrame()
        bar.setStyleSheet("background:#161b22;border-bottom:1px solid #21262d;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(6, 4, 6, 4)
        bar_layout.setSpacing(6)

        title = QLabel("MEDIA GALLERY")
        title.setFont(QFont("Courier New", 12))
        title.setStyleSheet("color:#6e7681;font-weight:700;letter-spacing:1px;")
        bar_layout.addWidget(title, 1)

        upload_btn = QPushButton("+ Upload")
        upload_btn.setFixedHeight(24)
        upload_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#c9d1d9;font-size:13px;border-radius:2px;padding:0 8px;}"
            "QPushButton:hover{border-color:#388bfd;color:#58a6ff;}"
        )
        upload_btn.clicked.connect(self._upload)

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#c9d1d9;font-size:14px;border-radius:2px;}"
            "QPushButton:hover{border-color:#388bfd;}"
        )
        refresh_btn.clicked.connect(self.refresh)

        bar_layout.addWidget(upload_btn)
        bar_layout.addWidget(refresh_btn)
        root.addWidget(bar)

        # ── Status label ───────────────────────────────────────────────
        self._status = QLabel("Click ↻ to load media")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color:#6e7681;font-size:12px;padding:4px;")
        root.addWidget(self._status)

        # ── Scroll grid ────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:#0d1117;}")

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background:#0d1117;")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setSpacing(6)

        scroll.setWidget(self._grid_widget)
        root.addWidget(scroll, 1)

    def refresh(self):
        if self._client is None:
            self._status.setText("Not connected")
            return
        self._status.setText("Loading…")
        self._clear_grid()
        self._fetch_thread = _FetchThread(self._client)
        self._fetch_thread.done.connect(self._on_fetched)
        self._fetch_thread.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._fetch_thread.start()

    def _on_fetched(self, items: list[dict]):
        self._items = items
        count = len(items)
        self._status.setText(f"{count} item{'s' if count != 1 else ''}")
        self._populate(items)

    def _clear_grid(self):
        self._cards.clear()
        self._pending_thumbs.clear()
        self._active_count = 0
        for t in self._thumb_threads:
            t.quit()
        self._thumb_threads.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _populate(self, items: list[dict]):
        cols = 3
        self._pending_thumbs.clear()
        for i, item in enumerate(items):
            card = _ThumbCard(item)
            card.clicked.connect(self._open_item)
            self._grid.addWidget(card, i // cols, i % cols)
            pid = item.get("id")
            if pid is not None:
                self._cards[pid] = card
                is_video = (item.get("mime_type", "")).startswith("video/")
                if not is_video and self._client:
                    self._pending_thumbs.append((pid, self._client.photo_url(pid)))
        # Start first batch
        for _ in range(_THUMB_BATCH):
            self._start_next_thumb()

    def _start_next_thumb(self):
        if not self._pending_thumbs:
            return
        pid, url = self._pending_thumbs.pop(0)
        t = _ThumbThread(pid, url, self._token)
        t.loaded.connect(self._on_thumb)
        t.finished.connect(self._on_thumb_finished)
        t.start()
        self._thumb_threads.append(t)
        self._active_count += 1

    def _on_thumb_finished(self):
        self._active_count = max(0, self._active_count - 1)
        self._start_next_thumb()

    def _on_thumb(self, photo_id: int, data: bytes):
        # QPixmap created here on the main thread — never in the worker thread
        card = self._cards.get(photo_id)
        if card and data:
            px = QPixmap()
            px.loadFromData(data)
            if not px.isNull():
                px = px.scaled(
                    120,
                    120,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                card.set_pixmap(px)

    def _open_item(self, item: dict):
        if self._client is None:
            return
        pid = item.get("id")
        if pid is None:
            return
        url = self._client.photo_url(pid)
        mime = item.get("mime_type", "")
        name = item.get("original_name") or item.get("filename") or str(pid)

        if mime.startswith("video/"):
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.information(
                self,
                "Video",
                f"Video: {name}\n\nURL:\n{url}\n\n"
                "Open this URL in a media player to play the video.",
            )
        else:
            viewer = _ImageViewer(url, self._token, name, parent=self)
            viewer.exec()

    def _upload(self):
        if self._client is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Photos or Videos",
            "",
            "Media (*.jpg *.jpeg *.png *.gif *.webp *.mp4 *.webm *.mov *.ogv);;All Files (*)",
        )
        if not paths:
            return
        ok = 0
        fail = 0
        for p in paths:
            try:
                self._client.upload_media(p)
                ok += 1
            except Exception:
                fail += 1
        msg = f"Uploaded {ok} file{'s' if ok != 1 else ''}"
        if fail:
            msg += f", {fail} failed"
        self._status.setText(msg)
        self.refresh()
