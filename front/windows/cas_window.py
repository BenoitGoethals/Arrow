"""CAS (Close Air Support) 9-liner request window.

Opens from the map radial menu with the target location pre-filled.
Submits to the backend as a CAS request (``POST /cas/requests``) which the
backend persists as a ``CAS`` report and broadcasts on the ``cas`` channel.
Mirrors the MEDEVAC 9-liner window so the two share look and behaviour.
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
    QCheckBox,
    QPushButton,
    QFrame,
    QScrollArea,
    QWidget,
    QTextEdit,
)
from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtGui import QFont

# ── Field option sets ───────────────────────────────────────────────────────
_LINE6_MARK = [
    "None",
    "Laser",
    "IR Pointer",
    "IR Strobe",
    "Smoke",
    "WP (White Phosphorus)",
    "Mark-63 / Beacon",
]
_LINE8_EGRESS = [
    "N",
    "NE",
    "E",
    "SE",
    "S",
    "SW",
    "W",
    "NW",
]


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#30363d;")
    return f


def _lbl(text: str, color: str = "#8b949e", size: int = 9) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{color};font-size:{size}px;font-weight:700;letter-spacing:1px;"
    )
    return lab


class CasWindow(QDialog):
    """Full CAS 9-liner request form (mirrors MEDEVAC window styling)."""

    request_submitted = pyqtSignal(dict)  # emitted on successful send

    # ── CAS target marker SIDC (Hostile Ground, generic — the strike point) ──
    CAS_SIDC = "SHGP-----------"  # Hostile Ground unit (target reference)

    def __init__(
        self,
        client,
        lat: float,
        lon: float,
        mgrs: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._client = client
        self._lat = lat
        self._lon = lon
        self._mgrs = mgrs or f"{lat:.5f}, {lon:.5f}"
        self._assets: list[dict] = []

        self.setWindowTitle("CAS 9-LINER REQUEST")
        self.setMinimumWidth(560)
        self.setMinimumHeight(700)
        self.setModal(True)
        self._build_ui()
        self._load_assets()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        hdr = QWidget()
        hdr.setStyleSheet("background:#0d1117;border-bottom:1px solid #f85149;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 8, 12, 8)
        title = QLabel("🎯  CAS 9-LINER")
        title.setStyleSheet(
            "color:#f85149;font-size:15px;font-weight:700;letter-spacing:2px;"
            "font-family:'Courier New',monospace;"
        )
        hl.addWidget(title)
        hl.addStretch()
        ts_lbl = QLabel(datetime.now(timezone.utc).strftime("Z %H%Mh %d%b%Y").upper())
        ts_lbl.setStyleSheet(
            "color:#6e7681;font-size:10px;font-family:'Courier New',monospace;"
        )
        hl.addWidget(ts_lbl)
        root.addWidget(hdr)

        # Scrollable form body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setStyleSheet("background:#0d1117;")
        fl = QVBoxLayout(body)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(8)

        mono = QFont("Courier New", 10)

        def _field(placeholder: str = "", editable: bool = True) -> QLineEdit:
            e = QLineEdit()
            e.setFont(mono)
            e.setPlaceholderText(placeholder)
            e.setStyleSheet(
                "QLineEdit{background:#161b22;border:1px solid #30363d;color:#c9d1d9;"
                "padding:5px 8px;border-radius:2px;}"
                "QLineEdit:focus{border-color:#388bfd;}"
                "QLineEdit[readOnly='true']{color:#8b949e;}"
            )
            if not editable:
                e.setReadOnly(True)
            return e

        def _combo(items: list[str]) -> QComboBox:
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

        def _wrap(layout) -> QWidget:
            w = QWidget()
            w.setLayout(layout)
            return w

        def _row(line_num: str, label: str, widget_or_layout, color: str = "#ff9e64"):
            from PyQt6.QtWidgets import QLayout

            widget = (
                _wrap(widget_or_layout)
                if isinstance(widget_or_layout, QLayout)
                else widget_or_layout
            )
            box = QHBoxLayout()
            box.setSpacing(8)
            num = QLabel(f"LINE {line_num}")
            num.setFixedWidth(56)
            num.setStyleSheet(
                f"color:{color};font-size:9px;font-weight:700;letter-spacing:1px;"
                "font-family:'Courier New',monospace;"
            )
            lbl2 = QLabel(label)
            lbl2.setFixedWidth(160)
            lbl2.setStyleSheet("color:#8b949e;font-size:10px;")
            lbl2.setWordWrap(True)
            box.addWidget(num)
            box.addWidget(lbl2)
            box.addWidget(widget, 1)
            fl.addLayout(box)

        # ── Line 1: IP (Initial Point) ──────────────────────────────────
        self._l1 = _field("IP / BP name or grid")
        _row("1", "IP / Battle Position", self._l1)
        fl.addWidget(_sep())

        # ── Line 2: Heading / Distance from IP to target ────────────────
        l2_row = QHBoxLayout()
        self._l2_hdg = _field("Heading °")
        self._l2_dist = _field("Distance (km/m)")
        l2_row.addWidget(QLabel("Hdg:"))
        l2_row.addWidget(self._l2_hdg, 1)
        l2_row.addWidget(QLabel("Dist:"))
        l2_row.addWidget(self._l2_dist, 1)
        for lbl_w in [l2_row.itemAt(i).widget() for i in (0, 2)]:
            if lbl_w:
                lbl_w.setStyleSheet("color:#6e7681;font-size:10px;")
        _row("2", "Heading /\ndistance IP→tgt", l2_row)
        fl.addWidget(_sep())

        # ── Line 3: Target elevation MSL ────────────────────────────────
        self._l3 = _field("Elevation (m/ft MSL)")
        _row("3", "Target elevation", self._l3)
        fl.addWidget(_sep())

        # ── Line 4: Target description ──────────────────────────────────
        self._l4 = _field("e.g. 2x BMP in treeline")
        _row("4", "Target description", self._l4)
        fl.addWidget(_sep())

        # ── Line 5: Target location (pre-filled MGRS) ───────────────────
        self._l5 = _field("Target MGRS")
        self._l5.setText(self._mgrs)
        _row("5", "Target location\n(MGRS)", self._l5)
        fl.addWidget(_sep())

        # ── Line 6: Type of mark ────────────────────────────────────────
        self._l6 = _combo(_LINE6_MARK)
        _row("6", "Type of mark", self._l6)
        fl.addWidget(_sep())

        # ── Line 7: Friendly location ───────────────────────────────────
        self._l7 = _field("Friendly posn / distance from tgt")
        _row("7", "Friendly location", self._l7)
        fl.addWidget(_sep())

        # ── Line 8: Egress direction ────────────────────────────────────
        self._l8 = _combo(_LINE8_EGRESS)
        _row("8", "Egress direction", self._l8)
        fl.addWidget(_sep())

        # ── Line 9: Remarks / Threats / TOT ─────────────────────────────
        self._l9 = _field("Threats, restrictions, TOT…")
        _row("9", "Remarks / threats", self._l9)
        fl.addWidget(_sep())

        # ── TIC + asset nomination ──────────────────────────────────────
        opt_row = QHBoxLayout()
        self._tic = QCheckBox("TROOPS IN CONTACT")
        self._tic.setStyleSheet(
            "QCheckBox{color:#f85149;font-size:10px;font-weight:700;letter-spacing:1px;}"
        )
        opt_row.addWidget(self._tic)
        opt_row.addStretch()
        fl.addLayout(opt_row)

        fl.addWidget(_lbl("NOMINATE CAS ASSET (OPTIONAL)"))
        self._asset = _combo(["— none —"])
        fl.addWidget(self._asset)

        # ── Additional remarks ──────────────────────────────────────────
        fl.addWidget(_lbl("ADDITIONAL REMARKS"))
        self._notes = QTextEdit()
        self._notes.setFont(mono)
        self._notes.setFixedHeight(60)
        self._notes.setPlaceholderText(
            "Additional coordination, danger-close, restrictions…"
        )
        self._notes.setStyleSheet(
            "QTextEdit{background:#161b22;border:1px solid #30363d;color:#c9d1d9;"
            "padding:5px 8px;border-radius:2px;}"
            "QTextEdit:focus{border-color:#388bfd;}"
        )
        fl.addWidget(self._notes)

        fl.addStretch()
        body.setLayout(fl)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ── Footer buttons ────────────────────────────────────────────
        foot = QWidget()
        foot.setStyleSheet("background:#0d1117;border-top:1px solid #30363d;")
        fbl = QHBoxLayout(foot)
        fbl.setContentsMargins(12, 8, 12, 8)

        self._status = QLabel("")
        self._status.setStyleSheet(
            "color:#8b949e;font-size:10px;font-family:'Courier New',monospace;"
        )
        fbl.addWidget(self._status, 1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton{background:#21262d;border:1px solid #30363d;color:#8b949e;"
            "padding:8px 20px;font-size:11px;}"
            "QPushButton:hover{background:#30363d;color:#c9d1d9;}"
        )
        cancel_btn.clicked.connect(self.reject)
        fbl.addWidget(cancel_btn)

        self._send_btn = QPushButton("🎯  TRANSMIT CAS REQUEST")
        self._send_btn.setStyleSheet(
            "QPushButton{background:#8b1538;border:1px solid #f85149;color:#fff;"
            "padding:8px 24px;font-size:12px;font-weight:700;letter-spacing:1px;}"
            "QPushButton:hover{background:#da3633;border-color:#f85149;}"
            "QPushButton:disabled{background:#21262d;border-color:#30363d;color:#484f58;}"
        )
        self._send_btn.clicked.connect(self._transmit)
        fbl.addWidget(self._send_btn)

        root.addWidget(foot)

    # ── Asset loading ──────────────────────────────────────────────────────────

    def _load_assets(self):
        """Populate the asset-nomination combo from /cas/assets (best-effort)."""
        try:
            self._assets = self._client.cas_assets() or []
        except Exception:
            self._assets = []
        for a in self._assets:
            label = (
                f"{a.get('callsign', '?')} · {a.get('aircraft_type', '')} · "
                f"{a.get('status', '')}"
            )
            self._asset.addItem(label.strip(" ·"))

    # ── Transmit ─────────────────────────────────────────────────────────────

    def _transmit(self):
        self._send_btn.setEnabled(False)
        self._status.setText("Transmitting…")
        self._status.setStyleSheet(
            "color:#d29922;font-size:10px;font-family:'Courier New',monospace;"
        )

        remarks = self._l9.text().strip()
        extra = self._notes.toPlainText().strip()
        if extra:
            remarks = f"{remarks}\n{extra}".strip()

        # Resolve nominated asset id (index 0 == "— none —")
        asset_id = None
        idx = self._asset.currentIndex()
        if idx > 0 and idx - 1 < len(self._assets):
            asset_id = self._assets[idx - 1].get("id")

        body = {
            "line_1": self._l1.text().strip(),
            "line_2": f"{self._l2_hdg.text().strip()} / {self._l2_dist.text().strip()}".strip(
                " /"
            ),
            "line_3": self._l3.text().strip(),
            "line_4": self._l4.text().strip(),
            "line_5_mgrs": self._l5.text().strip(),
            "line_5_lat": self._lat,
            "line_5_lon": self._lon,
            "line_6": self._l6.currentText(),
            "line_7": self._l7.text().strip(),
            "line_8": self._l8.currentText(),
            "line_9": remarks,
            "tic": self._tic.isChecked(),
            "asset_id": asset_id,
        }

        try:
            self._client.post_cas_request(body)
            self._status.setText("✓ TRANSMITTED")
            self._status.setStyleSheet(
                "color:#3fb950;font-size:10px;font-weight:700;font-family:'Courier New',monospace;"
            )
            self.request_submitted.emit(body)
            QTimer.singleShot(1500, self.accept)
        except Exception as e:
            self._send_btn.setEnabled(True)
            self._status.setText(f"FAILED: {e}")
            self._status.setStyleSheet(
                "color:#f85149;font-size:10px;font-family:'Courier New',monospace;"
            )
