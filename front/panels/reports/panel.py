"""Reports Panel — incoming tactical report queue with detail viewer."""

from __future__ import annotations
import json
from typing import List

from front.utils.mgrs_util import to_mgrs

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QComboBox,
    QTextEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from front.models.report import Report


class ReportItem(QListWidgetItem):
    def __init__(self, report: Report):
        super().__init__()
        self.report = report
        self._render()

    def _render(self):
        ts = (
            self.report.timestamp[:16]
            if len(self.report.timestamp) >= 16
            else self.report.timestamp
        )
        pin = "📍" if self.report.has_position else "  "
        self.setText(
            f"{pin}{self.report.icon}  {self.report.type:<12}  {self.report.sender:<10}  {ts}"
        )
        self.setForeground(QColor(self.report.priority_color))
        if not self.report.read:
            font = QFont()
            font.setBold(True)
            self.setFont(font)


class ReportsPanel(QWidget):
    """Right-dock reports queue."""

    report_selected = pyqtSignal(object)  # Report
    locate_requested = pyqtSignal(float, float)  # lat, lon

    def __init__(self, parent=None):
        super().__init__(parent)
        self._reports: List[Report] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(6, 4, 6, 4)
        filter_row.setSpacing(4)
        self._type_filter = QComboBox()
        self._type_filter.addItems(
            [
                "ALL",
                "CASEVAC",
                "MEDEVAC",
                "CAS",
                "SALUTE",
                "SITREP",
                "ACE",
                "CBRN_1",
                "DRONE_SPOT",
                "CONTACT",
            ]
        )
        self._type_filter.currentTextChanged.connect(self._apply_filter)
        filter_row.addWidget(QLabel("TYPE"))
        filter_row.addWidget(self._type_filter, 1)
        layout.addLayout(filter_row)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        layout.addWidget(line)

        # Report list
        self._list = QListWidget()
        self._list.setFont(QFont("Courier New", 12))
        self._list.setAlternatingRowColors(True)
        self._list.itemClicked.connect(self._on_click)
        self._list.itemDoubleClicked.connect(self._show_detail)
        layout.addWidget(self._list, 1)

        # Unread counter
        self._counter = QLabel("0 reports")
        self._counter.setObjectName("statusSmall")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self._counter)

    # ---- Public API -------------------------------------------------------

    def add_report(self, data: dict):
        report = Report(
            id=data.get("id", 0),
            type=data.get("type", "UNKNOWN"),
            sender=data.get("sender") or data.get("callsign", "?"),
            timestamp=data.get("timestamp") or data.get("created_at", ""),
            payload=data.get("payload", {}),
            read=False,
        )
        self._reports.insert(0, report)
        self._apply_filter(self._type_filter.currentText())
        self._update_counter()

    def load_reports(self, reports: list):
        self._reports.clear()
        for d in reversed(reports):
            self._reports.insert(
                0,
                Report(
                    id=d.get("id", 0),
                    type=d.get("type", "UNKNOWN"),
                    sender=d.get("sender") or d.get("callsign", "?"),
                    timestamp=d.get("timestamp") or d.get("created_at", ""),
                    payload=d.get("payload", {}),
                    read=True,
                ),
            )
        self._apply_filter(self._type_filter.currentText())
        self._update_counter()

    # ---- Private ----------------------------------------------------------

    def _apply_filter(self, type_filter: str):
        self._list.clear()
        for r in self._reports:
            if type_filter == "ALL" or r.type == type_filter:
                self._list.addItem(ReportItem(r))

    def _update_counter(self):
        unread = sum(1 for r in self._reports if not r.read)
        total = len(self._reports)
        self._counter.setText(f"{unread} unread  ·  {total} total")

    def _on_click(self, item: QListWidgetItem):
        if not isinstance(item, ReportItem):
            return
        r = item.report
        if r.has_position:
            self.locate_requested.emit(r.latitude, r.longitude)

    def _show_detail(self, item: QListWidgetItem):
        if not isinstance(item, ReportItem):
            return
        item.report.read = True
        font = QFont()
        font.setBold(False)
        item.setFont(font)
        self._update_counter()

        dlg = ReportDetailDialog(item.report, self)
        dlg.exec()


_LAT_KEYS = {"latitude", "lat", "observer_lat", "event_lat", "target_lat"}
_LON_KEYS = {"longitude", "lon", "observer_lon", "event_lon", "target_lon"}


def _coords_to_mgrs(d: dict) -> dict:
    """Return a copy of d with lat/lon float pairs replaced by MGRS strings."""
    out = {}
    skip = set()
    # Pair up lat/lon keys and replace with MGRS
    lat_keys = {
        k for k in d if k.lower() in _LAT_KEYS and isinstance(d[k], (int, float))
    }
    for lk in lat_keys:
        base = lk.lower().replace("lat", "").replace("itude", "").strip("_")
        lon_candidates = [
            k
            for k in d
            if k.lower().replace("lon", "").replace("gitude", "").strip("_") == base
            and k.lower() in _LON_KEYS
            and isinstance(d[k], (int, float))
        ]
        if lon_candidates:
            lonk = lon_candidates[0]
            mgrs_str = to_mgrs(d[lk], d[lonk])
            label = f"GRID_{base}".upper().strip("_") if base else "GRID"
            out[label] = mgrs_str
            skip.add(lk)
            skip.add(lonk)
    for k, v in d.items():
        if k not in skip:
            out[k] = v
    return out


class ReportDetailDialog(QDialog):
    def __init__(self, report: Report, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{report.type}  —  {report.sender}")
        self.setMinimumSize(480, 400)
        self.setModal(True)

        layout = QVBoxLayout(self)

        # Header
        hdr = QLabel(
            f"<b style='color:{report.priority_color}'>[{report.priority}]</b> "
            f"&nbsp;{report.icon}&nbsp; <b>{report.type}</b>"
            f"&nbsp;&nbsp;&nbsp;<span style='color:#8b949e'>{report.sender}</span>"
            f"&nbsp;&nbsp;<small style='color:#6e7681'>{report.timestamp[:19]}</small>"
        )
        hdr.setTextFormat(Qt.TextFormat.RichText)
        hdr.setContentsMargins(8, 8, 8, 0)
        layout.addWidget(hdr)

        # Payload viewer
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        viewer.setFont(QFont("Courier New", 13))
        viewer.setPlainText(self._format_payload(report.payload))
        layout.addWidget(viewer, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    @staticmethod
    def _format_payload(payload) -> str:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return payload
        if isinstance(payload, dict):
            payload = _coords_to_mgrs(payload)
            lines = []
            for k, v in payload.items():
                lines.append(f"{str(k).upper():<24} {v}")
            return "\n".join(lines)
        return str(payload)
