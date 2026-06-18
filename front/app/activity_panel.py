"""ActivityPanel — vertical icon bar + collapsible content for a window edge.

A slim, always-visible vertical icon strip (VS-Code activity-bar style) sits on
the left or right edge of the window. Clicking an icon opens that feature's
panel in the content area beside it. Clicking the active icon again collapses
the content, leaving only the icon strip.

    side="left"   →  [ bar | content ]   (bar on the left,  content on its right)
    side="right"  →  [ content | bar ]   (bar on the right, content on its left)

Usage:
    panel = ActivityPanel(side="left", default_width=270)
    panel.add_panel("orbat", "⊟", "ORBAT", orbat_widget, shortcut="O")
    splitter.addWidget(panel)
    panel.bind_splitter(splitter, index=0)   # call after addWidget

The collapse/expand logic resizes the bound splitter so the map reclaims the
space the content area gives up.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QStackedWidget, QPushButton, QSizePolicy, QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics


# ── Vertical nav button ──────────────────────────────────────────────────────

class _VertNavBtn(QPushButton):
    """A single activity-bar button — icon char over a small label, + badge."""

    def __init__(self, icon: str, label: str, shortcut: str = "", side: str = "left"):
        super().__init__()
        self._icon  = icon
        self._lbl   = label
        self._badge = 0
        self._sc    = shortcut
        self.setCheckable(True)
        self.setFixedHeight(50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label)
        accent_edge = "right" if side == "right" else "left"
        self.setStyleSheet(f"""
            QPushButton {{
                background: #161b22;
                border: none;
                border-{accent_edge}: 2px solid transparent;
                color: #6e7681;
                font-family: 'Courier New', monospace;
                padding: 0;
            }}
            QPushButton:hover:!checked {{
                background: #21262d;
                color: #c9d1d9;
            }}
            QPushButton:checked {{
                background: #0d1117;
                color: #79c0ff;
                border-{accent_edge}: 2px solid #1f6feb;
            }}
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

        # Icon (larger, upper portion)
        p.setPen(text_color)
        icon_font = QFont("Segoe UI Emoji", 15)
        p.setFont(icon_font)
        fm = QFontMetrics(icon_font)
        icon_w = fm.horizontalAdvance(self._icon)
        p.drawText(cx - icon_w // 2, 26, self._icon)

        # Label (small caps, lower portion)
        lbl_font = QFont("Courier New", 6, QFont.Weight.Bold)
        p.setFont(lbl_font)
        fm2 = QFontMetrics(lbl_font)
        lbl_w = fm2.horizontalAdvance(self._lbl)
        p.setPen(text_color)
        p.drawText(cx - lbl_w // 2, 42, self._lbl)

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
            bw  = max(fm3.horizontalAdvance(txt) + 6, 14)
            bh  = 13
            bx  = self.width() - bw - 3
            by  = 3
            p.setBrush(QColor("#f85149"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bx, by, bw, bh, bh // 2, bh // 2)
            p.setPen(QColor("#ffffff"))
            p.drawText(bx, by, bw, bh, Qt.AlignmentFlag.AlignCenter, txt)

        p.end()


# ── Activity panel ───────────────────────────────────────────────────────────

class ActivityPanel(QWidget):
    """Vertical icon bar + collapsible stacked content for a window edge."""

    panel_changed = pyqtSignal(str)
    toggled       = pyqtSignal(bool)   # True = content collapsed

    BAR_WIDTH = 46

    def __init__(self, side: str = "left", parent=None, default_width: int = 270):
        super().__init__(parent)
        self._side = "right" if side == "right" else "left"
        self._panels: dict[str, tuple[QWidget, _VertNavBtn]] = {}
        self._order:  list[str] = []
        self._current: str | None = None
        self._collapsed = False
        self._default_w = default_width          # width of the CONTENT area
        self._splitter: QSplitter | None = None
        self._splitter_idx = 0
        self._fallback: list[int] | None = None
        self._build()

    # ---- build ------------------------------------------------------------

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Always-visible vertical icon strip
        self._bar = QFrame()
        self._bar.setFixedWidth(self.BAR_WIDTH)
        sep_edge = "left" if self._side == "right" else "right"
        self._bar.setStyleSheet(
            "background:#161b22;"
            f"border-{sep_edge}:1px solid #21262d;"
        )
        self._bar_layout = QVBoxLayout(self._bar)
        self._bar_layout.setContentsMargins(0, 0, 0, 0)
        self._bar_layout.setSpacing(0)
        self._bar_layout.addStretch(1)           # buttons stack at the top

        # Collapsible content area
        self._content = QWidget()
        cl = QVBoxLayout(self._content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:#0d1117;")
        cl.addWidget(self._stack, 1)

        if self._side == "right":
            layout.addWidget(self._content, 1)
            layout.addWidget(self._bar)
        else:
            layout.addWidget(self._bar)
            layout.addWidget(self._content, 1)

        self.setMinimumWidth(self.BAR_WIDTH)

    # ---- public API -------------------------------------------------------

    def add_panel(self, name: str, icon: str, label: str,
                  widget: QWidget, shortcut: str = "") -> _VertNavBtn:
        btn = _VertNavBtn(icon, label, shortcut, side=self._side)
        btn.clicked.connect(lambda _checked, n=name: self.toggle_panel(n))
        # Insert above the trailing stretch so buttons stay top-aligned.
        self._bar_layout.insertWidget(self._bar_layout.count() - 1, btn)
        self._stack.addWidget(widget)
        self._panels[name] = (widget, btn)
        self._order.append(name)
        if self._current is None:
            self.activate(name)
        return btn

    def activate(self, name: str):
        """Show `name`'s panel, expanding the content area if collapsed."""
        if name not in self._panels:
            return
        widget, btn = self._panels[name]
        self._stack.setCurrentWidget(widget)
        for n, (_, b) in self._panels.items():
            b.setChecked(n == name)
        self._current = name
        btn.clear_badge()
        if self._collapsed:
            self._expand()
        self.panel_changed.emit(name)

    def toggle_panel(self, name: str):
        """Icon-click behaviour: collapse if `name` is already open, else open it."""
        if self._current == name and not self._collapsed:
            self._collapse()
            self._panels[name][1].setChecked(False)
        else:
            self.activate(name)

    def toggle(self):
        """Collapse/expand the current panel (keyboard shortcut / menu)."""
        if self._current is None:
            if self._order:
                self.activate(self._order[0])
            return
        self.toggle_panel(self._current)

    def collapse(self):
        if not self._collapsed:
            self._collapse()
            if self._current is not None:
                self._panels[self._current][1].setChecked(False)

    def expand(self):
        if self._collapsed:
            if self._current is not None:
                self.activate(self._current)
            elif self._order:
                self.activate(self._order[0])

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    # ---- badge API --------------------------------------------------------

    def set_badge(self, name: str, count: int):
        if name in self._panels and self._current != name:
            self._panels[name][1].set_badge(count)

    def inc_badge(self, name: str):
        if name in self._panels and self._current != name:
            btn = self._panels[name][1]
            btn.set_badge(btn._badge + 1)

    def current(self) -> str | None:
        return self._current

    def widget_for(self, name: str) -> QWidget | None:
        if name in self._panels:
            return self._panels[name][0]
        return None

    # ---- splitter integration --------------------------------------------

    def bind_splitter(self, splitter: QSplitter, index: int,
                      fallback: list[int] | None = None):
        self._splitter     = splitter
        self._splitter_idx = index
        self._fallback     = fallback

    def _expanded_width(self) -> int:
        return self.BAR_WIDTH + self._default_w

    def _fallback_sizes(self) -> list[int]:
        if self._fallback:
            return list(self._fallback)
        n = self._splitter.count() if self._splitter else 3
        sizes = [self.BAR_WIDTH] * max(n, 1)
        if len(sizes) > 1:
            sizes[1] = 900
        if 0 <= self._splitter_idx < len(sizes):
            sizes[self._splitter_idx] = self._expanded_width()
        return sizes

    def _collapse(self):
        if self._splitter is None:
            self._content.setVisible(False)
            self._collapsed = True
            self.toggled.emit(True)
            return
        sizes = self._splitter.sizes()
        if sum(sizes) == 0:
            sizes = self._fallback_sizes()
        current = sizes[self._splitter_idx]
        if current > self.BAR_WIDTH:
            self._default_w = current - self.BAR_WIDTH
        delta = self._default_w
        sizes[self._splitter_idx] = self.BAR_WIDTH
        if len(sizes) > 1:
            sizes[1] = max(sizes[1] + delta, 200)
        self._splitter.setSizes(sizes)
        self._content.setVisible(False)
        self._collapsed = True
        self.toggled.emit(True)

    def _expand(self):
        if self._splitter is None:
            self._content.setVisible(True)
            self._collapsed = False
            self.toggled.emit(False)
            return
        sizes = self._splitter.sizes()
        if sum(sizes) == 0:
            sizes = self._fallback_sizes()
        gained = self._default_w
        sizes[self._splitter_idx] = self._expanded_width()
        if len(sizes) > 1:
            sizes[1] = max(sizes[1] - gained, 200)
        self._splitter.setSizes(sizes)
        self._content.setVisible(True)
        self._collapsed = False
        self.toggled.emit(False)
