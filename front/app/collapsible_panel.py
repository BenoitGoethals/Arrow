"""CollapsibleSidePanel — resizable panel with a thin toggle strip.

Usage:
    panel = CollapsibleSidePanel(content_widget, title="ORBAT", side="left")
    splitter.addWidget(panel)
    panel.bind_splitter(splitter, index=0)       # call after addWidget
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QSplitter, QSizePolicy,
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics


class _ToggleStrip(QWidget):
    """Thin vertical strip — the collapse/expand hit target."""
    clicked = pyqtSignal()

    def __init__(self, title: str, side: str):
        super().__init__()
        self._title  = title.upper()
        self._side   = side          # 'left' or 'right'
        self._collapsed = False
        self.setFixedWidth(18)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{'Collapse' if not self._collapsed else 'Expand'} {title}")

    def set_collapsed(self, c: bool):
        self._collapsed = c
        self.update()

    def mousePressEvent(self, _):
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        p.fillRect(self.rect(), QColor("#161b22"))

        # Border on the inner edge
        p.setPen(QColor("#30363d"))
        if self._side == "left":
            p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        else:
            p.drawLine(0, 0, 0, self.height())

        # Chevron
        cx = self.width() // 2
        arrow_y = self.height() // 2
        p.setPen(QColor("#484f58"))
        if self._side == "left":
            ch = "‹" if not self._collapsed else "›"
        else:
            ch = "›" if not self._collapsed else "‹"

        font = QFont("Courier New", 13, QFont.Weight.Bold)
        p.setFont(font)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(ch)
        p.drawText(cx - tw // 2, arrow_y + fm.ascent() // 2, ch)

        # Vertical title text (when expanded)
        if not self._collapsed:
            p.save()
            p.translate(cx, arrow_y - 20)
            p.rotate(-90)
            font2 = QFont("Courier New", 7, QFont.Weight.Bold)
            p.setFont(font2)
            p.setPen(QColor("#30363d"))
            p.drawText(-30, 4, self._title)
            p.restore()

        p.end()


class CollapsibleSidePanel(QWidget):
    """
    A content panel with a toggle strip on its inner edge.
    side='left'  → strip is on the right of the content
    side='right' → strip is on the left  of the content
    """
    toggled = pyqtSignal(bool)   # True = collapsed

    def __init__(self, content: QWidget, title: str, side: str = "left",
                 default_width: int = 280):
        super().__init__()
        self._content      = content
        self._side         = side
        self._collapsed    = False
        self._default_w    = default_width
        self._splitter: QSplitter | None = None
        self._splitter_idx: int = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._strip = _ToggleStrip(title, side)
        self._strip.clicked.connect(self.toggle)

        if side == "left":
            layout.addWidget(content, 1)
            layout.addWidget(self._strip)
        else:
            layout.addWidget(self._strip)
            layout.addWidget(content, 1)

        self.setMinimumWidth(18)

    # ---- API ---------------------------------------------------------------

    def bind_splitter(self, splitter: QSplitter, index: int):
        self._splitter     = splitter
        self._splitter_idx = index

    def toggle(self):
        if self._splitter is None:
            return
        if self._collapsed:
            self._expand()
        else:
            self._collapse()

    def collapse(self):
        if not self._collapsed:
            self._collapse()

    def expand(self):
        if self._collapsed:
            self._expand()

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    # ---- Private -----------------------------------------------------------

    def _collapse(self):
        sizes = self._splitter.sizes()
        # Guard: splitter not yet laid out (all zeros before window shown)
        if sum(sizes) == 0:
            sizes = [270, 900, 360]

        current = sizes[self._splitter_idx]
        if current > 18:
            self._default_w = current
        # Only redistribute if map index exists
        delta = self._default_w - 18
        sizes[self._splitter_idx] = 18
        if len(sizes) > 1:
            sizes[1] = max(sizes[1] + delta, 200)
        self._splitter.setSizes(sizes)
        self._content.setVisible(False)
        self._strip.set_collapsed(True)
        self._collapsed = True
        self.toggled.emit(True)

    def _expand(self):
        sizes = self._splitter.sizes()
        if sum(sizes) == 0:
            sizes = [270, 900, 18]
        gained = self._default_w - 18
        sizes[self._splitter_idx] = self._default_w
        if len(sizes) > 1:
            sizes[1] = max(sizes[1] - gained, 200)
        self._splitter.setSizes(sizes)
        self._content.setVisible(True)
        self._strip.set_collapsed(False)
        self._collapsed = False
        self.toggled.emit(False)
