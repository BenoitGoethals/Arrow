"""MEDEVAC 9-liner request window.

Opens from the map radial menu with the pickup-zone location pre-filled.
Submits to the backend as a MEDEVAC report with the full 9-liner payload.
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
    QFrame,
    QScrollArea,
    QWidget,
)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont

# ── Field definitions per NATO STANAG 3705 / FM 8-10-6 ──────────────────────
_LINE3_PRECEDENCE = [
    "A – Urgent Surgical (< 1 h)",
    "B – Urgent (< 2 h)",
    "C – Priority (< 4 h)",
    "D – Routine (< 24 h)",
    "E – Convenience",
]
_LINE4_EQUIPMENT = [
    "None",
    "A – Hoist",
    "B – Extraction Equipment",
    "C – Ventilator",
]
_LINE6_SECURITY = [
    "N – No enemy troops",
    "P – Possible enemy troops",
    "E – Enemy troops in area",
    "X – Armed escort required",
]
_LINE7_MARKING = [
    "A – Panels",
    "B – Pyrotechnic signal",
    "C – Smoke signal",
    "D – None",
    "E – Other",
]
_LINE8_NATIONALITY = [
    "A – US Military",
    "B – US Civilian",
    "C – Non-US Military",
    "D – Non-US Civilian",
    "E – EPW (Enemy Prisoner of War)",
]
_LINE9_NBC = [
    "N – None",
    "B – Biological",
    "C – Chemical",
    "N/A – Nuclear",
]


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#30363d;")
    return f


def _lbl(text: str, color: str = "#8b949e", size: int = 9) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{color};font-size:{size}px;font-weight:700;letter-spacing:1px;"
    )
    return l


class MedevacWindow(QDialog):
    """Full NATO 9-liner MEDEVAC request form."""

    report_submitted = pyqtSignal(dict)  # emitted on successful send

    # ── Medical marker SIDC (Ground, Medical) ────────────────────────────────
    MEDEVAC_SIDC = "SFGPUSM---D----"  # Friendly Ground Medical

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

        self.setWindowTitle("MEDEVAC 9-LINER REQUEST")
        self.setMinimumWidth(560)
        self.setMinimumHeight(680)
        self.setModal(True)
        self._build_ui()

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
        title = QLabel("🚁  MEDEVAC 9-LINER")
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
            """Wrap a QLayout in a plain QWidget so it can be added as a widget."""
            w = QWidget()
            w.setLayout(layout)
            return w

        def _row(line_num: str, label: str, widget_or_layout, color: str = "#ff9e64"):
            # Accept either a QWidget or a QLayout
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

        # ── Line 1: Location ────────────────────────────────────────────
        self._l1 = _field("MGRS of pickup zone")
        self._l1.setText(self._mgrs)
        _row("1", "Location (MGRS)", self._l1)
        fl.addWidget(_sep())

        # ── Line 2: Frequency / callsign ────────────────────────────────
        l2_row = QHBoxLayout()
        self._l2_freq = _field("Freq (MHz)")
        self._l2_cs = _field("Call sign")
        self._l2_suf = _field("Suffix")
        self._l2_suf.setFixedWidth(60)
        l2_row.addWidget(self._l2_freq, 2)
        l2_row.addWidget(self._l2_cs, 2)
        l2_row.addWidget(self._l2_suf, 1)
        _row("2", "Radio freq / call sign / suffix", l2_row)

        # insert the layout directly
        fl.addWidget(_sep())

        # ── Line 3: Number of patients by precedence ─────────────────
        l3_row = QHBoxLayout()
        self._l3_prec = _combo(_LINE3_PRECEDENCE)
        self._l3_num = _field("Count", True)
        self._l3_num.setFixedWidth(60)
        l3_row.addWidget(self._l3_prec, 3)
        l3_row.addWidget(self._l3_num, 1)
        _row("3", "Patients by\nprecedence / count", l3_row)
        fl.addWidget(_sep())

        # ── Line 4: Special equipment ────────────────────────────────
        self._l4 = _combo(_LINE4_EQUIPMENT)
        _row("4", "Special equipment", self._l4)
        fl.addWidget(_sep())

        # ── Line 5: Number of patients by type ───────────────────────
        l5_row = QHBoxLayout()
        self._l5_litter = _field("Litter")
        self._l5_amb = _field("Ambulatory")
        l5_row.addWidget(QLabel("Litter:"))
        l5_row.addWidget(self._l5_litter, 1)
        l5_row.addWidget(QLabel("Ambulatory:"))
        l5_row.addWidget(self._l5_amb, 1)
        for lbl_w in [l5_row.itemAt(i).widget() for i in (0, 2)]:
            if lbl_w:
                lbl_w.setStyleSheet("color:#6e7681;font-size:10px;")
        _row("5", "Patients by type", l5_row)
        fl.addWidget(_sep())

        # ── Line 6: Security at pickup site ──────────────────────────
        self._l6 = _combo(_LINE6_SECURITY)
        _row("6", "Security at\npickup site", self._l6)
        fl.addWidget(_sep())

        # ── Line 7: Marking of pickup site ───────────────────────────
        l7_row = QHBoxLayout()
        self._l7_method = _combo(_LINE7_MARKING)
        self._l7_color = _field("Smoke colour / panel colour")
        l7_row.addWidget(self._l7_method, 2)
        l7_row.addWidget(self._l7_color, 2)
        _row("7", "Marking of\npickup site", l7_row)
        fl.addWidget(_sep())

        # ── Line 8: Nationality / status ─────────────────────────────
        self._l8 = _combo(_LINE8_NATIONALITY)
        _row("8", "Nationality &\nstatus", self._l8)
        fl.addWidget(_sep())

        # ── Line 9: NBC contamination ────────────────────────────────
        self._l9 = _combo(_LINE9_NBC)
        _row("9", "NBC\ncontamination", self._l9)
        fl.addWidget(_sep())

        # ── Additional notes ─────────────────────────────────────────
        from PyQt6.QtWidgets import QTextEdit

        fl.addWidget(_lbl("ADDITIONAL NOTES / PATIENT CONDITION"))
        self._notes = QTextEdit()
        self._notes.setFont(mono)
        self._notes.setFixedHeight(70)
        self._notes.setPlaceholderText("Nature of injury, mechanism, vital signs…")
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

        self._send_btn = QPushButton("🚁  TRANSMIT MEDEVAC")
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

        payload = {
            "line1_location": self._l1.text().strip(),
            "line2_frequency": self._l2_freq.text().strip(),
            "line2_callsign": self._l2_cs.text().strip(),
            "line2_suffix": self._l2_suf.text().strip(),
            "line3_precedence": self._l3_prec.currentText(),
            "line3_count": self._l3_num.text().strip(),
            "line4_equipment": self._l4.currentText(),
            "line5_litter": self._l5_litter.text().strip(),
            "line5_ambulatory": self._l5_amb.text().strip(),
            "line6_security": self._l6.currentText(),
            "line7_marking": self._l7_method.currentText(),
            "line7_color": self._l7_color.text().strip(),
            "line8_nationality": self._l8.currentText(),
            "line9_nbc": self._l9.currentText(),
            "notes": self._notes.toPlainText().strip(),
            "latitude": self._lat,
            "longitude": self._lon,
        }

        try:
            self._client.post_report("MEDEVAC", payload)
            self._status.setText("✓ TRANSMITTED")
            self._status.setStyleSheet(
                "color:#3fb950;font-size:10px;font-weight:700;font-family:'Courier New',monospace;"
            )
            self.report_submitted.emit(payload)
            # Auto-close after brief confirmation
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(1500, self.accept)
        except Exception as e:
            self._send_btn.setEnabled(True)
            self._status.setText(f"FAILED: {e}")
            self._status.setStyleSheet(
                "color:#f85149;font-size:10px;font-family:'Courier New',monospace;"
            )
