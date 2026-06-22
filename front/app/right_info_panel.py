"""RightInfoPanel — icon-button navigation + stacked content panels.

Replaces the plain QTabWidget with a military-style panel selector:
  - Compact icon+label nav strip at the top
  - Badge overlays for unread counts (painted in paintEvent)
  - QStackedWidget content below
  - Keyboard shortcuts 1-5 to switch panels
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QStackedWidget,
    QPushButton,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics

# ── Nav button ───────────────────────────────────────────────────────────────


class _NavBtn(QPushButton):
    """Single navigation button — icon char + label + optional badge."""

    def __init__(self, icon: str, label: str, shortcut: str = ""):
        super().__init__()
        self._icon = icon
        self._lbl = label
        self._badge = 0
        self._sc = shortcut
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

    # ---- style ------------------------------------------------------------

    def _apply_style(self):
        self.setStyleSheet("""
            QPushButton {
                background: #161b22;
                border: none;
                border-right: 1px solid #21262d;
                color: #6e7681;
                font-family: 'Courier New', monospace;
                padding: 0;
            }
            QPushButton:hover:!checked {
                background: #21262d;
                color: #c9d1d9;
            }
            QPushButton:checked {
                background: #0d1117;
                color: #79c0ff;
                border-bottom: 2px solid #1f6feb;
            }
        """)

    # ---- badge API --------------------------------------------------------

    def set_badge(self, count: int):
        self._badge = max(0, count)
        self.update()

    def clear_badge(self):
        self.set_badge(0)

    # ---- painting ---------------------------------------------------------

    def paintEvent(self, event):
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() // 2

        active = self.isChecked()
        text_color = QColor("#79c0ff" if active else "#6e7681")
        if self.underMouse() and not active:
            text_color = QColor("#c9d1d9")

        # Icon (larger)
        p.setPen(text_color)
        icon_font = QFont("Segoe UI Emoji", 14)
        p.setFont(icon_font)
        fm = QFontMetrics(icon_font)
        icon_w = fm.horizontalAdvance(self._icon)
        p.drawText(cx - icon_w // 2, 22, self._icon)

        # Label (small caps)
        lbl_font = QFont("Courier New", 7, QFont.Weight.Bold)
        p.setFont(lbl_font)
        fm2 = QFontMetrics(lbl_font)
        lbl_w = fm2.horizontalAdvance(self._lbl)
        p.setPen(text_color)
        p.drawText(cx - lbl_w // 2, 36, self._lbl)

        # Shortcut hint (very small, top-left)
        if self._sc:
            sc_font = QFont("Courier New", 6)
            p.setFont(sc_font)
            p.setPen(QColor("#30363d"))
            p.drawText(3, 9, self._sc)

        # Badge (top-right red bubble)
        if self._badge > 0:
            txt = str(min(self._badge, 99))
            badge_font = QFont("Courier New", 7, QFont.Weight.Bold)
            p.setFont(badge_font)
            fm3 = QFontMetrics(badge_font)
            bw = max(fm3.horizontalAdvance(txt) + 6, 14)
            bh = 13
            bx = self.width() - bw - 3
            by = 3
            p.setBrush(QColor("#f85149"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bx, by, bw, bh, bh // 2, bh // 2)
            p.setPen(QColor("#ffffff"))
            p.drawText(bx, by, bw, bh, Qt.AlignmentFlag.AlignCenter, txt)

        p.end()


# ── Panel container ──────────────────────────────────────────────────────────


class RightInfoPanel(QWidget):
    """Icon-navigation + stacked content for the right info panel."""

    panel_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: dict[str, tuple[QWidget, _NavBtn]] = {}
        self._order: list[str] = []
        self._current: str | None = None
        self._build()

    # ---- build ------------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Navigation strip
        nav_frame = QFrame()
        nav_frame.setFixedHeight(44)
        nav_frame.setStyleSheet(
            "background:#161b22;" "border-bottom:2px solid #21262d;"
        )
        self._nav_layout = QHBoxLayout(nav_frame)
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(0)
        root.addWidget(nav_frame)

        # Content stack
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:#0d1117;")
        root.addWidget(self._stack, 1)

    # ---- public API -------------------------------------------------------

    def add_panel(
        self, name: str, icon: str, label: str, widget: QWidget, shortcut: str = ""
    ) -> _NavBtn:
        btn = _NavBtn(icon, label, shortcut)
        btn.clicked.connect(lambda _checked, n=name: self.activate(n))
        self._nav_layout.addWidget(btn)
        self._stack.addWidget(widget)
        self._panels[name] = (widget, btn)
        self._order.append(name)
        if self._current is None:
            self.activate(name)
        return btn

    def activate(self, name: str):
        if name not in self._panels:
            return
        widget, btn = self._panels[name]
        self._stack.setCurrentWidget(widget)
        for n, (_, b) in self._panels.items():
            b.setChecked(n == name)
        self._current = name
        # Clear badge on activation
        btn.clear_badge()
        self.panel_changed.emit(name)

    def set_badge(self, name: str, count: int):
        if name in self._panels and self._current != name:
            _, btn = self._panels[name]
            btn.set_badge(count)

    def inc_badge(self, name: str):
        if name in self._panels and self._current != name:
            _, btn = self._panels[name]
            btn.set_badge(btn._badge + 1)

    def current(self) -> str | None:
        return self._current

    def widget_for(self, name: str) -> QWidget | None:
        if name in self._panels:
            return self._panels[name][0]
        return None
