"""Tab 'Firing Tables' — upload ballistic tables and link them to ammunition.

The platoon fires several natures (HE, ILLUM, SMOKE, WP, …); each has its own
ballistic table. This panel manages a global library: upload a firing-table
JSON, link it to a shell type, pick the default fallback, and remove links.
Fire missions then resolve the right table from `FireMission.shell`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QGroupBox, QMessageBox, QFileDialog,
    QInputDialog, QAbstractItemView, QTreeWidget, QTreeWidgetItem,
)

from ..ballistics import FireTable, FireTableLibrary, FireTableRepository
from ..battery import KNOWN_SHELLS


class FireTablePanel(QWidget):
    """Manage the firing-table library: upload, link to shell, set default."""

    def __init__(
        self,
        library: FireTableLibrary,
        repository: FireTableRepository,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.library = library
        self.repository = repository
        self.on_changed = on_changed

        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "Upload a firing-table JSON and link it to an ammunition type. "
            "Fire missions automatically use the table that matches their shell; "
            "shells without their own table fall back to the <b>default</b>."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        root.addWidget(self._build_toolbar())

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self._build_table())
        split.addWidget(self._build_detail())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        root.addWidget(split, stretch=1)

        self.refresh()

    # ------------------------------------------------------------------ build
    def _build_toolbar(self) -> QGroupBox:
        box = QGroupBox("Library")
        row = QHBoxLayout(box)
        b_upload = QPushButton("Upload firing table…")
        b_upload.clicked.connect(self._upload)
        b_relink = QPushButton("Re-link to shell…")
        b_relink.clicked.connect(self._relink_selected)
        b_default = QPushButton("Set as default")
        b_default.clicked.connect(self._set_default_selected)
        b_remove = QPushButton("Remove")
        b_remove.setStyleSheet("color: #c0392b;")
        b_remove.clicked.connect(self._remove_selected)
        row.addWidget(b_upload)
        row.addStretch(1)
        row.addWidget(b_relink)
        row.addWidget(b_default)
        row.addWidget(b_remove)
        return box

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Shell (link)", "Table name", "Fuze", "Charges", "Range coverage", "Default"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._show_detail)
        return self.table

    def _build_detail(self) -> QGroupBox:
        box = QGroupBox("Firing table")
        lay = QVBoxLayout(box)
        self.detail_title = QLabel("Select a firing table above to view its data.")
        self.detail_title.setWordWrap(True)
        lay.addWidget(self.detail_title)
        self.detail_tree = QTreeWidget()
        self.detail_tree.setHeaderLabels(
            ["Charge / Range", "Elevation", "Time of flight", "Drift", "ΔR per 100 m Δh"]
        )
        self.detail_tree.setRootIsDecorated(True)
        self.detail_tree.setAlternatingRowColors(True)
        lay.addWidget(self.detail_tree, stretch=1)
        return box

    # ------------------------------------------------------------------ refresh
    def refresh(self) -> None:
        shells = self.library.shells()
        self.table.setRowCount(len(shells))
        for i, shell in enumerate(shells):
            ft = self.library.tables[shell]
            lo, hi = ft.range_span_m
            cells = [
                shell,
                ft.shell,
                str(ft.fuze),
                str(len(ft.charges)),
                f"{lo:.0f}–{hi:.0f} m",
                "✓ default" if self.library.is_default(shell) else "",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, shell)
                self.table.setItem(i, col, item)
        if shells and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._show_detail()

    def _show_detail(self) -> None:
        """Populate the lower pane with the selected table's charges and rows."""
        self.detail_tree.clear()
        shell = self._selected_shell()
        if shell is None or shell not in self.library.tables:
            self.detail_title.setText("Select a firing table above to view its data.")
            return
        ft = self.library.tables[shell]
        lo, hi = ft.range_span_m
        self.detail_title.setText(
            f"<b>{shell}</b> → {ft.shell}  ·  fuze {ft.fuze}  ·  "
            f"{len(ft.charges)} charge(s)  ·  {lo:.0f}–{hi:.0f} m  ·  "
            f"columns in mils / seconds / metres"
        )
        for c in ft.charges:
            top = QTreeWidgetItem([
                f"Charge {c.id}   ({c.min_range_m:.0f}–{c.max_range_m:.0f} m, "
                f"MV {c.muzzle_velocity_mps:.0f} m/s)",
                "", "", "", "",
            ])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            for r in c.rows:
                child = QTreeWidgetItem([
                    f"{r.range_m:.0f} m",
                    f"{r.elevation_mils:.0f}",
                    f"{r.tof_s:.1f} s",
                    f"{r.drift_mils:.0f}",
                    f"{r.dR_per_100m_height:.0f} m",
                ])
                for col in range(1, 5):
                    child.setTextAlignment(col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                top.addChild(child)
            self.detail_tree.addTopLevelItem(top)
        self.detail_tree.expandAll()
        for col in range(self.detail_tree.columnCount()):
            self.detail_tree.resizeColumnToContents(col)

    # ------------------------------------------------------------------ helpers
    def _selected_shell(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _shell_choices(self) -> list[str]:
        """Known natures first, then any custom links already in the library."""
        seen = list(KNOWN_SHELLS)
        for s in self.library.shells():
            if s not in seen:
                seen.append(s)
        return seen

    def _ask_shell(self, title: str, suggested: str = "") -> str | None:
        choices = self._shell_choices()
        current = choices.index(suggested) if suggested in choices else 0
        shell, ok = QInputDialog.getItem(
            self, title,
            "Link to ammunition (pick or type a custom name, e.g. HE, ILLUM, HR):",
            choices, current, editable=True,
        )
        if not ok:
            return None
        shell = shell.strip()
        return shell or None

    def _commit(self) -> None:
        """Persist the library and notify the rest of the app."""
        try:
            self.repository.save(self.library)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", f"Could not save firing tables:\n{e}")
        self.refresh()
        if self.on_changed:
            self.on_changed()

    # ------------------------------------------------------------------ actions
    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Upload firing table", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            table: FireTable = self.repository.import_file(Path(path))
        except Exception as e:
            QMessageBox.critical(
                self, "Invalid firing table",
                f"Could not read this firing table:\n{e}",
            )
            return
        # Suggest a shell from the table's own name (e.g. "M821 HE 81mm" → HE).
        suggested = next(
            (s for s in KNOWN_SHELLS if s in table.shell.upper()), ""
        )
        shell = self._ask_shell("Link firing table", suggested)
        if shell is None:
            return
        if self.library.get(shell) is not None and QMessageBox.question(
            self, "Replace table",
            f"A firing table is already linked to '{shell.upper()}'. Replace it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.library.add(shell, table)
        self._commit()

    def _relink_selected(self) -> None:
        shell = self._selected_shell()
        if shell is None:
            QMessageBox.information(self, "No selection", "Select a firing table first.")
            return
        new_shell = self._ask_shell("Re-link firing table", shell)
        if new_shell is None or new_shell.upper() == shell.upper():
            return
        table = self.library.tables[shell]
        was_default = self.library.is_default(shell)
        self.library.remove(shell)
        self.library.add(new_shell, table)
        if was_default:
            self.library.set_default(new_shell)
        self._commit()

    def _set_default_selected(self) -> None:
        shell = self._selected_shell()
        if shell is None:
            QMessageBox.information(self, "No selection", "Select a firing table first.")
            return
        self.library.set_default(shell)
        self._commit()

    def _remove_selected(self) -> None:
        shell = self._selected_shell()
        if shell is None:
            QMessageBox.information(self, "No selection", "Select a firing table first.")
            return
        if QMessageBox.question(
            self, "Remove firing table",
            f"Remove the firing table linked to '{shell}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.library.remove(shell)
        self._commit()
