"""Arrow Front — Configuration dialog (Server · Display · GPS)."""

from __future__ import annotations


import httpx
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTabWidget,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QFrame,
    QComboBox,
    QSpinBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QFont

_S = QSettings("Arrow", "ArrowFront")

# ── Defaults ────────────────────────────────────────────────────────────────
DEFAULTS = {
    "server_url": "http://localhost:6001",
    "server_timeout": 10,
    "display_base_layer": "OSM",
    "display_show_trails": True,
    "display_voice_alerts": True,
    "gps_enabled": True,
    "gps_high_accuracy": True,
    "gps_max_age_ms": 4000,
    "gps_center_on_fix": True,
    "gps_show_accuracy": True,
}


def load(key: str):
    return _S.value(key, DEFAULTS.get(key))


def save_all(values: dict):
    for k, v in values.items():
        _S.setValue(k, v)


class ConfigDialog(QDialog):
    """Tabbed settings modal. Emits gps_config_changed after saving."""

    gps_config_changed = pyqtSignal(bool, bool, int, bool, bool)
    base_layer_changed = pyqtSignal(str)
    trails_changed = pyqtSignal(bool)
    voice_alerts_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Arrow Front — Configuration")
        self.setMinimumSize(520, 460)
        self.setMaximumSize(640, 560)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )
        self._build()
        self._load_values()

    # ─────────────────────────────────────────────────────────────────────
    # Build UI
    # ─────────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet("background:#161b22;border-bottom:1px solid #30363d;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 18, 0)
        title = QLabel("◆  CONFIGURATION")
        title.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        title.setStyleSheet("color:#3fb950;letter-spacing:2px;")
        hl.addWidget(title)
        hl.addStretch()
        root.addWidget(hdr)

        # ── Tabs ────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._build_server_tab(), "SERVER")
        self._tabs.addTab(self._build_display_tab(), "DISPLAY")
        self._tabs.addTab(self._build_gps_tab(), "GPS")
        root.addWidget(self._tabs, 1)

        # ── Footer ──────────────────────────────────────────────────────
        ftr = QFrame()
        ftr.setFixedHeight(52)
        ftr.setStyleSheet("background:#161b22;border-top:1px solid #30363d;")
        fl = QHBoxLayout(ftr)
        fl.setContentsMargins(18, 8, 18, 8)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color:#6e7681;font-size:10px;")
        fl.addWidget(self._status_lbl, 1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        fl.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryButton")
        save_btn.setFixedWidth(90)
        save_btn.clicked.connect(self._save)
        fl.addWidget(save_btn)

        root.addWidget(ftr)

    # ── Tab: SERVER ─────────────────────────────────────────────────────

    def _build_server_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lay.addWidget(_section("Connection"))

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._url = QLineEdit()
        self._url.setPlaceholderText("http://localhost:6001")
        form.addRow(_lbl("Server URL"), self._url)

        self._timeout = QSpinBox()
        self._timeout.setRange(3, 120)
        self._timeout.setSuffix("  s")
        self._timeout.setFixedWidth(80)
        form.addRow(_lbl("Timeout"), self._timeout)

        lay.addLayout(form)

        # Test connection row
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("Test Connection")
        self._test_btn.setFixedWidth(140)
        self._test_btn.clicked.connect(self._test_connection)
        self._test_result = QLabel("")
        self._test_result.setStyleSheet(
            "font-size:10px;font-family:'Courier New',monospace;"
        )
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._test_result, 1)
        lay.addLayout(test_row)

        lay.addStretch()
        return w

    # ── Tab: DISPLAY ────────────────────────────────────────────────────

    def _build_display_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lay.addWidget(_section("Map"))

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._base_layer = QComboBox()
        for name, label in [
            ("OSM", "OpenStreetMap"),
            ("DARK", "Dark (CartoDB)"),
            ("SATELLITE", "Satellite (Esri)"),
            ("TOPO", "Topo"),
        ]:
            self._base_layer.addItem(label, name)
        form.addRow(_lbl("Default base layer"), self._base_layer)

        lay.addLayout(form)

        lay.addWidget(_section("Overlays"))

        self._show_trails = QCheckBox("Show operator trails")
        lay.addWidget(self._show_trails)

        lay.addWidget(_section("Alerts"))

        self._voice_alerts = QCheckBox(
            "Voice alerts  (TTS + alarm tone on incoming alerts)"
        )
        lay.addWidget(self._voice_alerts)

        lay.addStretch()
        return w

    # ── Tab: GPS ────────────────────────────────────────────────────────

    def _build_gps_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lay.addWidget(_section("Own Position"))

        self._gps_enabled = QCheckBox("Enable GPS position tracking")
        self._gps_enabled.stateChanged.connect(self._on_gps_toggle)
        lay.addWidget(self._gps_enabled)

        self._gps_body = QWidget()
        gb = QVBoxLayout(self._gps_body)
        gb.setContentsMargins(16, 0, 0, 0)
        gb.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._gps_accuracy = QComboBox()
        self._gps_accuracy.addItem("High (enableHighAccuracy)", True)
        self._gps_accuracy.addItem("Low  (battery-saving)", False)
        form.addRow(_lbl("Accuracy mode"), self._gps_accuracy)

        self._gps_interval = QSpinBox()
        self._gps_interval.setRange(1, 60)
        self._gps_interval.setSuffix("  s")
        self._gps_interval.setFixedWidth(80)
        self._gps_interval.setToolTip("Maximum cached position age (maximumAge)")
        form.addRow(_lbl("Max position age"), self._gps_interval)

        gb.addLayout(form)

        self._gps_center = QCheckBox("Center map on first GPS fix")
        gb.addWidget(self._gps_center)

        self._gps_accuracy_circle = QCheckBox(
            "Show accuracy circle around own position"
        )
        gb.addWidget(self._gps_accuracy_circle)

        lay.addWidget(self._gps_body)
        lay.addStretch()

        note = QLabel(
            "GPS requires system Location Services to be enabled.\n"
            "On macOS: System Settings → Privacy → Location Services."
        )
        note.setStyleSheet("color:#484f58;font-size:9px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        return w

    # ─────────────────────────────────────────────────────────────────────
    # Load / Save
    # ─────────────────────────────────────────────────────────────────────

    def _load_values(self):
        # Server
        self._url.setText(str(load("server_url")))
        self._timeout.setValue(int(load("server_timeout")))

        # Display
        bl = str(load("display_base_layer"))
        idx = self._base_layer.findData(bl)
        self._base_layer.setCurrentIndex(max(idx, 0))

        st = load("display_show_trails")
        self._show_trails.setChecked(_bool(st, True))

        self._voice_alerts.setChecked(_bool(load("display_voice_alerts"), True))

        # GPS
        gps_en = _bool(load("gps_enabled"), True)
        self._gps_enabled.setChecked(gps_en)
        self._gps_body.setEnabled(gps_en)

        ha = _bool(load("gps_high_accuracy"), True)
        self._gps_accuracy.setCurrentIndex(0 if ha else 1)

        age_ms = int(load("gps_max_age_ms"))
        self._gps_interval.setValue(max(1, age_ms // 1000))

        self._gps_center.setChecked(_bool(load("gps_center_on_fix"), True))
        self._gps_accuracy_circle.setChecked(_bool(load("gps_show_accuracy"), True))

    def _save(self):
        values = {
            "server_url": self._url.text().strip().rstrip("/")
            or "http://localhost:6001",
            "server_timeout": self._timeout.value(),
            "display_base_layer": self._base_layer.currentData(),
            "display_show_trails": self._show_trails.isChecked(),
            "display_voice_alerts": self._voice_alerts.isChecked(),
            "gps_enabled": self._gps_enabled.isChecked(),
            "gps_high_accuracy": bool(self._gps_accuracy.currentData()),
            "gps_max_age_ms": self._gps_interval.value() * 1000,
            "gps_center_on_fix": self._gps_center.isChecked(),
            "gps_show_accuracy": self._gps_accuracy_circle.isChecked(),
        }
        save_all(values)

        self.gps_config_changed.emit(
            values["gps_enabled"],
            values["gps_high_accuracy"],
            values["gps_max_age_ms"],
            values["gps_center_on_fix"],
            values["gps_show_accuracy"],
        )
        self.base_layer_changed.emit(values["display_base_layer"])
        self.trails_changed.emit(values["display_show_trails"])
        self.voice_alerts_changed.emit(values["display_voice_alerts"])

        self._status_lbl.setText("Saved.")
        self.accept()

    # ─────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────

    def _on_gps_toggle(self, state: int):
        self._gps_body.setEnabled(state == Qt.CheckState.Checked.value)

    def _test_connection(self):
        url = self._url.text().strip().rstrip("/") or "http://localhost:6001"
        self._test_btn.setEnabled(False)
        self._test_result.setText("Testing…")
        try:
            r = httpx.get(
                f"{url}/health", timeout=float(self._timeout.value()), verify=False
            )
            if r.status_code == 200:
                data = r.json()
                ver = data.get("version", "")
                self._test_result.setText(f"● Connected  {ver}")
                self._test_result.setStyleSheet(
                    "color:#3fb950;font-size:10px;font-family:'Courier New',monospace;"
                )
            else:
                self._test_result.setText(f"○ HTTP {r.status_code}")
                self._test_result.setStyleSheet(
                    "color:#d29922;font-size:10px;font-family:'Courier New',monospace;"
                )
        except Exception as exc:
            msg = str(exc)
            short = msg[:48] if len(msg) > 48 else msg
            self._test_result.setText(f"○ {short}")
            self._test_result.setStyleSheet(
                "color:#f85149;font-size:10px;font-family:'Courier New',monospace;"
            )
        finally:
            self._test_btn.setEnabled(True)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color:#8b949e;font-size:9px;font-weight:600;letter-spacing:1.2px;"
    )
    return lbl


def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        "color:#484f58;font-size:8px;font-weight:700;letter-spacing:2px;"
        "padding-bottom:2px;border-bottom:1px solid #21262d;"
    )
    lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return lbl


def _bool(val, default: bool = True) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    if val is None:
        return default
    return bool(val)


def read_gps_config() -> tuple[bool, bool, int, bool, bool]:
    """Return current GPS config tuple for applying to the map."""
    return (
        _bool(load("gps_enabled"), True),
        _bool(load("gps_high_accuracy"), True),
        int(load("gps_max_age_ms")),
        _bool(load("gps_center_on_fix"), True),
        _bool(load("gps_show_accuracy"), True),
    )
