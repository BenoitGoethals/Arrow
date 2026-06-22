"""OPORD Editor/Viewer Window — mirrors the Arrow web OPORD editor.

Opens in view mode for existing OPORDs or edit mode for new ones.
Paragraphs: Header · 1.Situation · 2.Mission · 3.Execution ·
            4.Sustainment · 5.Command & Signal · Snapshots · Distribution
"""

from __future__ import annotations
import base64
import json
import urllib.request
from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QScrollArea,
    QStackedWidget,
    QSplitter,
    QMessageBox,
    QSizePolicy,
    QFileDialog,
    QInputDialog,
    QGridLayout,
)
from PyQt6.QtCore import Qt, QThread, QBuffer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut, QFont, QPixmap


def _pixmap_to_b64(px: "QPixmap") -> str:
    """Encode a QPixmap as a base64 PNG string."""
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    px.save(buf, "PNG")
    return base64.b64encode(bytes(buf.data())).decode("ascii")


class _SnapCard(QFrame):
    """Thumbnail card for a single OPORD snapshot."""

    delete_requested = pyqtSignal(int)  # snap_id

    _CARD_W = 240
    _THUMB_H = 160

    def __init__(self, snap: dict, parent=None):
        super().__init__(parent)
        self._snap_id = snap.get("id", 0)
        self.setFixedWidth(self._CARD_W)
        self.setStyleSheet(
            "QFrame{background:#161b22;border:1px solid #30363d;border-radius:4px;}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(4)

        # Thumbnail area
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(self._CARD_W - 2, self._THUMB_H)
        self._thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_lbl.setStyleSheet(
            "background:#0d1117;border:none;border-radius:3px 3px 0 0;"
            "color:#484f58;font-size:20px;"
        )
        self._thumb_lbl.setText("🖼")
        lay.addWidget(self._thumb_lbl)

        # Label + delete row
        row = QHBoxLayout()
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(4)

        label_text = snap.get("label") or snap.get("annotations") or "Snapshot"
        lbl = QLabel(label_text)
        lbl.setStyleSheet(
            "color:#c9d1d9;font-size:9px;border:none;background:transparent;"
        )
        lbl.setWordWrap(True)
        row.addWidget(lbl, 1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(18, 18)
        del_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#484f58;border:none;font-size:10px;}"
            "QPushButton:hover{color:#f85149;}"
        )
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._snap_id))
        row.addWidget(del_btn)
        lay.addLayout(row)

    def set_pixmap(self, px: "QPixmap"):
        scaled = px.scaled(
            self._CARD_W - 2,
            self._THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_lbl.setPixmap(scaled)
        self._thumb_lbl.setText("")


class _ThumbLoader(QThread):
    """Download one image with Bearer auth; emit raw bytes on main thread."""

    loaded = pyqtSignal(int, bytes)  # snap_id, data

    def __init__(self, snap_id: int, url: str, token: str):
        super().__init__()
        self._snap_id = snap_id
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
            self.loaded.emit(self._snap_id, data)
        except Exception:
            pass


# ── Helpers ────────────────────────────────────────────────────────────────────

_MONO = QFont("Courier New", 10)
_SANS = QFont("Segoe UI", 10)
_SEP_STYLE = "background:#21262d;max-height:1px;"
_HDR_STYLE = (
    "color:#8b949e;font-size:9px;font-weight:700;"
    "letter-spacing:2px;text-transform:uppercase;"
    "padding:8px 0 3px;"
)
_FIELD_STYLE = (
    "QLineEdit,QTextEdit,QComboBox{"
    "background:#161b22;border:1px solid #30363d;"
    "color:#c9d1d9;border-radius:2px;padding:4px 6px;}"
    "QLineEdit:focus,QTextEdit:focus{border-color:#388bfd;}"
    "QComboBox QAbstractItemView{background:#161b22;color:#c9d1d9;}"
)


def _make_label(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(_HDR_STYLE)
    return l


def _make_field(placeholder: str = "", height: int = 0) -> QTextEdit:
    f = QTextEdit()
    f.setFont(_MONO)
    f.setPlaceholderText(placeholder)
    f.setStyleSheet(_FIELD_STYLE)
    if height:
        f.setFixedHeight(height)
    else:
        f.setMinimumHeight(80)
    return f


def _make_line(placeholder: str = "") -> QLineEdit:
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    f.setFont(_MONO)
    f.setStyleSheet(_FIELD_STYLE)
    return f


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(_SEP_STYLE)
    f.setFixedHeight(1)
    return f


def _scroll_wrap(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setStyleSheet("QScrollArea{background:#0d1117;}")
    sa.setWidget(widget)
    return sa


def _to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        return json.dumps(v, indent=2, ensure_ascii=False)
    return str(v)


def _from_json(text: str):
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return text


# ── Sidebar nav button ─────────────────────────────────────────────────────────


class _NavBtn(QPushButton):
    def __init__(self, text: str):
        super().__init__(text)
        self.setCheckable(True)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            QPushButton{background:none;border:none;border-left:3px solid transparent;
                        color:#6e7681;font-family:'Courier New',monospace;
                        font-size:10px;text-align:left;padding:0 10px;}
            QPushButton:hover:!checked{color:#c9d1d9;background:#161b22;}
            QPushButton:checked{color:#79c0ff;border-left-color:#1f6feb;background:#0d1117;}
        """)


# ── OPORD Window ───────────────────────────────────────────────────────────────


class OpordWindow(QMainWindow):
    """View or edit an OPORD. Pass opord_data=None to create a new one."""

    saved = pyqtSignal(dict)  # emitted after successful save
    published = pyqtSignal(dict)  # emitted after publish

    def __init__(
        self,
        client,
        opord_data: Optional[dict] = None,
        map_capture_fn: Optional[Callable] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._client = client
        self._opord = opord_data or {}
        self._opord_id: Optional[int] = opord_data.get("id") if opord_data else None
        self._is_new = self._opord_id is None
        self._map_capture_fn = map_capture_fn  # callable → QPixmap | None
        self._thumb_loaders: list[_ThumbLoader] = []
        self._snap_cards: dict[int, _SnapCard] = {}  # snap_id → card widget

        title = self._opord.get("title", "New OPORD") if opord_data else "New OPORD"
        self.setWindowTitle(f"OPORD — {title}")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(1100, 800)
        self.setMinimumSize(900, 640)
        self.setStyleSheet("""
            QMainWindow,QWidget{background:#0d1117;color:#c9d1d9;
                font-family:'Segoe UI','Ubuntu',sans-serif;font-size:11px;}
            QScrollBar:vertical{background:#0d1117;width:7px;border:none;}
            QScrollBar::handle:vertical{background:#30363d;border-radius:3px;min-height:20px;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
            QListWidget{background:#0d1117;border:none;color:#c9d1d9;}
            QListWidget::item{padding:3px 6px;}
            QListWidget::item:selected{background:#1c2d3f;color:#79c0ff;}
        """)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)
        self._build()
        self._populate()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Top bar
        top = QFrame()
        top.setFixedHeight(46)
        top.setStyleSheet("background:#161b22;border-bottom:1px solid #21262d;")
        tb = QHBoxLayout(top)
        tb.setContentsMargins(12, 0, 12, 0)

        self._title_label = QLabel("📋 OPORD")
        self._title_label.setStyleSheet("color:#c9d1d9;font-size:12px;font-weight:700;")
        tb.addWidget(self._title_label, 1)

        self._status_badge = QLabel("DRAFT")
        self._status_badge.setStyleSheet(
            "background:#1a1208;color:#d29922;border:1px solid #d29922;"
            "font-size:9px;font-weight:700;padding:2px 8px;border-radius:2px;letter-spacing:1px;"
        )
        tb.addWidget(self._status_badge)

        self._save_btn = QPushButton("💾  SAVE")
        self._save_btn.setStyleSheet(
            "QPushButton{background:#1f6feb;border:1px solid #388bfd;"
            "color:#fff;font-weight:700;padding:5px 14px;border-radius:2px;}"
            "QPushButton:hover{background:#388bfd;}"
        )
        self._save_btn.clicked.connect(self._save)
        tb.addWidget(self._save_btn)

        self._pub_btn = QPushButton("▶  PUBLISH")
        self._pub_btn.setEnabled(False)
        self._pub_btn.setStyleSheet(
            "QPushButton{background:#1a3020;border:1px solid #3fb950;"
            "color:#3fb950;font-weight:700;padding:5px 14px;border-radius:2px;}"
            "QPushButton:hover:!disabled{background:#3fb950;color:#0d1117;}"
            "QPushButton:disabled{color:#30363d;border-color:#21262d;}"
        )
        self._pub_btn.clicked.connect(self._publish)
        tb.addWidget(self._pub_btn)

        self._send_btn = QPushButton("📤  SEND")
        self._send_btn.setEnabled(False)
        self._send_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#8b949e;font-weight:700;padding:5px 14px;border-radius:2px;}"
            "QPushButton:hover:!disabled{background:#30363d;color:#c9d1d9;}"
            "QPushButton:disabled{color:#30363d;border-color:#21262d;}"
        )
        self._send_btn.clicked.connect(self._send)
        tb.addWidget(self._send_btn)

        # Main: sidebar + stacked content
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle{background:#21262d;}")

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("background:#161b22;")
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 8, 0, 8)
        sb.setSpacing(2)

        self._stack = QStackedWidget()
        self._nav_btns: list[_NavBtn] = []

        pages = [
            ("📑  HEADER", self._build_header()),
            ("1.  SITUATION", self._build_situation()),
            ("2.  MISSION", self._build_mission()),
            ("3.  EXECUTION", self._build_execution()),
            ("4.  SUSTAINMENT", self._build_sustainment()),
            ("5.  CMD & SIGNAL", self._build_cs()),
            ("📸  SNAPSHOTS", self._build_snapshots()),
            ("📤  DISTRIBUTION", self._build_distribution()),
        ]
        for i, (label, page) in enumerate(pages):
            btn = _NavBtn(label)
            btn.clicked.connect(lambda checked, idx=i: self._switch(idx))
            self._nav_btns.append(btn)
            sb.addWidget(btn)
            self._stack.addWidget(_scroll_wrap(page))

        sb.addStretch()
        splitter.addWidget(sidebar)
        splitter.addWidget(self._stack)
        splitter.setSizes([200, 900])

        # Root layout
        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(top)
        cv.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self._switch(0)

    def _switch(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)

    # ── Page builders ──────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(8)

        lay.addWidget(_make_label("Title"))
        self._f_title = _make_line("e.g. OPORD 01 — OPERATION STEEL TIDE")
        lay.addWidget(self._f_title)

        row = QHBoxLayout()
        row.setSpacing(8)
        col1 = QVBoxLayout()
        col1.setSpacing(4)
        col1.addWidget(_make_label("OPORD Number"))
        self._f_num = _make_line("01")
        col1.addWidget(self._f_num)

        col2 = QVBoxLayout()
        col2.setSpacing(4)
        col2.addWidget(_make_label("DTG"))
        self._f_dtg = _make_line("011800ZJUN2026")
        col2.addWidget(self._f_dtg)

        col3 = QVBoxLayout()
        col3.setSpacing(4)
        col3.addWidget(_make_label("Time Zone"))
        self._f_tz = _make_line("Z")
        self._f_tz.setFixedWidth(60)
        col3.addWidget(self._f_tz)

        col4 = QVBoxLayout()
        col4.setSpacing(4)
        col4.addWidget(_make_label("Classification"))
        self._f_class = QComboBox()
        self._f_class.addItems(["UNCLASSIFIED", "RESTRICTED", "CONFIDENTIAL", "SECRET"])
        self._f_class.setStyleSheet(_FIELD_STYLE)
        col4.addWidget(self._f_class)

        for c in (col1, col2, col3, col4):
            row.addLayout(c)
        lay.addLayout(row)

        lay.addWidget(_sep())
        lay.addWidget(_make_label("References"))
        self._f_refs = _make_field("Maps, higher OPORDs, SOPs, annexes…", 70)
        lay.addWidget(self._f_refs)

        lay.addWidget(_make_label("Task Organization"))
        self._f_taskorg = _make_field(
            "List assigned/attached units, OPCON/TACON arrangements, effective times…",
            120,
        )
        lay.addWidget(self._f_taskorg)
        lay.addStretch()
        return w

    def _build_situation(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(8)
        lay.addWidget(
            QLabel(
                "PARAGRAPH 1 — SITUATION",
                styleSheet="color:#3fb950;font-size:12px;font-weight:700;padding:0 0 6px;",
            )
        )

        lay.addWidget(_make_label("a. Enemy Forces"))
        self._f_enemy = _make_field(
            "Enemy order of battle, disposition, strengths, capabilities, COAs…", 120
        )
        lay.addWidget(self._f_enemy)

        lay.addWidget(_make_label("b. Friendly Forces"))
        self._f_friendly = _make_field(
            "Higher HQ mission, adjacent units, supporting units…", 100
        )
        lay.addWidget(self._f_friendly)

        lay.addWidget(_make_label("c. Attachments & Detachments"))
        self._f_attach = _make_field("Units attached/detached, effective times…", 60)
        lay.addWidget(self._f_attach)

        lay.addWidget(_make_label("d. Terrain & Weather"))
        self._f_terrain = _make_field(
            "Key terrain, obstacles, avenues of approach, weather impact…", 80
        )
        lay.addWidget(self._f_terrain)

        lay.addStretch()
        return w

    def _build_mission(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(8)
        lay.addWidget(
            QLabel(
                "PARAGRAPH 2 — MISSION",
                styleSheet="color:#3fb950;font-size:12px;font-weight:700;padding:0 0 6px;",
            )
        )
        lay.addWidget(
            QLabel(
                "Who · What · When · Where · Why (5W format)\n"
                "e.g. A COY / 1-75 RGR conducts an air-assault raid on OBJ HAMMER NLT H+45 to DESTROY…",
                styleSheet="color:#6e7681;font-size:9px;",
            )
        )
        self._f_mission = _make_field("", 200)
        lay.addWidget(self._f_mission)
        lay.addStretch()
        return w

    def _build_execution(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(8)
        lay.addWidget(
            QLabel(
                "PARAGRAPH 3 — EXECUTION",
                styleSheet="color:#3fb950;font-size:12px;font-weight:700;padding:0 0 6px;",
            )
        )

        for attr, label, ph in [
            ("_f_intent", "a. Commander's Intent", "End state, key tasks, risk…"),
            (
                "_f_concept",
                "b. Concept of Operations",
                "Scheme of manoeuvre, phase plan, main/supporting efforts…",
            ),
            (
                "_f_tasks",
                "c. Tasks to Manoeuvre Units",
                "By unit: task and purpose for each subordinate element…",
            ),
            (
                "_f_fires",
                "d. Fire Support Plan",
                "Pre-planned fires, CFL/NFL, on-call targets, restrictions…",
            ),
            (
                "_f_roe",
                "e. Rules of Engagement",
                "Positive ID, restricted areas, escalation of force…",
            ),
        ]:
            lay.addWidget(_make_label(label))
            field = _make_field(ph, 100)
            setattr(self, attr, field)
            lay.addWidget(field)

        lay.addStretch()
        return w

    def _build_sustainment(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(8)
        lay.addWidget(
            QLabel(
                "PARAGRAPH 4 — SUSTAINMENT",
                styleSheet="color:#3fb950;font-size:12px;font-weight:700;padding:0 0 6px;",
            )
        )

        for attr, label, ph in [
            (
                "_f_supply",
                "a. Supply",
                "Class I–X, POL, ammunition plan, resupply points…",
            ),
            (
                "_f_maint",
                "b. Maintenance",
                "Vehicle recovery, equipment serviceability SOP…",
            ),
            (
                "_f_medical",
                "c. Medical",
                "9-liner procedures, CASEVAC plan, CCP locations, MEDEVAC strip-alert…",
            ),
            (
                "_f_trans",
                "d. Transportation",
                "Lift plan, serial manifests, chalk load plans…",
            ),
        ]:
            lay.addWidget(_make_label(label))
            field = _make_field(ph, 80)
            setattr(self, attr, field)
            lay.addWidget(field)

        lay.addStretch()
        return w

    def _build_cs(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(8)
        lay.addWidget(
            QLabel(
                "PARAGRAPH 5 — COMMAND & SIGNAL",
                styleSheet="color:#3fb950;font-size:12px;font-weight:700;padding:0 0 6px;",
            )
        )

        for attr, label, ph in [
            ("_f_cp", "a. Command Posts", "CP locations, jump CP, TAC CP…"),
            (
                "_f_succession",
                "b. Succession",
                "CO → XO → OPS → PLT LDR order of succession…",
            ),
            (
                "_f_freqs",
                "c. Radio Frequencies",
                "Primary, alternate, CASEVAC, CAS frequencies…",
            ),
            (
                "_f_signals",
                "d. Signals",
                "Pyros, IR strobes, CEOI references, challenge/password…",
            ),
            (
                "_f_pace",
                "e. PACE Plan",
                "Primary / Alternate / Contingency / Emergency comms…",
            ),
        ]:
            lay.addWidget(_make_label(label))
            field = _make_field(ph, 70)
            setattr(self, attr, field)
            lay.addWidget(field)

        lay.addStretch()
        return w

    def _build_snapshots(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(10)

        lay.addWidget(
            QLabel(
                "MAP SNAPSHOTS & ATTACHMENTS",
                styleSheet="color:#3fb950;font-size:12px;font-weight:700;padding:0 0 6px;",
            )
        )

        # ── Action buttons ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        _btn_style = (
            "QPushButton{background:#21262d;border:1px solid #30363d;"
            "color:#c9d1d9;font-size:10px;padding:5px 10px;border-radius:2px;}"
            "QPushButton:hover{border-color:#388bfd;color:#79c0ff;}"
            "QPushButton:disabled{color:#484f58;border-color:#21262d;}"
        )

        self._snap_capture_btn = QPushButton("📸  Capture Map")
        self._snap_capture_btn.setStyleSheet(_btn_style)
        self._snap_capture_btn.setEnabled(self._map_capture_fn is not None)
        self._snap_capture_btn.setToolTip("Screenshot the current map view")
        self._snap_capture_btn.clicked.connect(self._capture_map)

        self._snap_file_btn = QPushButton("📂  From File")
        self._snap_file_btn.setStyleSheet(_btn_style)
        self._snap_file_btn.setToolTip("Attach an existing image file")
        self._snap_file_btn.clicked.connect(self._attach_file)

        self._snap_refresh_btn = QPushButton("↻")
        self._snap_refresh_btn.setFixedWidth(30)
        self._snap_refresh_btn.setStyleSheet(_btn_style)
        self._snap_refresh_btn.clicked.connect(self._refresh_snapshots)

        btn_row.addWidget(self._snap_capture_btn)
        btn_row.addWidget(self._snap_file_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._snap_refresh_btn)
        lay.addLayout(btn_row)

        lay.addWidget(
            QLabel(
                "Save the OPORD first before adding snapshots.",
                styleSheet="color:#6e7681;font-size:9px;",
                objectName="snap_hint",
            )
        )
        lay.addWidget(_sep())

        # ── Scrollable snapshot grid ──────────────────────────────────
        self._snap_scroll = QScrollArea()
        self._snap_scroll.setWidgetResizable(True)
        self._snap_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._snap_scroll.setStyleSheet("QScrollArea{background:#0d1117;}")

        self._snap_container = QWidget()
        self._snap_container.setStyleSheet("background:#0d1117;")
        self._snap_grid = QGridLayout(self._snap_container)
        self._snap_grid.setContentsMargins(0, 0, 0, 0)
        self._snap_grid.setSpacing(8)

        self._snap_scroll.setWidget(self._snap_container)
        lay.addWidget(self._snap_scroll, 1)
        return w

    # ── Snapshot management ───────────────────────────────────────────────────

    def _ensure_saved(self) -> bool:
        if not self._opord_id:
            if not self._f_title.text().strip():
                QMessageBox.information(
                    self,
                    "Title Required",
                    "Please fill in the OPORD title (Header page) before saving.",
                )
                self._switch(0)  # jump to HEADER
                return False
            ans = QMessageBox.question(
                self,
                "Save First",
                "The OPORD must be saved before adding snapshots. Save now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self._save()
            return self._opord_id is not None
        return True

    def _capture_map(self):
        if not self._ensure_saved():
            return
        label, ok = QInputDialog.getText(
            self, "Snapshot Label", "Label for this snapshot:"
        )
        if not ok:
            return
        label = label.strip() or "Map Snapshot"
        try:
            px = self._map_capture_fn()
            if px is None or px.isNull():
                QMessageBox.warning(self, "Capture Failed", "Could not capture map.")
                return
            # Scale down if very large
            if px.width() > 1400:
                px = px.scaledToWidth(1400, Qt.TransformationMode.SmoothTransformation)
            b64 = _pixmap_to_b64(px)
            result = self._client.add_opord_snapshot(self._opord_id, label, b64)
            self._opord = result
            self._refresh_snapshots()
        except Exception as e:
            QMessageBox.critical(self, "Upload Failed", str(e))

    def _attach_file(self):
        if not self._ensure_saved():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach Image",
            "",
            "Images (*.png *.jpg *.jpeg *.gif *.webp);;All Files (*)",
        )
        if not path:
            return
        label, ok = QInputDialog.getText(
            self,
            "Attachment Label",
            "Label for this attachment:",
            text=path.split("/")[-1].rsplit(".", 1)[0],
        )
        if not ok:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
            b64 = base64.b64encode(data).decode("ascii")
            result = self._client.add_opord_snapshot(
                self._opord_id, label.strip() or "Attachment", b64
            )
            self._opord = result
            self._refresh_snapshots()
        except Exception as e:
            QMessageBox.critical(self, "Upload Failed", str(e))

    def _delete_snapshot(self, snap_id: int):
        ans = QMessageBox.question(
            self,
            "Delete Snapshot",
            "Delete this snapshot? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._client.delete_opord_snapshot(self._opord_id, snap_id)
            self._opord = result
            self._refresh_snapshots()
        except Exception as e:
            QMessageBox.critical(self, "Delete Failed", str(e))

    def _refresh_snapshots(self):
        # Clear existing grid
        self._snap_cards.clear()
        for t in self._thumb_loaders:
            t.quit()
        self._thumb_loaders.clear()
        while self._snap_grid.count():
            item = self._snap_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        snaps = self._opord.get("map_snapshots") or []
        has_id = self._opord_id is not None

        # Update hint visibility
        hint = self.findChild(QLabel, "snap_hint")
        if hint:
            hint.setVisible(not has_id)
        self._snap_capture_btn.setEnabled(has_id and self._map_capture_fn is not None)
        self._snap_file_btn.setEnabled(has_id)

        if not snaps:
            empty = QLabel("No snapshots yet." if has_id else "Save the OPORD first.")
            empty.setStyleSheet("color:#6e7681;font-size:10px;padding:12px 0;")
            self._snap_grid.addWidget(empty, 0, 0)
            return

        cols = 2
        token = self._client.token or ""
        for i, snap in enumerate(snaps):
            card = _SnapCard(snap)
            card.delete_requested.connect(self._delete_snapshot)
            self._snap_grid.addWidget(card, i // cols, i % cols)
            snap_id = snap.get("id", i)
            photo_id = snap.get("photo_id")
            if photo_id and token:
                url = self._client.photo_url(photo_id)
                t = _ThumbLoader(snap_id, url, token)
                t.loaded.connect(self._on_thumb)
                t.start()
                self._thumb_loaders.append(t)
                self._snap_cards[snap_id] = card

    def _on_thumb(self, snap_id: int, data: bytes):
        card = self._snap_cards.get(snap_id)
        if card and data:
            px = QPixmap()
            px.loadFromData(data)
            if not px.isNull():
                card.set_pixmap(px)

    def _build_distribution(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(8)
        lay.addWidget(
            QLabel(
                "DISTRIBUTION LIST",
                styleSheet="color:#3fb950;font-size:12px;font-weight:700;padding:0 0 6px;",
            )
        )
        lay.addWidget(
            QLabel(
                "Select operators to receive this OPORD:",
                styleSheet="color:#6e7681;font-size:9px;",
            )
        )

        # Select/deselect all
        btns = QHBoxLayout()
        sel_all = QPushButton("Select All")
        clr_all = QPushButton("Clear All")
        for b in (sel_all, clr_all):
            b.setFixedHeight(24)
            b.setStyleSheet(
                "QPushButton{background:#21262d;border:1px solid #30363d;"
                "color:#8b949e;font-size:9px;padding:0 8px;border-radius:2px;}"
                "QPushButton:hover{color:#c9d1d9;}"
            )
        sel_all.clicked.connect(
            lambda: [
                self._dist_list.item(i).setCheckState(Qt.CheckState.Checked)
                for i in range(self._dist_list.count())
            ]
        )
        clr_all.clicked.connect(
            lambda: [
                self._dist_list.item(i).setCheckState(Qt.CheckState.Unchecked)
                for i in range(self._dist_list.count())
            ]
        )
        btns.addWidget(sel_all)
        btns.addWidget(clr_all)
        btns.addStretch()
        lay.addLayout(btns)

        self._dist_list = QListWidget()
        self._dist_list.setFont(_MONO)
        lay.addWidget(self._dist_list, 1)
        lay.addStretch()
        return w

    # ── Populate from existing OPORD data ─────────────────────────────────────

    def _populate(self):
        o = self._opord
        if not o:
            self._update_title_bar()
            return

        self._f_title.setText(o.get("title", ""))
        self._f_num.setText(o.get("opord_number", ""))
        self._f_dtg.setText(o.get("dtg", ""))
        self._f_tz.setText(o.get("time_zone", "Z"))
        cls = o.get("classification", "UNCLASSIFIED")
        idx = self._f_class.findText(cls)
        if idx >= 0:
            self._f_class.setCurrentIndex(idx)
        self._f_refs.setPlainText(_to_str(o.get("references", "")))
        self._f_taskorg.setPlainText(_to_str(o.get("task_organization", "")))

        # Paragraph 1 — Situation (nested dict or string)
        sit = o.get("situation") or {}
        if isinstance(sit, str):
            try:
                sit = json.loads(sit)
            except Exception:
                sit = {"enemy": sit}
        self._f_enemy.setPlainText(_to_str(sit.get("enemy", "")))
        self._f_friendly.setPlainText(_to_str(sit.get("friendly", "")))
        self._f_attach.setPlainText(_to_str(sit.get("attachments", "")))
        self._f_terrain.setPlainText(_to_str(sit.get("terrain_weather", "")))

        # Paragraph 2 — Mission
        self._f_mission.setPlainText(_to_str(o.get("mission", "")))

        # Paragraph 3 — Execution
        ex = o.get("execution") or {}
        if isinstance(ex, str):
            try:
                ex = json.loads(ex)
            except Exception:
                ex = {"concept_of_operations": ex}
        self._f_intent.setPlainText(
            _to_str(ex.get("commanders_intent", ex.get("commander_intent", "")))
        )
        self._f_concept.setPlainText(
            _to_str(ex.get("concept_of_operations", ex.get("concept", "")))
        )
        self._f_tasks.setPlainText(
            _to_str(ex.get("tasks_by_element", ex.get("tasks", "")))
        )
        self._f_fires.setPlainText(
            _to_str(ex.get("fire_support", ex.get("fire_plan", "")))
        )
        self._f_roe.setPlainText(
            _to_str(ex.get("rules_of_engagement", ex.get("roe", "")))
        )

        # Paragraph 4 — Sustainment
        sus = o.get("sustainment") or {}
        if isinstance(sus, str):
            try:
                sus = json.loads(sus)
            except Exception:
                sus = {"supply": sus}
        self._f_supply.setPlainText(_to_str(sus.get("supply", "")))
        self._f_maint.setPlainText(_to_str(sus.get("maintenance", "")))
        self._f_medical.setPlainText(_to_str(sus.get("medical", "")))
        self._f_trans.setPlainText(_to_str(sus.get("transportation", "")))

        # Paragraph 5 — C&S
        cs = o.get("command_signal") or {}
        if isinstance(cs, str):
            try:
                cs = json.loads(cs)
            except Exception:
                cs = {"radio_freqs": cs}
        self._f_cp.setPlainText(_to_str(cs.get("command_post", "")))
        self._f_succession.setPlainText(_to_str(cs.get("succession", "")))
        self._f_freqs.setPlainText(
            _to_str(cs.get("radio_freqs", cs.get("frequencies", "")))
        )
        self._f_signals.setPlainText(_to_str(cs.get("signals", "")))
        self._f_pace.setPlainText(_to_str(cs.get("pace_plan", "")))

        self._update_title_bar()
        self._load_operators()
        self._refresh_snapshots()

    def _update_title_bar(self):
        status = self._opord.get("status", "DRAFT")
        title = self._opord.get("title", "New OPORD")
        self._title_label.setText(f"📋  {title}")
        self.setWindowTitle(f"OPORD — {title}")
        if status == "PUBLISHED":
            self._status_badge.setText("PUBLISHED")
            self._status_badge.setStyleSheet(
                "background:#0d2b0d;color:#3fb950;border:1px solid #3fb950;"
                "font-size:9px;font-weight:700;padding:2px 8px;border-radius:2px;letter-spacing:1px;"
            )
        else:
            self._status_badge.setText("DRAFT")
            self._status_badge.setStyleSheet(
                "background:#1a1208;color:#d29922;border:1px solid #d29922;"
                "font-size:9px;font-weight:700;padding:2px 8px;border-radius:2px;letter-spacing:1px;"
            )
        can_publish = self._opord_id is not None and status == "DRAFT"
        self._pub_btn.setEnabled(can_publish)
        self._send_btn.setEnabled(self._opord_id is not None and status == "PUBLISHED")

    def _load_operators(self):
        """Populate distribution list."""
        self._dist_list.clear()
        try:
            ops = self._client.live_operators()
            recipient_ids = set(self._opord.get("recipient_ids") or [])
            for op in ops:
                item = QListWidgetItem(
                    f"  {op.get('callsign','?')}  [{op.get('role','')}]"
                )
                item.setData(Qt.ItemDataRole.UserRole, op.get("id"))
                checked = (
                    Qt.CheckState.Checked
                    if op.get("id") in recipient_ids
                    else Qt.CheckState.Unchecked
                )
                item.setCheckState(checked)
                self._dist_list.addItem(item)
        except Exception:
            pass

    # ── Collect form data ──────────────────────────────────────────────────────

    def _collect(self) -> dict:
        recipient_ids = []
        for i in range(self._dist_list.count()):
            it = self._dist_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                rid = it.data(Qt.ItemDataRole.UserRole)
                if rid is not None:
                    recipient_ids.append(rid)

        return {
            "title": self._f_title.text().strip(),
            "opord_number": self._f_num.text().strip(),
            "dtg": self._f_dtg.text().strip(),
            "time_zone": self._f_tz.text().strip() or "Z",
            "classification": self._f_class.currentText(),
            "references": self._f_refs.toPlainText().strip(),
            "task_organization": self._f_taskorg.toPlainText().strip(),
            "situation": {
                "enemy": self._f_enemy.toPlainText().strip(),
                "friendly": self._f_friendly.toPlainText().strip(),
                "attachments": self._f_attach.toPlainText().strip(),
                "terrain_weather": self._f_terrain.toPlainText().strip(),
            },
            "mission": self._f_mission.toPlainText().strip(),
            "execution": {
                "commanders_intent": self._f_intent.toPlainText().strip(),
                "concept_of_operations": self._f_concept.toPlainText().strip(),
                "tasks_by_element": self._f_tasks.toPlainText().strip(),
                "fire_support": self._f_fires.toPlainText().strip(),
                "rules_of_engagement": self._f_roe.toPlainText().strip(),
            },
            "sustainment": {
                "supply": self._f_supply.toPlainText().strip(),
                "maintenance": self._f_maint.toPlainText().strip(),
                "medical": self._f_medical.toPlainText().strip(),
                "transportation": self._f_trans.toPlainText().strip(),
            },
            "command_signal": {
                "command_post": self._f_cp.toPlainText().strip(),
                "succession": self._f_succession.toPlainText().strip(),
                "radio_freqs": self._f_freqs.toPlainText().strip(),
                "signals": self._f_signals.toPlainText().strip(),
                "pace_plan": self._f_pace.toPlainText().strip(),
            },
            "recipient_ids": recipient_ids,
            "status": "DRAFT",
        }

    # ── Actions ────────────────────────────────────────────────────────────────

    def _save(self):
        data = self._collect()
        if not data.get("title"):
            QMessageBox.warning(self, "Required", "OPORD title is required.")
            return
        try:
            if self._is_new:
                result = self._client.create_opord(data)
                self._opord_id = result["id"]
                self._is_new = False
            else:
                result = self._client.update_opord(self._opord_id, data)
            self._opord = result
            self._update_title_bar()
            self._refresh_snapshots()
            self.saved.emit(result)
            self.statusBar().showMessage("Saved", 3000)
        except Exception as e:
            msg = str(e)
            if "403" in msg:
                msg = (
                    "Permission denied — creating and editing OPORDs requires "
                    "BATTLE_CAPTAIN or ADMIN role."
                )
            QMessageBox.critical(self, "Save Failed", msg)

    def _publish(self):
        if not self._opord_id:
            return
        ans = QMessageBox.question(
            self,
            "Publish OPORD",
            "Publish this OPORD? Recipients will be able to receive it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self._client.publish_opord(self._opord_id)
            self._opord = result
            self._update_title_bar()
            self.published.emit(result)
        except Exception as e:
            QMessageBox.critical(self, "Publish Failed", str(e))

    def _send(self):
        if not self._opord_id:
            return
        recipient_ids = []
        for i in range(self._dist_list.count()):
            it = self._dist_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                rid = it.data(Qt.ItemDataRole.UserRole)
                if rid is not None:
                    recipient_ids.append(rid)
        try:
            self._client.send_opord(self._opord_id, recipient_ids)
            self.statusBar().showMessage(
                f"OPORD sent to {len(recipient_ids)} operators", 4000
            )
        except Exception as e:
            QMessageBox.critical(self, "Send Failed", str(e))
