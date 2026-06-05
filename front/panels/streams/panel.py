"""Streams Panel — live Android streams, Octopus, external, recordings."""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QFrame, QTabWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont

# Store stream type inside the data dict under this key
_TYPE_KEY = "__arrow_stream_type__"


class StreamsPanel(QWidget):
    stream_open_requested    = pyqtSignal(dict, str)   # stream_info, stream_type
    recording_open_requested = pyqtSignal(dict)
    external_add_requested   = pyqtSignal()
    refresh_requested        = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 6, 8, 4)
        hdr.addWidget(QLabel("STREAMS",
            styleSheet="color:#8b949e;font-size:12px;font-weight:700;letter-spacing:2px;"))
        hdr.addStretch()
        r = QPushButton("⟳")
        r.setFixedSize(26, 24)
        r.setToolTip("Reload streams from server")
        r.setStyleSheet("QPushButton{background:#21262d;border:1px solid #30363d;"
                        "color:#8b949e;font-size:15px;border-radius:2px;}"
                        "QPushButton:hover{color:#c9d1d9;}")
        r.clicked.connect(self.refresh_requested.emit)
        hdr.addWidget(r)
        root.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFixedHeight(1)
        root.addWidget(sep)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(
            "QTabBar::tab{font-size:11px;padding:4px 8px;letter-spacing:1px;}")

        # LIVE
        self._live_list = self._make_list()
        self._live_list.itemDoubleClicked.connect(self._on_live_click)
        self._tabs.addTab(self._live_list, "LIVE")

        # EXTERNAL
        ext_w = QWidget(); ev = QVBoxLayout(ext_w); ev.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton("+ Add Stream")
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(
            "QPushButton{background:#1f6feb;border:1px solid #388bfd;"
            "color:#fff;font-size:12px;font-weight:700;padding:0 10px;"
            "border-radius:2px;margin:4px 6px;}"
            "QPushButton:hover{background:#388bfd;}")
        add_btn.clicked.connect(self.external_add_requested.emit)
        ev.addWidget(add_btn)
        self._ext_list = self._make_list()
        self._ext_list.itemDoubleClicked.connect(self._on_ext_click)
        ev.addWidget(self._ext_list, 1)
        self._tabs.addTab(ext_w, "EXTERNAL")

        # OCTOPUS
        self._oct_list = self._make_list()
        self._oct_list.itemDoubleClicked.connect(self._on_oct_click)
        self._tabs.addTab(self._oct_list, "OCTOPUS")

        # RECORDINGS
        self._rec_list = self._make_list()
        self._rec_list.itemDoubleClicked.connect(self._on_rec_click)
        self._tabs.addTab(self._rec_list, "RECORDINGS")

        root.addWidget(self._tabs, 1)

        self._counter = QLabel("—")
        self._counter.setObjectName("statusSmall")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setContentsMargins(6, 4, 6, 4)
        root.addWidget(self._counter)

    def _make_list(self) -> QListWidget:
        lst = QListWidget()
        lst.setFont(QFont("Courier New", 13))
        lst.setAlternatingRowColors(True)
        return lst

    # ── Public API ──────────────────────────────────────────────────────────────

    def load_live_streams(self, streams: list[dict]):
        self._live_list.clear()
        if not streams:
            self._placeholder(self._live_list, "No active streams")
        else:
            for s in streams:
                viewers = s.get("viewers", 0)
                text = f"  📡  {s.get('callsign','?')}   [{viewers} viewer{'s' if viewers!=1 else ''}]"
                self._add_item(self._live_list, text, "#3fb950",
                               {**s, _TYPE_KEY: "ws_jpeg"})
        n = len(streams)
        self._counter.setText(f"{n} live  ·  double-click to view")

    def load_external_streams(self, streams: list[dict]):
        self._ext_list.clear()
        if not streams:
            self._placeholder(self._ext_list, "No external streams  (+ Add)")
        else:
            for s in streams:
                stype = s.get("stream_type", "?").upper()
                text  = f"  📺  {s.get('name','?')}   [{stype}]"
                self._add_item(self._ext_list, text, "#79c0ff",
                               {**s, _TYPE_KEY: "external"})

    def load_octopus_streams(self, streams: list[dict]):
        self._oct_list.clear()
        if not streams:
            self._placeholder(self._oct_list, "No Octopus streams / server offline")
        else:
            for s in streams:
                text = f"  🎥  {s.get('name') or s.get('id','?')}"
                self._add_item(self._oct_list, text, "#d2a8ff",
                               {**s, _TYPE_KEY: "hls"})

    def load_recordings(self, recs: list[dict]):
        self._rec_list.clear()
        if not recs:
            self._placeholder(self._rec_list, "No recordings")
            return
        for r in recs:
            ts  = (r.get("started_at") or "")[:16]
            dur = _duration(r)
            text = f"  ⏺  {r.get('callsign','?')}   {ts}  {dur}"
            self._add_item(self._rec_list, text, "#8b949e",
                           {**r, _TYPE_KEY: "recording"})

    def add_live_stream(self, stream: dict):
        """Called on WS stream.started event."""
        existing = {
            self._live_list.item(i).data(Qt.ItemDataRole.UserRole).get("id")
            for i in range(self._live_list.count())
            if isinstance(self._live_list.item(i).data(Qt.ItemDataRole.UserRole), dict)
        }
        sid = stream.get("id") or stream.get("stream_id", "")
        if sid not in existing:
            # Remove "No active streams" placeholder if present
            for i in range(self._live_list.count()):
                if self._live_list.item(i).flags() == Qt.ItemFlag.NoItemFlags:
                    self._live_list.takeItem(i)
                    break
            text = f"  📡  {stream.get('callsign','?')}   [LIVE]"
            self._add_item(self._live_list, text, "#3fb950",
                           {**stream, _TYPE_KEY: "ws_jpeg"})
            self._counter.setText(f"{self._live_list.count()} live")

    def remove_live_stream(self, stream_id: str):
        for i in range(self._live_list.count()):
            it = self._live_list.item(i)
            d  = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(d, dict) and d.get("id") == stream_id:
                self._live_list.takeItem(i)
                return

    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _add_item(lst: QListWidget, text: str, color: str, data: dict):
        item = QListWidgetItem(text)
        item.setForeground(QBrush(QColor(color)))
        item.setData(Qt.ItemDataRole.UserRole, data)   # single role — type embedded in dict
        lst.addItem(item)

    @staticmethod
    def _placeholder(lst: QListWidget, text: str):
        it = QListWidgetItem(f"  {text}")
        it.setForeground(QBrush(QColor("#484f58")))
        it.setFlags(Qt.ItemFlag.NoItemFlags)
        lst.addItem(it)

    # ── Click handlers ──────────────────────────────────────────────────────────

    def _emit(self, item: QListWidgetItem):
        d = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(d, dict):
            return
        stype = d.get(_TYPE_KEY, "unknown")
        self.stream_open_requested.emit(d, stype)

    def _on_live_click(self, item: QListWidgetItem): self._emit(item)
    def _on_ext_click(self,  item: QListWidgetItem): self._emit(item)
    def _on_oct_click(self,  item: QListWidgetItem): self._emit(item)
    def _on_rec_click(self,  item: QListWidgetItem):
        d = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(d, dict):
            self.recording_open_requested.emit(d)


def _duration(rec: dict) -> str:
    if not rec.get("started_at") or not rec.get("ended_at"):
        return ""
    try:
        from datetime import datetime
        s = datetime.fromisoformat(rec["started_at"].replace("Z",""))
        e = datetime.fromisoformat(rec["ended_at"].replace("Z",""))
        secs = int((e - s).total_seconds())
        return f"{secs//60}m{secs%60:02d}s"
    except Exception:
        return ""
