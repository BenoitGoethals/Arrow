"""Vertical pipeline timeline — one card per facade step + status + elapsed.

The widget is driven by two methods used by `MainWindow`:

* `reset()`               — all steps back to PENDING.
* `start_step(key, msg)`  — marks any previous RUNNING step COMPLETED, then
                            transitions `key` to RUNNING with the given
                            subtitle and starts its elapsed-time clock.
* `fail_current(msg)`     — moves the current RUNNING step to FAILED with the
                            error subtitle. Subsequent steps stay PENDING.

The `key` strings match the `PIPELINE` constants in `sim_gui.facade`. The
final step ("done") is treated like a checkpoint — once start_step("done")
fires every prior step is COMPLETED and the "done" card itself transitions
straight to COMPLETED.
"""

from __future__ import annotations

import time
from enum import Enum

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sim_gui.theme import (
    ACCENT,
    BG_RAISED,
    BORDER,
    DANGER,
    SUCCESS,
    TEXT_DIM,
    TEXT_MUTED,
)


class StepStatus(Enum):
    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3


# Step key, display title, default subtitle when pending.
STEPS: list[tuple[str, str, str]] = [
    ("cleanup", "Cleanup", "Wipe backend state + hierarchy + missions"),
    ("hierarchy", "Hierarchy", "Seed the 3 PARA / SOR ORBAT"),
    ("operators", "Operators", "Register and authenticate operators"),
    ("vehicles", "Vehicles", "Attach vehicles to combat sections"),
    ("mission", "Mission", "Create and start the mission"),
    ("opord", "OPORD", "Publish the 5-paragraph operations order"),
    ("overlay", "Overlay", "Inject scenario tactical objects"),
    ("done", "Done", "All steps completed"),
]


# ── Status indicator ─────────────────────────────────────────────────────────


class _StatusDot(QWidget):
    """A small animated status indicator drawn with QPainter."""

    DIAMETER = 14
    BOX = DIAMETER + 12  # widget bounds (for pulse halo)

    _PALETTE = {
        StepStatus.PENDING: ("#2a323d", "#3a4452"),
        StepStatus.RUNNING: ("#0b1018", ACCENT),
        StepStatus.COMPLETED: (SUCCESS, "#34d399"),
        StepStatus.FAILED: (DANGER, "#fca5a5"),
    }

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(self.BOX, self.BOX)
        self.status = StepStatus.PENDING
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_status(self, status: StepStatus) -> None:
        self.status = status
        if status == StepStatus.RUNNING:
            self._pulse = 0.0
            self._timer.start(40)
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.045) % 1.0
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = self.DIAMETER / 2.0
        fill, border = self._PALETTE[self.status]

        if self.status == StepStatus.RUNNING:
            ring = QColor(border)
            ring.setAlpha(int(140 * (1.0 - self._pulse)))
            extra = self._pulse * 8.0
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ring, 2))
            p.drawEllipse(
                int(cx - r - extra),
                int(cy - r - extra),
                int((r + extra) * 2),
                int((r + extra) * 2),
            )

        p.setBrush(QColor(fill))
        p.setPen(QPen(QColor(border), 2))
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        if self.status == StepStatus.COMPLETED:
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(int(cx - 3), int(cy + 1), int(cx - 1), int(cy + 3))
            p.drawLine(int(cx - 1), int(cy + 3), int(cx + 3), int(cy - 2))
        elif self.status == StepStatus.FAILED:
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(int(cx - 3), int(cy - 3), int(cx + 3), int(cy + 3))
            p.drawLine(int(cx - 3), int(cy + 3), int(cx + 3), int(cy - 3))


# ── Step row ────────────────────────────────────────────────────────────────


class _StepRow(QFrame):
    """One pipeline step rendered as a card."""

    def __init__(self, key: str, title: str, default_sub: str) -> None:
        super().__init__()
        self.key = key
        self._default_sub = default_sub
        self._start_ts: float | None = None

        self.setObjectName("StepRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.dot = _StatusDot()
        self.title_lbl = QLabel(title)
        tf = self.title_lbl.font()
        tf.setBold(True)
        tf.setPointSize(tf.pointSize() + 1)
        self.title_lbl.setFont(tf)

        self.sub_lbl = QLabel(default_sub)
        sf = QFont(self.sub_lbl.font())
        self.sub_lbl.setFont(sf)
        self.sub_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self.sub_lbl.setWordWrap(True)

        self.elapsed_lbl = QLabel("")
        self.elapsed_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: 'SF Mono', Menlo, monospace; font-size: 11px;"
        )
        self.elapsed_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.elapsed_lbl.setMinimumWidth(50)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 2, 0, 0)
        col.addWidget(self.title_lbl)
        col.addWidget(self.sub_lbl)
        row.addLayout(col, 1)
        row.addWidget(self.elapsed_lbl, 0, Qt.AlignmentFlag.AlignTop)

        self._apply_card_style(StepStatus.PENDING)

    # ── transitions ──────────────────────────────────────────────────────

    def set_pending(self) -> None:
        self.dot.set_status(StepStatus.PENDING)
        self.sub_lbl.setText(self._default_sub)
        self.sub_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self.elapsed_lbl.setText("")
        self._start_ts = None
        self._apply_card_style(StepStatus.PENDING)

    def set_running(self, msg: str) -> None:
        self.dot.set_status(StepStatus.RUNNING)
        self.sub_lbl.setText(msg or self._default_sub)
        self.sub_lbl.setStyleSheet(f"color: {ACCENT}; font-size: 11px;")
        self._start_ts = time.monotonic()
        self.elapsed_lbl.setText("…")
        self._apply_card_style(StepStatus.RUNNING)

    def set_completed(self, msg: str | None = None) -> None:
        self.dot.set_status(StepStatus.COMPLETED)
        if msg:
            self.sub_lbl.setText(msg)
        self.sub_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        if self._start_ts is not None:
            self.elapsed_lbl.setText(f"{time.monotonic() - self._start_ts:.2f}s")
        self._apply_card_style(StepStatus.COMPLETED)

    def set_failed(self, msg: str) -> None:
        self.dot.set_status(StepStatus.FAILED)
        self.sub_lbl.setText(msg or "failed")
        self.sub_lbl.setStyleSheet(f"color: {DANGER}; font-size: 11px;")
        if self._start_ts is not None:
            self.elapsed_lbl.setText(f"{time.monotonic() - self._start_ts:.2f}s")
        self._apply_card_style(StepStatus.FAILED)

    # ── styling ──────────────────────────────────────────────────────────

    def _apply_card_style(self, status: StepStatus) -> None:
        if status == StepStatus.RUNNING:
            border = ACCENT
            bg = "rgba(56, 189, 248, 0.07)"
        elif status == StepStatus.COMPLETED:
            border = BORDER
            bg = BG_RAISED
        elif status == StepStatus.FAILED:
            border = DANGER
            bg = "rgba(239, 68, 68, 0.10)"
        else:
            border = "transparent"
            bg = "transparent"
        self.setStyleSheet(
            f"#StepRow {{ background-color: {bg}; border: 1px solid {border};"
            f" border-radius: 8px; }}"
        )


# ── Timeline ─────────────────────────────────────────────────────────────────


class PipelineTimeline(QWidget):
    """Vertical timeline of pipeline steps."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, _StepRow] = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        for key, title, default_sub in STEPS:
            row = _StepRow(key, title, default_sub)
            self.rows[key] = row
            v.addWidget(row)
        v.addStretch(1)

        self.reset()

    def reset(self) -> None:
        for r in self.rows.values():
            r.set_pending()

    def start_step(self, key: str, msg: str = "") -> None:
        # Promote any in-flight step to COMPLETED first.
        for r in self.rows.values():
            if r.dot.status == StepStatus.RUNNING:
                r.set_completed()
        row = self.rows.get(key)
        if row is None:
            return
        if key == "done":
            row.set_running(msg or "finalising")
            row.set_completed(msg or "all steps completed")
        else:
            row.set_running(msg)

    def fail_current(self, msg: str) -> None:
        for r in self.rows.values():
            if r.dot.status == StepStatus.RUNNING:
                r.set_failed(msg)
                return
        # Nothing was running — fall back to the first PENDING step.
        for r in self.rows.values():
            if r.dot.status == StepStatus.PENDING:
                r.set_failed(msg)
                return
