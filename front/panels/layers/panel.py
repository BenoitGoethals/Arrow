"""Map Visibility panel — grid of layer toggles with labels and badges."""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QCheckBox,
    QFrame,
    QPushButton,
)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont

# layer_key, icon, display_name, description, default_visible
MAP_LAYERS = [
    ("operators", "🎖", "Operators", "Friendly position markers (live tracking).", True),
    (
        "enemies",
        "⚔",
        "Enemy units",
        "Hostile forces & tactical objects (ENEMY / HOSTILE).",
        True,
    ),
    (
        "tactObjs",
        "📍",
        "Tactical objects",
        "POIs, objectives, markers, tactical control graphics.",
        True,
    ),
    (
        "fireMissions",
        "🎯",
        "Fire missions",
        "CFF markers and impact splashes on the map.",
        True,
    ),
    ("alerts", "🚨", "Alerts", "TIC / MEDICAL / EVAC / LOST_COMMS pulse rings.", True),
    (
        "cotTracks",
        "📡",
        "CoT tracks",
        "Foreign-UID Cursor-on-Target tracks (ATAK / simulator).",
        True,
    ),
    ("kml", "🗺", "KML layers", "Imported KML/KMZ overlay features.", True),
    (
        "cbrn",
        "☢",
        "CBRN zones",
        "Chemical, biological, radiological, nuclear overlays.",
        True,
    ),
    (
        "operTrails",
        "〰",
        "Operator trails",
        "Movement trail lines drawn behind operator tracks.",
        True,
    ),
    (
        "graphics",
        "✏",
        "Drawn graphics",
        "Lines, polygons, and other drawn tactical graphics.",
        True,
    ),
]


class _LayerCard(QFrame):
    toggled = pyqtSignal(str, bool)

    def __init__(self, key: str, icon: str, name: str, desc: str, visible: bool):
        super().__init__()
        self._key = key
        self.setObjectName("layerCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        self._cb = QCheckBox()
        self._cb.setChecked(visible)
        self._cb.stateChanged.connect(lambda s: self.toggled.emit(self._key, s == 2))
        root.addWidget(self._cb)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)

        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 14))
        title_row.addWidget(icon_lbl)

        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color:#c9d1d9;")
        title_row.addWidget(name_lbl)

        self._badge = QLabel("VISIBLE")
        self._badge.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._badge.setStyleSheet(
            "color:#3fb950;background:#0d2b0d;border:1px solid #238636;"
            "border-radius:3px;padding:0 4px;"
        )
        title_row.addWidget(self._badge)
        title_row.addStretch()
        text_col.addLayout(title_row)

        desc_lbl = QLabel(desc)
        desc_lbl.setFont(QFont("Courier New", 8))
        desc_lbl.setStyleSheet("color:#6e7681;")
        desc_lbl.setWordWrap(True)
        text_col.addWidget(desc_lbl)

        root.addLayout(text_col, 1)
        self._update_badge(visible)
        self._cb.stateChanged.connect(lambda s: self._update_badge(s == 2))

    def _update_badge(self, visible: bool):
        if visible:
            self._badge.setText("VISIBLE")
            self._badge.setStyleSheet(
                "color:#3fb950;background:#0d2b0d;border:1px solid #238636;"
                "border-radius:3px;padding:0 4px;"
            )
        else:
            self._badge.setText("HIDDEN")
            self._badge.setStyleSheet(
                "color:#f85149;background:#2d0d0d;border:1px solid #da3633;"
                "border-radius:3px;padding:0 4px;"
            )

    def is_visible(self) -> bool:
        return self._cb.isChecked()


class LayersDialog(QDialog):
    layer_toggled = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map Visibility")
        self.setMinimumWidth(820)
        self.setModal(False)
        self._cards: dict[str, _LayerCard] = {}
        self._build_ui()
        self.setStyleSheet("""
            QDialog { background:#0d1117; }
            QFrame#layerCard {
                background:#161b22; border:1px solid #21262d;
                border-radius:6px;
            }
            QFrame#layerCard:hover { border-color:#388bfd; }
            QLabel#sectionHdr {
                color:#8b949e; font-size:10px; font-weight:bold;
                letter-spacing:2px;
            }
            QPushButton#closeBtn {
                background:#21262d; color:#c9d1d9; border:1px solid #30363d;
                border-radius:4px; padding:4px 16px; font-family:'Courier New';
            }
            QPushButton#closeBtn:hover { background:#388bfd; border-color:#388bfd; color:#fff; }
        """)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("MAP VISIBILITY")
        title.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#c9d1d9;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕  Close")
        close_btn.setObjectName("closeBtn")
        close_btn.clicked.connect(self.close)
        hdr.addWidget(close_btn)
        root.addLayout(hdr)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#21262d;")
        root.addWidget(line)

        # Section label
        sec_lbl = QLabel("■  ON THE MAP")
        sec_lbl.setObjectName("sectionHdr")
        sec_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        sec_lbl.setContentsMargins(0, 4, 0, 2)
        root.addWidget(sec_lbl)

        # 2-column grid of cards
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (key, icon, name, desc, default) in enumerate(MAP_LAYERS):
            card = _LayerCard(key, icon, name, desc, default)
            card.toggled.connect(self.layer_toggled)
            self._cards[key] = card
            grid.addWidget(card, i // 2, i % 2)
        root.addLayout(grid)
        root.addStretch()

    def set_visible(self, key: str, visible: bool):
        if key in self._cards:
            self._cards[key]._cb.setChecked(visible)
