"""MBTiles layer manager — CRUD dialog for offline tile overlays.

Two tabs:
  LOCAL LAYERS — list loaded overlays, toggle visibility, remove
  FROM SERVER  — browse server sources, download with progress
"""
from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QTabWidget, QProgressBar,
    QSizePolicy,
)

_DOWNLOAD_DIR = Path.home() / ".arrow_front" / "maps"


# ── Background workers ────────────────────────────────────────────────────────

class _FetchWorker(QObject):
    """Fetches source list from server in a thread."""
    finished = pyqtSignal(list)   # list[dict]
    error    = pyqtSignal(str)

    def __init__(self, client):
        super().__init__()
        self._client = client

    def run(self):
        try:
            sources = self._client.map_sources()
            self.finished.emit([s for s in sources if s.get("downloadable")])
        except Exception as exc:
            self.error.emit(str(exc))


class _DownloadWorker(QObject):
    """Streams one MBTiles file from the server to disk."""
    progress  = pyqtSignal(int, int)   # done_bytes, total_bytes
    finished  = pyqtSignal(str)        # dest_path
    error     = pyqtSignal(str)

    def __init__(self, client, name: str, dest_path: str):
        super().__init__()
        self._client    = client
        self._name      = name
        self._dest_path = dest_path
        self._stop      = threading.Event()

    def cancel(self):
        self._stop.set()

    def run(self):
        try:
            self._client.download_mbtiles(
                self._name, self._dest_path,
                on_progress=lambda d, t: self.progress.emit(d, t),
                stop_event=self._stop,
            )
            if not self._stop.is_set():
                self.finished.emit(self._dest_path)
        except InterruptedError:
            pass
        except Exception as exc:
            self.error.emit(str(exc))


# ── Main dialog ───────────────────────────────────────────────────────────────

class MBTilesDialog(QDialog):
    """Floating manager for MBTiles overlays.

    Keep one instance; call ``refresh(layers)`` and ``set_client(client)``
    as state changes.

    Signals
    -------
    add_requested(path)          — load this file as a local overlay
    remove_requested(mbt_id)     — unload and remove overlay
    toggle_requested(mbt_id, on) — change overlay visibility
    """

    add_requested    = pyqtSignal(str)        # file path
    remove_requested = pyqtSignal(str)        # mbt_id
    toggle_requested = pyqtSignal(str, bool)  # mbt_id, visible

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MBTiles Layers")
        self.setMinimumSize(500, 340)
        self.setMaximumWidth(620)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        )
        self._layers: dict[str, dict] = {}
        self._client = None
        self._server_sources: list[dict] = []
        self._dl_thread: QThread | None  = None
        self._dl_worker: _DownloadWorker | None = None
        self._dl_name   = ""
        self._build()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_client(self, client):
        self._client = client

    def refresh(self, layers: dict[str, dict]):
        self._layers = dict(layers)
        self._rebuild_local()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet("background:#161b22;border-bottom:1px solid #30363d;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("◆  MBTILES LAYERS")
        title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:#3fb950;letter-spacing:2px;")
        hl.addWidget(title)
        hl.addStretch()
        root.addWidget(hdr)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._build_local_tab(),  "LOCAL LAYERS")
        self._tabs.addTab(self._build_server_tab(), "FROM SERVER")
        root.addWidget(self._tabs, 1)

    # ── Local layers tab ──────────────────────────────────────────────────────

    def _build_local_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#0d1117;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._local_list = QWidget()
        self._local_list.setStyleSheet("background:#0d1117;")
        self._local_layout = QVBoxLayout(self._local_list)
        self._local_layout.setContentsMargins(8, 8, 8, 8)
        self._local_layout.setSpacing(4)
        self._local_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._local_list)
        scroll.setStyleSheet("QScrollArea{border:none;background:#0d1117;}")
        lay.addWidget(scroll, 1)

        # Footer: Add button
        ftr = QFrame()
        ftr.setFixedHeight(50)
        ftr.setStyleSheet("background:#161b22;border-top:1px solid #30363d;")
        fl = QHBoxLayout(ftr)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.addStretch()
        add_btn = QPushButton("📂  Add file…")
        add_btn.setObjectName("primaryButton")
        add_btn.setFixedWidth(140)
        add_btn.clicked.connect(self._pick_file)
        fl.addWidget(add_btn)
        lay.addWidget(ftr)
        return w

    def _rebuild_local(self):
        while self._local_layout.count() > 1:
            item = self._local_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._layers:
            empty = QLabel("No MBTiles layers loaded")
            empty.setStyleSheet("color:#484f58;font-size:10px;padding:12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._local_layout.insertWidget(0, empty)
            return

        for mbt_id, info in self._layers.items():
            self._local_layout.insertWidget(
                self._local_layout.count() - 1,
                self._make_local_row(mbt_id, info),
            )

    def _make_local_row(self, mbt_id: str, info: dict) -> QFrame:
        row = QFrame()
        row.setFixedHeight(46)
        row.setStyleSheet(
            "QFrame{background:#161b22;border:1px solid #21262d;border-radius:4px;}"
            "QFrame:hover{border-color:#30363d;}"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 0, 8, 0)
        rl.setSpacing(8)

        visible = info.get("visible", True)
        eye_btn = QPushButton("👁" if visible else "⊘")
        eye_btn.setFixedSize(30, 30)
        eye_btn.setCheckable(True)
        eye_btn.setChecked(visible)
        eye_btn.setToolTip("Toggle visibility")
        eye_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;font-size:14px;}"
            "QPushButton:hover{background:#21262d;border-radius:4px;}"
        )
        eye_btn.clicked.connect(lambda checked, mid=mbt_id: self.toggle_requested.emit(mid, checked))
        rl.addWidget(eye_btn)

        name    = info.get("name", mbt_id)
        z_min   = info.get("min_zoom", 0)
        z_max   = info.get("max_zoom", 18)
        fname   = Path(info.get("path", "")).name
        col = QVBoxLayout()
        col.setSpacing(1)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"color:{'#e6edf3' if visible else '#484f58'};font-size:11px;font-weight:600;"
        )
        meta_lbl = QLabel(f"z{z_min}–{z_max}  ·  {fname}")
        meta_lbl.setStyleSheet("color:#484f58;font-size:9px;")
        col.addWidget(name_lbl)
        col.addWidget(meta_lbl)
        rl.addLayout(col, 1)

        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(26, 26)
        rm_btn.setToolTip("Remove layer")
        rm_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#484f58;font-size:12px;}"
            "QPushButton:hover{color:#f85149;background:#21262d;border-radius:4px;}"
        )
        rm_btn.clicked.connect(lambda _, mid=mbt_id: self.remove_requested.emit(mid))
        rl.addWidget(rm_btn)
        return row

    def _pick_file(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Open MBTiles", "", "MBTiles files (*.mbtiles *.mb)"
        )
        if path:
            self.add_requested.emit(path)

    # ── From Server tab ───────────────────────────────────────────────────────

    def _build_server_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#0d1117;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Toolbar row
        bar = QFrame()
        bar.setFixedHeight(42)
        bar.setStyleSheet("background:#0d1117;border-bottom:1px solid #21262d;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 10, 0)
        self._srv_status = QLabel("Click Refresh to list server sources")
        self._srv_status.setStyleSheet("color:#484f58;font-size:10px;")
        bl.addWidget(self._srv_status, 1)
        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self._fetch_sources)
        bl.addWidget(refresh_btn)
        lay.addWidget(bar)

        # Source list
        self._srv_list = QWidget()
        self._srv_list.setStyleSheet("background:#0d1117;")
        self._srv_layout = QVBoxLayout(self._srv_list)
        self._srv_layout.setContentsMargins(8, 8, 8, 8)
        self._srv_layout.setSpacing(4)
        self._srv_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._srv_list)
        scroll.setStyleSheet("QScrollArea{border:none;background:#0d1117;}")
        lay.addWidget(scroll, 1)

        # Progress bar (hidden until download starts)
        self._progress_frame = QFrame()
        self._progress_frame.setFixedHeight(46)
        self._progress_frame.setStyleSheet(
            "background:#161b22;border-top:1px solid #30363d;"
        )
        pfl = QHBoxLayout(self._progress_frame)
        pfl.setContentsMargins(12, 6, 12, 6)
        self._progress_lbl = QLabel("")
        self._progress_lbl.setStyleSheet("color:#8b949e;font-size:9px;min-width:140px;")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(12)
        self._progress_bar.setTextVisible(False)
        self._cancel_btn = QPushButton("✕ Cancel")
        self._cancel_btn.setFixedWidth(80)
        self._cancel_btn.clicked.connect(self._cancel_download)
        pfl.addWidget(self._progress_lbl)
        pfl.addWidget(self._progress_bar, 1)
        pfl.addWidget(self._cancel_btn)
        self._progress_frame.hide()
        lay.addWidget(self._progress_frame)

        return w

    def _fetch_sources(self):
        if not self._client:
            self._srv_status.setText("No server connection")
            return
        self._srv_status.setText("Fetching…")

        worker = _FetchWorker(self._client)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_sources_fetched)
        worker.error.connect(lambda e: self._srv_status.setText(f"Error: {e}"))
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()

    def _on_sources_fetched(self, sources: list):
        self._server_sources = sources
        count = len(sources)
        self._srv_status.setText(f"{count} downloadable source{'s' if count != 1 else ''}")
        self._rebuild_server_list()

    def _rebuild_server_list(self):
        while self._srv_layout.count() > 1:
            item = self._srv_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._server_sources:
            empty = QLabel("No downloadable sources on server")
            empty.setStyleSheet("color:#484f58;font-size:10px;padding:12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._srv_layout.insertWidget(0, empty)
            return

        loaded_paths = {v["path"] for v in self._layers.values()}

        for src in self._server_sources:
            self._srv_layout.insertWidget(
                self._srv_layout.count() - 1,
                self._make_server_row(src, loaded_paths),
            )

    def _make_server_row(self, src: dict, loaded_paths: set) -> QFrame:
        row = QFrame()
        row.setFixedHeight(50)
        row.setStyleSheet(
            "QFrame{background:#161b22;border:1px solid #21262d;border-radius:4px;}"
            "QFrame:hover{border-color:#30363d;}"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 0, 8, 0)
        rl.setSpacing(10)

        col = QVBoxLayout()
        col.setSpacing(1)
        title_lbl = QLabel(src.get("title") or src.get("name", "?"))
        title_lbl.setStyleSheet("color:#e6edf3;font-size:11px;font-weight:600;")
        z_min = src.get("min_zoom", 0)
        z_max = src.get("max_zoom", 18)
        size  = src.get("size_bytes") or 0
        size_str = _fmt_size(size)
        meta_lbl = QLabel(f"z{z_min}–{z_max}  ·  {size_str}")
        meta_lbl.setStyleSheet("color:#484f58;font-size:9px;")
        col.addWidget(title_lbl)
        col.addWidget(meta_lbl)
        rl.addLayout(col, 1)

        name = src.get("name", "")
        dest = str(_DOWNLOAD_DIR / f"{name}.mbtiles")
        already_loaded = dest in loaded_paths

        dl_btn = QPushButton("✓ Loaded" if already_loaded else "⬇  Download")
        dl_btn.setFixedWidth(100)
        dl_btn.setEnabled(not already_loaded and self._dl_thread is None)
        dl_btn.setStyleSheet(
            "QPushButton{background:#1f6feb;border:none;color:#fff;"
            "font-size:10px;padding:4px 8px;border-radius:3px;}"
            "QPushButton:hover{background:#388bfd;}"
            "QPushButton:disabled{background:#21262d;color:#484f58;}"
        )
        if not already_loaded:
            dl_btn.clicked.connect(
                lambda _, n=name, d=dest, b=dl_btn: self._start_download(n, d, b)
            )
        rl.addWidget(dl_btn)
        return row

    # ── Download management ───────────────────────────────────────────────────

    def _start_download(self, name: str, dest_path: str, btn: QPushButton):
        if self._dl_thread and self._dl_thread.isRunning():
            return
        _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        self._dl_name = name
        btn.setEnabled(False)
        btn.setText("Downloading…")

        worker = _DownloadWorker(self._client, name, dest_path)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(lambda p, b=btn: self._on_dl_finished(p, b))
        worker.error.connect(lambda e, b=btn: self._on_dl_error(e, b))
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)

        self._dl_worker = worker
        self._dl_thread = thread

        self._progress_bar.setValue(0)
        self._progress_lbl.setText(f"Downloading {name}…")
        self._progress_frame.show()

        thread.start()

    def _on_progress(self, done: int, total: int):
        pct = int(done * 100 / total) if total > 0 else 0
        self._progress_bar.setValue(pct)
        self._progress_lbl.setText(
            f"{_fmt_size(done)} / {_fmt_size(total)}  ({pct}%)"
        )

    def _on_dl_finished(self, path: str, btn: QPushButton):
        self._dl_thread = None
        self._dl_worker = None
        self._progress_frame.hide()
        btn.setText("✓ Loaded")
        btn.setEnabled(False)
        self.add_requested.emit(path)

    def _on_dl_error(self, msg: str, btn: QPushButton):
        self._dl_thread = None
        self._dl_worker = None
        self._progress_frame.hide()
        btn.setText("⬇  Download")
        btn.setEnabled(True)
        self._srv_status.setText(f"Download failed: {msg}")

    def _cancel_download(self):
        if self._dl_worker:
            self._dl_worker.cancel()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(b: int) -> str:
    if b <= 0:
        return "?"
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024 ** 3:.2f} GB"
