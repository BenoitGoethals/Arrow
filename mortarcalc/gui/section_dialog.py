"""Modal dialog for editing a fire section: PDF, members, lay-on-watch."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QDoubleSpinBox, QComboBox, QGroupBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QTableWidget, QTableWidgetItem, QMessageBox,
    QDialogButtonBox,
)

from ..ballistics import FireTableLibrary
from ..battery import Peloton, Group, lay_on_watch
from .position_diagram import SectionDiagram
from .shell_selector import ShellSelector


class EditSectionDialog(QDialog):
    """Edit one section. Returns deleted=True via .deleted if user removed it."""

    def __init__(
        self,
        peloton: Peloton,
        group: Group,
        on_changed: Callable[[], None],
        library: FireTableLibrary | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.peloton = peloton
        self.group = group
        self.on_changed = on_changed
        self.library = library
        self.deleted: bool = False

        self.setWindowTitle(f"Section '{group.name}'")
        self.setModal(True)
        self.resize(620, 640)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- header ----
        header = QLabel(f"<b>Section '{group.name}'</b>")
        header.setStyleSheet("font-size: 14px;")
        root.addWidget(header)

        # ---- PDF + sector limits ----
        pdf_box = QGroupBox("Sector of fire (watch)")
        pdf_form = QFormLayout(pdf_box)
        self.pdf_spin = QDoubleSpinBox()
        self.pdf_spin.setRange(0, 6399)
        self.pdf_spin.setDecimals(0)
        self.pdf_spin.setSuffix(" mils")
        self.pdf_spin.setValue(group.pdf_mils)
        self.pdf_spin.valueChanged.connect(self._on_pdf_changed)
        pdf_form.addRow("PDF", self.pdf_spin)

        self.left_spin = QDoubleSpinBox()
        self.left_spin.setRange(0, 6399); self.left_spin.setDecimals(0)
        self.left_spin.setSuffix(" mils"); self.left_spin.setValue(group.left_limit_mils)
        self.left_spin.valueChanged.connect(self._on_limits_changed)
        self.right_spin = QDoubleSpinBox()
        self.right_spin.setRange(0, 6399); self.right_spin.setDecimals(0)
        self.right_spin.setSuffix(" mils"); self.right_spin.setValue(group.right_limit_mils)
        self.right_spin.valueChanged.connect(self._on_limits_changed)
        self.max_range_spin = QDoubleSpinBox()
        self.max_range_spin.setRange(0, 30000); self.max_range_spin.setDecimals(0)
        self.max_range_spin.setSuffix(" m"); self.max_range_spin.setValue(group.max_range_m)
        self.max_range_spin.setSpecialValueText("(use firing-table max)")
        self.max_range_spin.setToolTip(
            "Optional cap on the range envelopes shown on the diagram and map.\n"
            "0 = no override; the firing-table maximum is used."
        )
        self.max_range_spin.valueChanged.connect(self._on_max_range_changed)
        pdf_form.addRow("Left limit", self.left_spin)
        pdf_form.addRow("Right limit", self.right_spin)
        pdf_form.addRow("Max range", self.max_range_spin)
        hint = QLabel("Sector runs clockwise from left to right limit. "
                      "Equal limits = unrestricted.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #95a5a6; font-size: 11px;")
        pdf_form.addRow("", hint)
        root.addWidget(pdf_box)

        # ---- per-shell range selector + live diagram for this section ----
        self.diagram = SectionDiagram(
            self.peloton, self.group, library=self.library, parent=self
        )
        self.shell_selector = ShellSelector(
            library=self.library, title="Show ranges:",
        )
        self.shell_selector.selection_changed.connect(
            self.diagram.set_visible_shells
        )
        root.addWidget(self.shell_selector)
        root.addWidget(self.diagram)

        # ---- members ----
        mem_box = QGroupBox("Pieces in this section")
        mem_layout = QVBoxLayout(mem_box)
        self.members_list = QListWidget()
        self.members_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.members_list.setMaximumHeight(120)
        self._populate_members()
        b_apply = QPushButton("Apply piece assignment")
        b_apply.clicked.connect(self._apply_members)
        mem_layout.addWidget(self.members_list)
        mem_layout.addWidget(b_apply)
        root.addWidget(mem_box)

        # ---- lay on watch ----
        lay_box = QGroupBox("Lay on watch — sight settings")
        l_layout = QVBoxLayout(lay_box)
        ap_row = QHBoxLayout()
        self.ap_combo = QComboBox()
        self.ap_combo.addItems([ap.name for ap in self.peloton.aiming_points])
        b_compute = QPushButton("Compute")
        b_compute.clicked.connect(self._compute_lay)
        ap_row.addWidget(QLabel("Aiming point:"))
        ap_row.addWidget(self.ap_combo, 1)
        ap_row.addWidget(b_compute)
        self.lay_table = QTableWidget(0, 4)
        self.lay_table.setHorizontalHeaderLabels(
            ["Piece", "Sight (mils)", "Az → AP", "Distance AP"]
        )
        self.lay_table.verticalHeader().setVisible(False)
        self.lay_table.setMaximumHeight(140)
        l_layout.addLayout(ap_row)
        l_layout.addWidget(self.lay_table)
        root.addWidget(lay_box)

        root.addStretch(1)

        # ---- footer: Delete + Close ----
        footer = QHBoxLayout()
        b_del = QPushButton("Delete section")
        b_del.setStyleSheet("color: #c0392b;")
        b_del.clicked.connect(self._delete_section)
        footer.addWidget(b_del)
        footer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Save && Close")
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        footer.addWidget(buttons)
        root.addLayout(footer)

    # ------------------------------------------------------------------ handlers
    def _on_pdf_changed(self, val: float) -> None:
        self.group.set_pdf(val)
        self.diagram.update()
        self.on_changed()

    def _on_limits_changed(self, _val: float = 0.0) -> None:
        self.group.set_limits(self.left_spin.value(), self.right_spin.value())
        self.diagram.update()
        self.on_changed()

    def _on_max_range_changed(self, val: float) -> None:
        self.group.max_range_m = float(val)
        self.diagram.update()
        self.on_changed()

    def _populate_members(self) -> None:
        self.members_list.clear()
        for p in self.peloton.pieces:
            item = QListWidgetItem(p.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            in_this = p.name in self.group.member_names
            item.setCheckState(Qt.CheckState.Checked if in_this else Qt.CheckState.Unchecked)
            other = self.peloton.group_of(p.name)
            if other is not None and other.name != self.group.name:
                item.setText(f"{p.name}  (now in '{other.name}')")
            self.members_list.addItem(item)

    def _apply_members(self) -> None:
        for i in range(self.members_list.count()):
            it = self.members_list.item(i)
            pname = it.text().split("  (now in")[0]
            if it.checkState() == Qt.CheckState.Checked:
                self.peloton.assign_piece_to_group(pname, self.group.name)
            else:
                if pname in self.group.member_names:
                    self.group.member_names.remove(pname)
        self._populate_members()
        self.diagram.update()
        self.on_changed()

    def _compute_lay(self) -> None:
        if not self.group.member_names:
            QMessageBox.information(self, "No pieces",
                "Assign pieces to this section first.")
            return
        if not self.peloton.aiming_points:
            QMessageBox.information(self, "No aiming points",
                "Add at least one aiming point.")
            return
        ap = self.peloton.aiming_point(self.ap_combo.currentText())
        settings = lay_on_watch(self.peloton, self.group, ap)
        self.lay_table.setRowCount(len(settings))
        for i, s in enumerate(settings):
            self.lay_table.setItem(i, 0, QTableWidgetItem(s.piece))
            self.lay_table.setItem(i, 1, QTableWidgetItem(f"{s.sight_mils:.0f}"))
            self.lay_table.setItem(i, 2, QTableWidgetItem(f"{s.azimuth_to_ap_mils:.0f}"))
            warn = "  parallax!" if s.range_to_ap_m < 500 else ""
            self.lay_table.setItem(i, 3, QTableWidgetItem(f"{s.range_to_ap_m:.0f} m{warn}"))

    def _delete_section(self) -> None:
        if QMessageBox.question(
            self, "Delete section",
            f"Delete section '{self.group.name}'? Pieces become unassigned.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.peloton.remove_group(self.group.name)
        self.deleted = True
        self.on_changed()
        self.accept()
