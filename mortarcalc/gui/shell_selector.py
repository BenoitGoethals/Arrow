"""Reusable per-shell selection row.

A horizontal strip of one checkbox per ammunition (HE / SMOKE / ILLUM / WP …),
plus 'All' and 'None' shortcut buttons. Used by both the SectionPanel battery
view and the EditSectionDialog so the user can toggle every range arc on the
diagram individually.

The widget emits `selection_changed(set[str])` whenever the user changes the
selection. The set contains the upper-case shell names that should be visible.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QCheckBox, QPushButton, QLabel,
)

from ..ballistics import FireTableLibrary
from .position_diagram import AMMO_COLORS


class ShellSelector(QWidget):
    """Per-shell visibility picker, color-coded to match the diagram."""

    selection_changed = Signal(set)   # set[str] (upper-case shell names)

    def __init__(self, library: FireTableLibrary | None,
                 title: str = "Show ranges:",
                 initial: set[str] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.library = library
        self._checks: dict[str, QCheckBox] = {}
        self._initial = {s.upper() for s in (initial or set())}

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(QLabel(title))

        shells = library.shells() if library else []
        for i, shell in enumerate(shells):
            color = AMMO_COLORS[i % len(AMMO_COLORS)]
            cb = QCheckBox(shell)
            cb.setStyleSheet(
                f"QCheckBox {{ color: {color}; font-weight: bold; }}"
            )
            cb.setChecked(shell.upper() in self._initial)
            cb.toggled.connect(self._on_toggle)
            row.addWidget(cb)
            self._checks[shell.upper()] = cb

        row.addSpacing(6)
        b_all = QPushButton("All"); b_all.setMaximumWidth(50)
        b_none = QPushButton("None"); b_none.setMaximumWidth(60)
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none.clicked.connect(lambda: self._set_all(False))
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch(1)

        if not shells:
            placeholder = QLabel("(no firing tables loaded)")
            placeholder.setStyleSheet("color: #888; font-size: 11px;")
            row.addWidget(placeholder)

    # ---------------------------------------------------------- public API
    def selection(self) -> set[str]:
        return {sh for sh, cb in self._checks.items() if cb.isChecked()}

    def set_selection(self, shells: set[str]) -> None:
        wanted = {s.upper() for s in shells}
        for sh, cb in self._checks.items():
            cb.blockSignals(True)
            cb.setChecked(sh in wanted)
            cb.blockSignals(False)
        self.selection_changed.emit(self.selection())

    # ---------------------------------------------------------- internals
    def _set_all(self, state: bool) -> None:
        for cb in self._checks.values():
            cb.blockSignals(True)
            cb.setChecked(state)
            cb.blockSignals(False)
        self.selection_changed.emit(self.selection())

    def _on_toggle(self, _checked: bool) -> None:
        self.selection_changed.emit(self.selection())
