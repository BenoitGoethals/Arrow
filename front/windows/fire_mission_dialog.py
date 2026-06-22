"""Call-for-Fire / Fire Mission request dialog.

Opens from the map radial menu (FIRE petal) with the target location pre-filled.
Mirrors the web map's inline "Call for Fire" form and submits to the backend's
``POST /fire-missions`` endpoint, which broadcasts the mission to the FDC and
every connected client on the ``fire-mission`` channel.
"""

from __future__ import annotations
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QWidget,
    QTextEdit,
    QFrame,
    QSpinBox,
    QDoubleSpinBox,
)
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QFont

# Mission types & ammunition — same vocabulary the backend validates against.
MISSION_TYPES = [
    ("ADJUST_FIRE", "Adjust Fire (AF)"),
    ("FIRE_FOR_EFFECT", "Fire for Effect (FFE)"),
    ("SUPPRESSION", "Suppression"),
    ("ILLUMINATION", "Illumination"),
    ("IMMEDIATE_SUPPRESSION", "Immediate Suppression"),
]
AMMO_TYPES = ["HE", "ILLUM", "SMOKE", "WP", "ICM", "AP", "FRAG", "MIXED"]


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#30363d;")
    return f


class FireMissionDialog(QDialog):
    """Call-for-Fire form. Emits ``fire_mission_submitted`` with the created
    FireMission dict on a successful POST."""

    fire_mission_submitted = pyqtSignal(dict)

    def __init__(self, client, lat: float, lon: float, mgrs: str = "", parent=None):
        super().__init__(parent)
        self._client = client
        self._lat = lat
        self._lon = lon
        self._mgrs = mgrs or f"{lat:.5f}, {lon:.5f}"

        self.setWindowTitle("CALL FOR FIRE")
        self.setMinimumWidth(520)
        self.setModal(True)
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        mono = QFont("Courier New", 10)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("background:#0d1117;border-bottom:1px solid #f85149;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 8, 12, 8)
        title = QLabel("🎯  CALL FOR FIRE")
        title.setStyleSheet(
            "color:#f85149;font-size:15px;font-weight:700;letter-spacing:2px;"
            "font-family:'Courier New',monospace;"
        )
        hl.addWidget(title)
        hl.addStretch()
        ts = QLabel(datetime.now(timezone.utc).strftime("Z %H%Mh %d%b%Y").upper())
        ts.setStyleSheet(
            "color:#6e7681;font-size:10px;font-family:'Courier New',monospace;"
        )
        hl.addWidget(ts)
        root.addWidget(hdr)

        # Body
        body = QWidget()
        body.setStyleSheet("background:#0d1117;")
        fl = QVBoxLayout(body)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(8)

        def _line_style(w):
            w.setFont(mono)
            w.setStyleSheet(
                "QLineEdit,QSpinBox,QDoubleSpinBox{background:#161b22;border:1px solid #30363d;"
                "color:#c9d1d9;padding:5px 8px;border-radius:2px;}"
                "QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus{border-color:#388bfd;}"
                "QLineEdit[readOnly='true']{color:#8b949e;}"
            )
            return w

        def _combo(items) -> QComboBox:
            c = QComboBox()
            c.setFont(mono)
            c.addItems(items)
            c.setStyleSheet(
                "QComboBox{background:#161b22;border:1px solid #30363d;color:#c9d1d9;"
                "padding:4px 8px;border-radius:2px;}"
                "QComboBox:focus{border-color:#388bfd;}"
                "QComboBox::drop-down{border:none;}"
                "QComboBox QAbstractItemView{background:#161b22;color:#c9d1d9;"
                "selection-background-color:#1f6feb;}"
            )
            return c

        def _lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(
                "color:#8b949e;font-size:10px;font-weight:700;letter-spacing:1px;"
            )
            return l

        # Target grid (reference; the radial click location is authoritative)
        self._grid = _line_style(QLineEdit(self._mgrs))
        self._grid.setReadOnly(True)
        gridrow = QHBoxLayout()
        gridrow.addWidget(_lbl("TARGET GRID"))
        gridrow.addWidget(self._grid, 1)
        fl.addLayout(gridrow)
        fl.addWidget(_sep())

        # Direction (required) + Altitude
        row1 = QHBoxLayout()
        self._dir = _line_style(QDoubleSpinBox())
        self._dir.setRange(0, 360)
        self._dir.setDecimals(0)
        self._dir.setSuffix(" °")
        col_dir = QVBoxLayout()
        col_dir.addWidget(_lbl("DIRECTION (obs → tgt)"))
        col_dir.addWidget(self._dir)
        self._alt = _line_style(QDoubleSpinBox())
        self._alt.setRange(-500, 9000)
        self._alt.setDecimals(0)
        self._alt.setSuffix(" m")
        col_alt = QVBoxLayout()
        col_alt.addWidget(_lbl("ALTITUDE (m MSL)"))
        col_alt.addWidget(self._alt)
        row1.addLayout(col_dir, 1)
        row1.addLayout(col_alt, 1)
        fl.addLayout(row1)

        # Mission type + ammunition + rounds
        row2 = QHBoxLayout()
        self._type = _combo([lbl for _, lbl in MISSION_TYPES])
        col_t = QVBoxLayout()
        col_t.addWidget(_lbl("TYPE OF MISSION"))
        col_t.addWidget(self._type)
        row2.addLayout(col_t, 2)
        fl.addLayout(row2)

        row3 = QHBoxLayout()
        self._ammo = _combo(AMMO_TYPES)
        col_a = QVBoxLayout()
        col_a.addWidget(_lbl("AMMUNITION"))
        col_a.addWidget(self._ammo)
        self._qty = _line_style(QSpinBox())
        self._qty.setRange(1, 999)
        self._qty.setValue(1)
        col_q = QVBoxLayout()
        col_q.addWidget(_lbl("ROUNDS"))
        col_q.addWidget(self._qty)
        row3.addLayout(col_a, 2)
        row3.addLayout(col_q, 1)
        fl.addLayout(row3)
        fl.addWidget(_sep())

        # Description
        fl.addWidget(_lbl("TARGET DESCRIPTION"))
        self._desc = QTextEdit()
        self._desc.setFont(mono)
        self._desc.setFixedHeight(64)
        self._desc.setPlaceholderText("e.g. Infantry platoon in open, moving NE")
        self._desc.setStyleSheet(
            "QTextEdit{background:#161b22;border:1px solid #30363d;color:#c9d1d9;"
            "padding:5px 8px;border-radius:2px;}"
            "QTextEdit:focus{border-color:#388bfd;}"
        )
        fl.addWidget(self._desc)

        root.addWidget(body, 1)

        # Footer
        foot = QWidget()
        foot.setStyleSheet("background:#0d1117;border-top:1px solid #30363d;")
        fbl = QHBoxLayout(foot)
        fbl.setContentsMargins(12, 8, 12, 8)
        self._status = QLabel("")
        self._status.setStyleSheet(
            "color:#8b949e;font-size:10px;font-family:'Courier New',monospace;"
        )
        fbl.addWidget(self._status, 1)

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;color:#8b949e;"
            "padding:8px 20px;font-size:11px;}"
            "QPushButton:hover{background:#30363d;color:#c9d1d9;}"
        )
        cancel.clicked.connect(self.reject)
        fbl.addWidget(cancel)

        self._send_btn = QPushButton("🎯  CALL FOR FIRE")
        self._send_btn.setStyleSheet(
            "QPushButton{background:#8b1538;border:1px solid #f85149;color:#fff;"
            "padding:8px 24px;font-size:12px;font-weight:700;letter-spacing:1px;}"
            "QPushButton:hover{background:#da3633;border-color:#f85149;}"
            "QPushButton:disabled{background:#21262d;border-color:#30363d;color:#484f58;}"
        )
        self._send_btn.clicked.connect(self._transmit)
        fbl.addWidget(self._send_btn)
        root.addWidget(foot)

    # ── Transmit ─────────────────────────────────────────────────────────────
    def _transmit(self):
        self._send_btn.setEnabled(False)
        self._status.setText("Transmitting…")
        self._status.setStyleSheet(
            "color:#d29922;font-size:10px;font-family:'Courier New',monospace;"
        )

        mission_type = MISSION_TYPES[self._type.currentIndex()][0]
        ammunition = self._ammo.currentText()
        direction = float(self._dir.value())
        quantity = int(self._qty.value())
        description = self._desc.toPlainText().strip() or (
            f"{mission_type} · {ammunition} · {self._mgrs}"
        )

        try:
            created = self._client.post_fire_mission(
                latitude=self._lat,
                longitude=self._lon,
                direction=direction,
                mission_type=mission_type,
                ammunition=ammunition,
                quantity=quantity,
                altitude=float(self._alt.value()),
                description=description,
            )
            self._status.setText(
                f"✓ FIRE MISSION #{created.get('id', '?')} SUBMITTED TO FDC"
            )
            self._status.setStyleSheet(
                "color:#3fb950;font-size:10px;font-weight:700;font-family:'Courier New',monospace;"
            )
            self.fire_mission_submitted.emit(created)
            QTimer.singleShot(1500, self.accept)
        except Exception as e:
            self._send_btn.setEnabled(True)
            self._status.setText(f"FAILED: {e}")
            self._status.setStyleSheet(
                "color:#f85149;font-size:10px;font-family:'Courier New',monospace;"
            )
