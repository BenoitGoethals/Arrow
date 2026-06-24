"""Modal Call-For-Fire entry dialog.

Used from the Fire Missions tab to start a new fire mission for a section.
Replaces the cramped inline form that used to live in the detail panel.
"""
from __future__ import annotations

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QLineEdit, QDoubleSpinBox,
    QSpinBox, QGroupBox, QComboBox, QMessageBox, QLabel,
    QStackedWidget, QWidget, QDialogButtonBox,
)

from ..ballistics import FireTableLibrary
from ..battery import Peloton, Group, KNOWN_SHELLS, shell_label, normalise_shell
from ..geo import mgrs_to_utm
from .mgrs_field import MgrsLineEdit
from ..firemission import (
    Observer, FireMission, MethodOfFire, Sheaf, TargetType, Fuze,
    FireControl, TargetByGrid, TargetByPolar, TargetByShift,
    solve_mission, PieceSolution,
)


METHOD_LABELS = [
    ("AF — Adjust Fire", MethodOfFire.AF),
    ("FFE — Fire For Effect", MethodOfFire.FFE),
    ("FPF — Final Protective Fire", MethodOfFire.FPF),
]
SHEAF_LABELS = [
    ("Converged (point)", Sheaf.CONVERGED),
    ("Parallel (area)", Sheaf.PARALLEL),
    ("Linear (line)", Sheaf.LINEAR),
]
TGT_TYPE_LABELS = [
    ("Point", TargetType.POINT),
    ("Area", TargetType.AREA),
    ("Linear", TargetType.LINEAR),
]
FUZE_LABELS = [
    ("Quick (PD)", Fuze.QUICK),
    ("Delay", Fuze.DELAY),
    ("VT", Fuze.VT),
    ("Time", Fuze.TIME),
    ("Illum", Fuze.ILLUM),
]
CONTROL_LABELS = [
    ("When Ready", FireControl.WHEN_READY),
    ("At My Command", FireControl.AT_MY_COMMAND),
    ("TOT", FireControl.TOT),
]


def _fill(combo: QComboBox, labels: list[tuple[str, object]]) -> None:
    for label, val in labels:
        combo.addItem(label, val)


def _select_combo(combo: QComboBox, value) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            combo.setCurrentIndex(i)
            return


class CallForFireDialog(QDialog):
    """Modal CFF entry. Holds .result_fm and .result_solutions after accept()."""

    def __init__(
        self,
        peloton: Peloton,
        library: FireTableLibrary,
        group: Group,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.peloton = peloton
        self.library = library
        self.group = group
        self.result_fm: FireMission | None = None
        self.result_solutions: list[PieceSolution] | None = None

        self.setWindowTitle(f"New fire mission — section '{group.name}'")
        self.setModal(True)
        self.resize(820, 620)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        header = QLabel(
            f"<b>Section '{group.name}'</b>  ·  PDF {group.pdf_mils:.0f} mils  ·  "
            f"{len(group.member_names)} piece(s)"
        )
        header.setStyleSheet("font-size: 13px; padding: 4px;")
        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addLayout(self._build_left_column(), 1)
        body.addLayout(self._build_right_column(), 1)
        root.addLayout(body, 1)

        # Buttons
        btn_row = QDialogButtonBox()
        self.btn_cancel = btn_row.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.btn_compute = btn_row.addButton(
            "Compute firing data", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.btn_compute.setDefault(True)
        self.btn_compute.setStyleSheet(
            "font-weight: bold; padding: 8px 18px; font-size: 13px;"
        )
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_compute.clicked.connect(self._compute_and_accept)
        root.addWidget(btn_row)

        QShortcut(QKeySequence("Esc"), self, activated=self.reject)

    # ------------------------------------------------------------------ left
    def _build_left_column(self) -> QVBoxLayout:
        col = QVBoxLayout()

        fo_box = QGroupBox("1. Observer (FO)")
        fo_form = QFormLayout(fo_box)
        self.fo_combo = QComboBox()
        self.fo_combo.addItem("— manual entry —", None)
        for o in self.peloton.observers:
            self.fo_combo.addItem(o.call_sign, o.call_sign)
        self.fo_combo.currentIndexChanged.connect(self._on_fo_selected)
        self.fo_call = QLineEdit(); self.fo_call.setPlaceholderText("call sign, e.g. OP1")
        self.fo_mgrs = MgrsLineEdit()
        self.fo_mgrs.setMinimumWidth(220)
        self.fo_alt = QDoubleSpinBox(); self.fo_alt.setRange(-500, 9000); self.fo_alt.setSuffix(" m")
        fo_form.addRow("Saved FO", self.fo_combo)
        fo_form.addRow("Call sign", self.fo_call)
        fo_form.addRow("MGRS", self.fo_mgrs)
        fo_form.addRow("Altitude", self.fo_alt)
        col.addWidget(fo_box)
        # Preselect the first saved FO, if any, for convenience.
        if self.peloton.observers:
            self.fo_combo.setCurrentIndex(1)

        tgt_box = QGroupBox("2. Target — location")
        tgt_layout = QVBoxLayout(tgt_box)
        self.target_kind = QComboBox()
        self.target_kind.addItems(["Grid (MGRS)", "Polar from FO", "Shift from aiming point"])
        tgt_layout.addWidget(QLabel("Method"))
        tgt_layout.addWidget(self.target_kind)

        self.stack = QStackedWidget()

        # Grid
        g_w = QWidget(); g_f = QFormLayout(g_w)
        self.g_mgrs = MgrsLineEdit(); self.g_mgrs.setMinimumWidth(220)
        self.g_alt = QDoubleSpinBox(); self.g_alt.setRange(-500, 9000); self.g_alt.setSuffix(" m")
        g_f.addRow("MGRS", self.g_mgrs); g_f.addRow("Altitude", self.g_alt)
        self.stack.addWidget(g_w)

        # Polar
        p_w = QWidget(); p_f = QFormLayout(p_w)
        self.p_az = QDoubleSpinBox(); self.p_az.setRange(0, 6399); self.p_az.setDecimals(0); self.p_az.setSuffix(" mils")
        self.p_rng = QDoubleSpinBox(); self.p_rng.setRange(0, 20000); self.p_rng.setSuffix(" m")
        self.p_up = QDoubleSpinBox(); self.p_up.setRange(-2000, 2000); self.p_up.setSuffix(" m")
        p_f.addRow("Azimuth", self.p_az); p_f.addRow("Range", self.p_rng); p_f.addRow("Δaltitude", self.p_up)
        self.stack.addWidget(p_w)

        # Shift
        s_w = QWidget(); s_f = QFormLayout(s_w)
        self.s_ap = QComboBox()
        self.s_ap.addItems([a.name for a in self.peloton.aiming_points])
        self.s_r = QDoubleSpinBox(); self.s_r.setRange(-5000, 5000); self.s_r.setSuffix(" m")
        self.s_a = QDoubleSpinBox(); self.s_a.setRange(-5000, 5000); self.s_a.setSuffix(" m")
        self.s_u = QDoubleSpinBox(); self.s_u.setRange(-2000, 2000); self.s_u.setSuffix(" m")
        s_f.addRow("Aiming point", self.s_ap)
        s_f.addRow("Right (+ R)", self.s_r)
        s_f.addRow("Add (+ fwd)", self.s_a)
        s_f.addRow("Up", self.s_u)
        self.stack.addWidget(s_w)

        self.target_kind.currentIndexChanged.connect(self.stack.setCurrentIndex)
        tgt_layout.addWidget(self.stack)
        col.addWidget(tgt_box, 1)
        return col

    # ----------------------------------------------------------------- right
    def _build_right_column(self) -> QVBoxLayout:
        col = QVBoxLayout()

        desc_box = QGroupBox("3. Target — description")
        desc_form = QFormLayout(desc_box)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("e.g. troops in open, mortar position")
        self.tgt_type = QComboBox(); _fill(self.tgt_type, TGT_TYPE_LABELS)
        desc_form.addRow("Description", self.desc)
        desc_form.addRow("Target type", self.tgt_type)
        col.addWidget(desc_box)

        eng_box = QGroupBox("4. Method of Engagement")
        eng_form = QFormLayout(eng_box)
        self.shell = QComboBox()
        self.shell.setEditable(True)  # allow custom shells
        for s in KNOWN_SHELLS:
            self.shell.addItem(shell_label(s), s)
        # Also offer any custom shells the platoon already stocks.
        extras = {sh for d in self.peloton.ammo.values() for sh in d.keys()}
        for s in sorted(extras - set(KNOWN_SHELLS)):
            self.shell.addItem(s, s)
        self.fuze = QComboBox(); _fill(self.fuze, FUZE_LABELS)
        self.method = QComboBox(); _fill(self.method, METHOD_LABELS)
        self.sheaf = QComboBox(); _fill(self.sheaf, SHEAF_LABELS)
        self.rounds = QSpinBox(); self.rounds.setRange(1, 50); self.rounds.setValue(1); self.rounds.setSuffix(" rnd/piece")
        self.prefer = QComboBox(); self.prefer.addItems(["lowest", "highest"])
        eng_form.addRow("Munition", self.shell)
        self.stock_label = QLabel()
        self.stock_label.setStyleSheet("color: #888; font-size: 11px;")
        eng_form.addRow("", self.stock_label)
        eng_form.addRow("Fuze", self.fuze)
        eng_form.addRow("Method of fire", self.method)
        eng_form.addRow("Sheaf", self.sheaf)
        eng_form.addRow("Rounds", self.rounds)
        eng_form.addRow("Charge preference", self.prefer)

        def _on_method():
            m = self.method.currentData()
            if m == MethodOfFire.AF:
                self.rounds.setValue(1)
            elif m == MethodOfFire.FFE and self.rounds.value() == 1:
                self.rounds.setValue(3)

        self.method.currentIndexChanged.connect(_on_method)

        def _on_shell_changed():
            sh = self._current_shell()
            # Sensible fuze default per shell type
            if sh == "ILLUM":
                _select_combo(self.fuze, Fuze.ILLUM)
            elif sh == "SMOKE":
                _select_combo(self.fuze, Fuze.QUICK)
            elif sh == "HE" and self.fuze.currentData() == Fuze.ILLUM:
                _select_combo(self.fuze, Fuze.QUICK)
            self._update_stock_label()

        self.shell.currentIndexChanged.connect(_on_shell_changed)
        self.shell.editTextChanged.connect(lambda _: self._update_stock_label())
        self._update_stock_label()
        col.addWidget(eng_box)

        ctl_box = QGroupBox("5. Fire control")
        ctl_form = QFormLayout(ctl_box)
        self.control = QComboBox(); _fill(self.control, CONTROL_LABELS)
        ctl_form.addRow("Control", self.control)
        col.addWidget(ctl_box)
        col.addStretch(1)
        return col

    # ----------------------------------------------------------------- helpers
    def _current_shell(self) -> str:
        """Get the currently selected shell as a canonical upper-case string."""
        data = self.shell.currentData()
        if isinstance(data, str) and data:
            return normalise_shell(data)
        return normalise_shell(self.shell.currentText()) or "HE"

    def _update_stock_label(self) -> None:
        """Show the section's stock of the currently selected shell."""
        shell = self._current_shell()
        members = self.group.member_names
        if not members:
            self.stock_label.setText("")
            return
        per_piece = [(n, self.peloton.ammo_of(n, shell)) for n in members]
        total = sum(c for _, c in per_piece)
        breakdown = ", ".join(f"{n}:{c}" for n, c in per_piece)
        warn = total == 0
        color = "#e67e22" if warn else "#888"
        self.stock_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.stock_label.setText(
            f"Section stock of {shell}: {total} rnd ({breakdown})"
            + ("   ⚠ no stock!" if warn else "")
        )

    # ----------------------------------------------------------------- compute
    def _build_spec(self):
        idx = self.target_kind.currentIndex()
        if idx == 0:
            try:
                pos = mgrs_to_utm(self.g_mgrs.text().strip(), altitude_m=self.g_alt.value())
            except Exception as e:
                QMessageBox.warning(self, "Target MGRS", str(e)); return None
            return TargetByGrid(position=pos)
        if idx == 1:
            return TargetByPolar(
                azimuth_mils=self.p_az.value(),
                range_m=self.p_rng.value(),
                delta_height_m=self.p_up.value(),
            )
        if idx == 2:
            if not self.s_ap.count():
                QMessageBox.information(self, "Aiming point", "No aiming points available."); return None
            return TargetByShift(
                reference_name=self.s_ap.currentText(),
                right_m=self.s_r.value(),
                add_m=self.s_a.value(),
                delta_height_m=self.s_u.value(),
            )
        return None

    def _on_fo_selected(self, _idx: int) -> None:
        call = self.fo_combo.currentData()
        if call is None:
            return
        try:
            o = self.peloton.observer(call)
        except KeyError:
            return
        self.fo_call.setText(o.call_sign)
        self.fo_mgrs.setText(o.position.to_mgrs())
        self.fo_alt.setValue(o.position.altitude_m)

    def _compute_and_accept(self) -> None:
        try:
            obs = Observer(
                call_sign=self.fo_call.text().strip() or "FO",
                position=mgrs_to_utm(self.fo_mgrs.text().strip(), altitude_m=self.fo_alt.value()),
            )
        except Exception as e:
            QMessageBox.warning(self, "FO MGRS", str(e)); return
        spec = self._build_spec()
        if spec is None:
            return
        # Qt strips str-Enum subclasses to plain str in userData — wrap with the
        # enum constructor to recover typed values.
        fm = FireMission(
            id=self.peloton.allocate_fm_id(),
            group_name=self.group.name,
            observer=obs,
            target_spec=spec,
            target_description=self.desc.text().strip(),
            target_type=TargetType(self.tgt_type.currentData()),
            shell=self._current_shell(),
            fuze=Fuze(self.fuze.currentData()),
            method_of_fire=MethodOfFire(self.method.currentData()),
            sheaf=Sheaf(self.sheaf.currentData()),
            rounds_per_piece=self.rounds.value(),
            control=FireControl(self.control.currentData()),
        )
        try:
            sols = solve_mission(
                fm, self.peloton, self.library.resolve(fm.shell),
                prefer_charge=self.prefer.currentText(),
            )
        except Exception as e:
            QMessageBox.critical(self, "Computation failed", str(e))
            return
        self.result_fm = fm
        self.result_solutions = sols
        self.accept()
