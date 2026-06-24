"""Tab 'Ammunition' — per-gun stock view + inline editing + bulk resupply."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QGroupBox, QMessageBox,
    QAbstractItemView, QComboBox, QInputDialog,
)

from ..battery import Peloton, KNOWN_SHELLS


class AmmoPanel(QWidget):
    """Live per-piece ammunition stock with inline editing.

    Each piece × shell intersection has its own spinbox; changes are written
    straight to peloton.set_ammo and propagated via on_changed.
    """

    def __init__(
        self,
        peloton: Peloton,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.peloton = peloton
        self.on_changed = on_changed
        self._spinboxes: dict[tuple[str, str], QSpinBox] = {}
        self._suppress_signals = False

        root = QVBoxLayout(self)
        root.setSpacing(10)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_table(), stretch=1)
        root.addWidget(self._build_footer())

    # ------------------------------------------------------------------ build
    def _build_toolbar(self) -> QGroupBox:
        box = QGroupBox("Stock controls")
        row = QHBoxLayout(box)

        row.addWidget(QLabel("Low-ammo threshold:"))
        self.thresh_spin = QSpinBox()
        self.thresh_spin.setRange(0, 999)
        self.thresh_spin.setValue(self.peloton.low_ammo_threshold)
        self.thresh_spin.setSuffix(" rnd")
        self.thresh_spin.valueChanged.connect(self._on_threshold_changed)
        row.addWidget(self.thresh_spin)

        row.addSpacing(24)
        row.addWidget(QLabel("Resupply"))
        self.bulk_shell = QComboBox()
        self.bulk_shell.setEditable(True)
        for s in self._shells():
            self.bulk_shell.addItem(s, s)
        row.addWidget(self.bulk_shell)
        row.addWidget(QLabel("for all pieces to"))
        self.bulk_spin = QSpinBox()
        self.bulk_spin.setRange(0, 999)
        self.bulk_spin.setValue(30)
        self.bulk_spin.setSuffix(" rnd")
        row.addWidget(self.bulk_spin)
        b_bulk = QPushButton("Apply to all")
        b_bulk.clicked.connect(self._apply_bulk)
        row.addWidget(b_bulk)

        row.addStretch(1)

        b_add_shell = QPushButton("Add shell type…")
        b_add_shell.setToolTip(
            "Add a column for a new shell type (e.g. SMOKE, ILLUM)"
        )
        b_add_shell.clicked.connect(self._add_shell_type)
        row.addWidget(b_add_shell)
        return box

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, 0)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget::item { padding: 4px; }"
        )
        return self.table

    def _build_footer(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #888; font-size: 11px;")
        row.addWidget(self.summary)
        row.addStretch(1)
        return w

    # ------------------------------------------------------------------ data
    def _shells(self) -> list[str]:
        """KNOWN_SHELLS first (in canonical order), then any custom shells."""
        in_use: set[str] = set()
        for d in self.peloton.ammo.values():
            in_use.update(d.keys())
        # Canonical shells always shown as columns, even when stock is 0.
        ordered = list(KNOWN_SHELLS)
        extras = sorted(in_use - set(KNOWN_SHELLS))
        return ordered + extras

    # ------------------------------------------------------------------ refresh
    def refresh(self) -> None:
        shells = self._shells()
        self._suppress_signals = True

        # Sync bulk-shell combo without firing signals
        if hasattr(self, "bulk_shell"):
            prev = self.bulk_shell.currentText() or "HE"
            self.bulk_shell.blockSignals(True)
            self.bulk_shell.clear()
            for s in shells:
                self.bulk_shell.addItem(s, s)
            # restore previous selection if still present
            for i in range(self.bulk_shell.count()):
                if self.bulk_shell.itemData(i) == prev:
                    self.bulk_shell.setCurrentIndex(i); break
            self.bulk_shell.blockSignals(False)

        self.table.clear()
        self._spinboxes.clear()
        # Columns: Name, Section, [shells…], Status (HE-based)
        ncols = 2 + len(shells) + 1
        self.table.setColumnCount(ncols)
        headers = ["Piece", "Section"] + [f"{s} rounds" for s in shells] + ["Status"]
        self.table.setHorizontalHeaderLabels(headers)

        pieces = self.peloton.pieces
        self.table.setRowCount(len(pieces))
        for r, p in enumerate(pieces):
            # Piece name (cell 0)
            name_item = QTableWidgetItem(p.name)
            if p.is_base:
                name_item.setText(f"{p.name}  (base)")
                name_item.setForeground(QColor("#27ae60"))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, name_item)

            # Section (cell 1)
            g = self.peloton.group_of(p.name)
            sec_item = QTableWidgetItem(g.name if g else "—")
            sec_item.setFlags(sec_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, sec_item)

            # Shell spinboxes
            for j, shell in enumerate(shells):
                sb = QSpinBox()
                sb.setRange(0, 9999)
                sb.setValue(self.peloton.ammo_of(p.name, shell))
                sb.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                sb.valueChanged.connect(self._make_handler(p.name, shell))
                self.table.setCellWidget(r, 2 + j, sb)
                self._spinboxes[(p.name, shell)] = sb

            # Status cell (HE-based, last column)
            self._set_status_cell(r, p.name)

        self.table.resizeColumnsToContents()
        self._update_summary()
        self._suppress_signals = False

    def _set_status_cell(self, row: int, piece_name: str) -> None:
        he = self.peloton.ammo_of(piece_name, "HE")
        thresh = self.peloton.low_ammo_threshold
        if he == 0:
            text, color = "EMPTY", QColor("#c0392b")
        elif he <= thresh:
            text, color = f"LOW (≤{thresh})", QColor("#e67e22")
        else:
            text, color = "OK", QColor("#27ae60")
        item = QTableWidgetItem(text)
        item.setForeground(color)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.table.columnCount() - 1, item)

    def _update_summary(self) -> None:
        shells = self._shells()
        parts = []
        for s in shells:
            total = sum(self.peloton.ammo_of(p.name, s) for p in self.peloton.pieces)
            parts.append(f"{s}: {total}")
        low = self.peloton.low_ammo_pieces("HE")
        text = f"Platoon stock — {' · '.join(parts)}"
        if low:
            text += f"   ⚠ {len(low)} piece(s) low on HE: {', '.join(low)}"
        self.summary.setText(text)

    # ------------------------------------------------------------------ handlers
    def _make_handler(self, piece_name: str, shell: str):
        def _h(value: int) -> None:
            if self._suppress_signals:
                return
            self.peloton.set_ammo(piece_name, shell, value)
            # Update only the affected row's status + summary; no full rebuild
            for r in range(self.table.rowCount()):
                name_cell = self.table.item(r, 0)
                if name_cell is None:
                    continue
                # cell may show "name  (base)" — strip
                if name_cell.text().split("  ")[0] == piece_name:
                    self._set_status_cell(r, piece_name)
                    break
            self._update_summary()
            if self.on_changed:
                self.on_changed()
        return _h

    def _on_threshold_changed(self, value: int) -> None:
        if self._suppress_signals:
            return
        self.peloton.low_ammo_threshold = value
        for r, p in enumerate(self.peloton.pieces):
            self._set_status_cell(r, p.name)
        self._update_summary()
        if self.on_changed:
            self.on_changed()

    def _apply_bulk(self) -> None:
        data = self.bulk_shell.currentData()
        text = data if isinstance(data, str) else self.bulk_shell.currentText()
        shell = (text or "HE").strip().upper()
        if not self.peloton.pieces:
            QMessageBox.information(self, "No pieces", "No pieces to resupply.")
            return
        target = self.bulk_spin.value()
        if QMessageBox.question(
            self, "Resupply all",
            f"Set {shell} to {target} rounds on all {len(self.peloton.pieces)} piece(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,
        ) != QMessageBox.StandardButton.Yes:
            return
        for p in self.peloton.pieces:
            self.peloton.set_ammo(p.name, shell, target)
        self.refresh()
        if self.on_changed:
            self.on_changed()

    def _add_shell_type(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Add shell type",
            "Shell name (e.g. SMOKE, ILLUM):",
        )
        if not ok:
            return
        shell = text.strip().upper()
        if not shell:
            return
        # Seed every piece with 0 of this shell so the column appears
        for p in self.peloton.pieces:
            if shell not in self.peloton.ammo.get(p.name, {}):
                self.peloton.set_ammo(p.name, shell, 0)
        self.refresh()
        if self.on_changed:
            self.on_changed()

    # ------------------------------------------------------------------
    def showEvent(self, ev) -> None:  # type: ignore[override]
        self.refresh()
        super().showEvent(ev)
