"""Modal dialog for adding/editing a preplotted fire-plan target.

Replaces the inline form that used to live at the bottom of the Fire Plan tab
so the table of planned targets can take the full panel height.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox,
    QSpinBox, QPushButton, QComboBox, QCheckBox, QMessageBox, QGroupBox,
    QDialogButtonBox,
)

from ..battery import (
    Peloton, PlannedTarget,
    KNOWN_SHELLS, shell_label, normalise_shell,
)
from ..geo import mgrs_to_utm
from ..geo.current_location import get_current_position, LocationUnavailable
from .coord_dialog import prompt_position
from .mgrs_field import MgrsLineEdit


SHEAF_OPTIONS = ["converged", "parallel", "linear"]
TYPE_OPTIONS = ["point", "area", "linear"]
FUZE_OPTIONS = ["quick", "delay", "vt", "time", "illum"]


class PlannedTargetDialog(QDialog):
    """Modal CRUD dialog for a single PlannedTarget.

    Use with `target=None` to add a new one, or pass an existing target to
    edit it in-place. After accept(), `result_target` holds the value and
    `existing_target` is set to the dialog's `target` argument so the caller
    can perform an update-in-place.
    """

    def __init__(
        self,
        peloton: Peloton,
        target: PlannedTarget | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.peloton = peloton
        self.existing_target: PlannedTarget | None = target
        self.result_target: PlannedTarget | None = None

        self.setWindowTitle("Edit planned target" if target else "Add planned target")
        self.setModal(True)
        self.resize(560, 0)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- main form ----
        form_box = QGroupBox("Target details")
        form = QFormLayout(form_box)
        self.f_name = QLineEdit(); self.f_name.setPlaceholderText("e.g. AB1001")
        self.f_name.setMinimumWidth(220)
        self.f_mgrs = MgrsLineEdit(); self.f_mgrs.setMinimumWidth(220)
        self.f_alt = QDoubleSpinBox(); self.f_alt.setRange(-500, 9000); self.f_alt.setSuffix(" m")
        b_loc = QPushButton("Current location"); b_loc.clicked.connect(self._fill_loc)
        mgrs_row = QHBoxLayout(); mgrs_row.addWidget(self.f_mgrs, 1); mgrs_row.addWidget(b_loc)
        self.f_desc = QLineEdit(); self.f_desc.setPlaceholderText("e.g. crossroads N9 / church")
        self.f_type = QComboBox(); self.f_type.addItems(TYPE_OPTIONS)
        self.f_shell = QComboBox(); self.f_shell.setEditable(True)
        for s in KNOWN_SHELLS:
            self.f_shell.addItem(shell_label(s), s)
        self.f_fuze = QComboBox(); self.f_fuze.addItems(FUZE_OPTIONS)
        self.f_sheaf = QComboBox(); self.f_sheaf.addItems(SHEAF_OPTIONS)
        self.f_rounds = QSpinBox(); self.f_rounds.setRange(1, 50); self.f_rounds.setValue(3)
        self.f_group = QComboBox(); self.f_group.setEditable(True)
        self.f_group.addItem("")
        self.f_group.addItems([g.name for g in self.peloton.groups])

        form.addRow("Name", self.f_name)
        form.addRow("MGRS", mgrs_row)
        form.addRow("Altitude", self.f_alt)
        form.addRow("Description", self.f_desc)
        form.addRow("Target type", self.f_type)
        form.addRow("Munition", self.f_shell)
        form.addRow("Fuze", self.f_fuze)
        form.addRow("Sheaf", self.f_sheaf)
        form.addRow("Rounds/piece", self.f_rounds)
        form.addRow("Suggested section", self.f_group)
        root.addWidget(form_box)

        # ---- LINEAR-only parameters ----
        self.f_linear_box = QGroupBox("LINEAR parameters")
        lin_form = QFormLayout(self.f_linear_box)
        self.f_line_az = QDoubleSpinBox()
        self.f_line_az.setRange(0, 6399); self.f_line_az.setDecimals(0); self.f_line_az.setSuffix(" mils")
        self.f_line_len = QDoubleSpinBox()
        self.f_line_len.setRange(0, 5000); self.f_line_len.setValue(200); self.f_line_len.setSuffix(" m")
        lin_form.addRow("Line azimuth", self.f_line_az)
        lin_form.addRow("Line length", self.f_line_len)
        self.f_linear_box.setVisible(False)
        self.f_type.currentTextChanged.connect(
            lambda t: self.f_linear_box.setVisible(t == "linear")
        )
        self.f_sheaf.currentTextChanged.connect(
            lambda _t: self.f_linear_box.setVisible(
                self.f_type.currentText() == "linear"
                or self.f_sheaf.currentText() == "linear"
            )
        )
        root.addWidget(self.f_linear_box)

        # ---- timing + FPF ----
        timing_box = QGroupBox("Timing")
        t_form = QFormLayout(timing_box)
        self.f_on_call = QCheckBox("On Call (no fixed timing)")
        self.f_on_call.setChecked(True)
        self.f_offset = QSpinBox(); self.f_offset.setRange(-720, 720); self.f_offset.setSuffix(" min rel. to H")
        self.f_offset.setEnabled(False)
        self.f_duration = QSpinBox(); self.f_duration.setRange(0, 240); self.f_duration.setSuffix(" min")
        self.f_on_call.toggled.connect(lambda chk: self.f_offset.setEnabled(not chk))
        self.f_fpf = QCheckBox("FPF (Final Protective Fire)")
        t_form.addRow(self.f_on_call)
        t_form.addRow("Offset", self.f_offset)
        t_form.addRow("Duration (sustained)", self.f_duration)
        t_form.addRow(self.f_fpf)
        root.addWidget(timing_box)

        # ---- footer ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        if target is not None:
            self._load_from(target)
        self.f_name.setFocus()

    # ------------------------------------------------------------------ load
    def _load_from(self, t: PlannedTarget) -> None:
        self.f_name.setText(t.name)
        self.f_mgrs.setText(t.position.to_mgrs())
        self.f_alt.setValue(t.position.altitude_m)
        self.f_desc.setText(t.description)
        if t.target_type in TYPE_OPTIONS:
            self.f_type.setCurrentIndex(TYPE_OPTIONS.index(t.target_type))
        # shell match by data, fallback to raw text
        sh_norm = normalise_shell(t.shell)
        matched = False
        for i in range(self.f_shell.count()):
            if normalise_shell(str(self.f_shell.itemData(i) or "")) == sh_norm:
                self.f_shell.setCurrentIndex(i); matched = True; break
        if not matched:
            self.f_shell.setEditText(t.shell)
        if t.fuze in FUZE_OPTIONS:
            self.f_fuze.setCurrentIndex(FUZE_OPTIONS.index(t.fuze))
        if t.sheaf in SHEAF_OPTIONS:
            self.f_sheaf.setCurrentIndex(SHEAF_OPTIONS.index(t.sheaf))
        self.f_rounds.setValue(t.rounds_per_piece)
        self.f_group.setCurrentText(t.suggested_group)
        self.f_fpf.setChecked(t.is_fpf)
        self.f_line_az.setValue(t.line_azimuth_mils)
        self.f_line_len.setValue(t.line_length_m)
        self.f_linear_box.setVisible(
            t.target_type == "linear" or t.sheaf == "linear"
        )
        self.f_on_call.setChecked(t.start_offset_min is None)
        if t.start_offset_min is not None:
            self.f_offset.setValue(t.start_offset_min)
        self.f_duration.setValue(t.duration_min)

    # ------------------------------------------------------------------ submit
    def _fill_loc(self) -> None:
        try:
            pos = get_current_position()
        except LocationUnavailable as e:
            if QMessageBox.question(
                self, "GPS unavailable",
                f"{e}\n\nEnter coordinates manually?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            ) != QMessageBox.StandardButton.Yes:
                return
            pos = prompt_position(self)
            if pos is None:
                return
        self.f_mgrs.setText(pos.to_mgrs())
        self.f_alt.setValue(pos.altitude_m)

    def _shell_value(self) -> str:
        data = self.f_shell.currentData()
        if isinstance(data, str) and data:
            return normalise_shell(data)
        return normalise_shell(self.f_shell.currentText()) or "HE"

    def _on_ok(self) -> None:
        name = self.f_name.text().strip()
        if not name:
            QMessageBox.information(self, "Name", "Provide a name (e.g. AB1001).")
            return
        # Reject duplicates only when creating a new target with a clashing name.
        if self.existing_target is None and any(
            t.name == name for t in self.peloton.fire_plan
        ):
            QMessageBox.warning(
                self, "Duplicate",
                f"A target named '{name}' already exists. "
                "Choose another name or edit the existing one.",
            )
            return
        try:
            pos = mgrs_to_utm(self.f_mgrs.text().strip(), altitude_m=self.f_alt.value())
        except Exception as e:
            QMessageBox.warning(self, "MGRS", str(e)); return
        self.result_target = PlannedTarget(
            name=name, position=pos,
            description=self.f_desc.text().strip(),
            target_type=self.f_type.currentText(),
            shell=self._shell_value(),
            fuze=self.f_fuze.currentText(),
            sheaf=self.f_sheaf.currentText(),
            rounds_per_piece=self.f_rounds.value(),
            suggested_group=self.f_group.currentText().strip(),
            is_fpf=self.f_fpf.isChecked(),
            line_azimuth_mils=self.f_line_az.value(),
            line_length_m=self.f_line_len.value(),
            start_offset_min=None if self.f_on_call.isChecked() else self.f_offset.value(),
            duration_min=self.f_duration.value(),
        )
        self.accept()
