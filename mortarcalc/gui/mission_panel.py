"""Tab 'Fire Missions' — section overview + active mission control + ammo tracking.

CFF entry is delegated to the modal CallForFireDialog (see cff_dialog.py).
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox, QMessageBox,
    QLabel, QListWidget, QListWidgetItem, QSplitter, QTableWidget,
    QTableWidgetItem, QTextEdit, QFileDialog, QScrollArea, QGridLayout,
    QFormLayout, QDoubleSpinBox, QDialog, QFrame,
)

from ..ballistics import FireTableLibrary
from ..battery import Peloton, Group
from ..export import export_fm_to_pdf
from ..firemission import (
    FireMission, MissionState, MethodOfFire, TargetByGrid,
    Correction, apply_correction, solve_mission, PieceSolution,
    format_mto, format_all_fire_commands,
)
from .cff_dialog import CallForFireDialog


class MissionPanel(QWidget):
    def __init__(
        self,
        peloton: Peloton,
        library: FireTableLibrary,
        on_changed: Callable[[], None] | None = None,
        on_eom: Callable[[FireMission], None] | None = None,
        archive_callback: Callable[[str], object] | None = None,
    ) -> None:
        super().__init__()
        self.peloton = peloton
        self.library = library
        self.on_changed = on_changed
        self.on_eom = on_eom
        self.archive_callback = archive_callback
        self.active: dict[str, FireMission | None] = {}
        self.solutions: dict[str, list[PieceSolution]] = {}

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.groups_list = QListWidget()
        self.groups_list.itemSelectionChanged.connect(self._refresh_detail)
        splitter.addWidget(self.groups_list)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail = QWidget()
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_scroll.setWidget(self.detail)
        splitter.addWidget(self.detail_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([220, 900])
        root = QVBoxLayout(self)
        root.addWidget(splitter)

        bar = QHBoxLayout()
        b_new_fm = QPushButton("New fire mission")
        b_new_fm.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        b_new_fm.setToolTip("Select a STANDBY section and open the CFF form")
        b_new_fm.clicked.connect(self._start_new_fm)
        bar.addWidget(b_new_fm)
        bar.addStretch(1)
        b_abort = QPushButton("Reset all active missions")
        b_abort.clicked.connect(self._reset_all_active)
        bar.addWidget(b_abort)
        root.addLayout(bar)

    # ---------- public API ----------
    def _start_new_fm(self) -> None:
        """Select the first STANDBY section so the CFF form becomes visible."""
        # If the currently selected section is already STANDBY, nothing to do.
        sel = self.groups_list.currentItem()
        if sel is not None and self.active.get(sel.data(Qt.ItemDataRole.UserRole)) is None:
            return
        # Find the first STANDBY section and select it.
        for i in range(self.groups_list.count()):
            gname = self.groups_list.item(i).data(Qt.ItemDataRole.UserRole)
            if self.active.get(gname) is None:
                self.groups_list.setCurrentRow(i)
                return
        if not self.peloton.groups:
            QMessageBox.information(self, "New fire mission",
                "No sections defined. Create a section in 'Platoon & Lay' first.")
        else:
            QMessageBox.information(self, "New fire mission",
                "All sections have an active fire mission.\n"
                "End a mission first before starting a new one.")

    def clear_active(self) -> None:
        self.active.clear()
        self.solutions.clear()
        self.refresh()

    def _reset_all_active(self) -> None:
        actives = self.active_missions()
        if not actives:
            QMessageBox.information(self, "Active missions", "No active missions to reset.")
            return
        if QMessageBox.question(
            self, "Reset all active missions",
            f"Archive and abort {len(actives)} active mission(s)?\n"
            "Aborted missions are NOT moved to history; archive snapshot will preserve them.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.archive_callback is not None:
            try: self.archive_callback("before_reset_active_fms")
            except Exception: pass
        self.clear_active()
        if self.on_changed: self.on_changed()

    def restore_active(self, missions: list[FireMission]) -> None:
        """Restore active missions (e.g. after autosave reload). Re-solves each."""
        self.active.clear()
        self.solutions.clear()
        for fm in missions:
            try:
                sols = solve_mission(fm, self.peloton, self.library.resolve(fm.shell))
            except Exception:
                sols = []
            self.active[fm.group_name] = fm
            self.solutions[fm.group_name] = sols
        self.refresh()

    def active_missions(self) -> list[FireMission]:
        """Return all currently active fire missions (one per section, at most)."""
        return [m for m in self.active.values() if m is not None]

    def reengage(self, old_fm: FireMission) -> FireMission | None:
        """Build a new FireMission re-using the old one's CFF and inject as active."""
        group_name = old_fm.group_name
        try:
            self.peloton.group(group_name)
        except KeyError:
            QMessageBox.warning(
                self, "Section gone",
                f"Section '{group_name}' no longer exists. Create it first or "
                "re-assign the FM manually."
            )
            return None
        if self.active.get(group_name) is not None:
            QMessageBox.warning(
                self, "Section busy",
                f"Section '{group_name}' already has an active FM. "
                "End that mission first."
            )
            return None
        new_fm = FireMission(
            id=self.peloton.allocate_fm_id(),
            group_name=group_name,
            observer=old_fm.observer,
            target_spec=old_fm.target_spec if old_fm.target_position is None
                        else TargetByGrid(position=old_fm.target_position),
            target_description=old_fm.target_description,
            target_type=old_fm.target_type,
            shell=old_fm.shell,
            fuze=old_fm.fuze,
            method_of_fire=old_fm.method_of_fire,
            sheaf=old_fm.sheaf,
            rounds_per_piece=old_fm.rounds_per_piece,
            control=old_fm.control,
            line_azimuth_mils=old_fm.line_azimuth_mils,
            line_length_m=old_fm.line_length_m,
        )
        new_fm.note(f"Re-engagement of {old_fm.id}")
        try:
            sols = solve_mission(new_fm, self.peloton, self.library.resolve(new_fm.shell))
        except Exception as e:
            QMessageBox.critical(self, "Computation failed", str(e))
            return None
        self.active[group_name] = new_fm
        self.solutions[group_name] = sols
        self.refresh()
        if self.on_changed: self.on_changed()
        return new_fm

    def inject_mission(self, fm: FireMission, solutions: list[PieceSolution]) -> None:
        """Inject a pre-computed FM (e.g. from Fire Plan engage)."""
        if self.active.get(fm.group_name) is not None:
            QMessageBox.warning(
                self, "Section busy",
                f"Section '{fm.group_name}' already has an active FM. "
                "End that mission first, or choose another section."
            )
            return
        self.active[fm.group_name] = fm
        self.solutions[fm.group_name] = solutions
        self.refresh()

    def _check_low_ammo(self, shell: str) -> None:
        low = self.peloton.low_ammo_pieces(shell)
        if low:
            QMessageBox.warning(
                self, "Low ammunition",
                f"{shell}: pieces below threshold ({self.peloton.low_ammo_threshold}): "
                f"{', '.join(low)}",
            )

    def _export_pdf(self, fm: FireMission) -> None:
        sols = self.solutions.get(fm.group_name, [])
        path, _ = QFileDialog.getSaveFileName(
            self, "Save FM card as PDF", f"{fm.id}_{fm.group_name}.pdf", "PDF (*.pdf)"
        )
        if not path: return
        if not path.lower().endswith(".pdf"): path += ".pdf"
        try:
            export_fm_to_pdf(path, fm, sols, self.peloton)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e)); return
        QMessageBox.information(self, "Export", f"PDF saved:\n{path}")

    # ---------- refresh ----------
    def refresh(self) -> None:
        for g in self.peloton.groups:
            self.active.setdefault(g.name, None)
        for stale in list(self.active.keys()):
            if not any(g.name == stale for g in self.peloton.groups):
                self.active.pop(stale, None); self.solutions.pop(stale, None)

        prev = self.groups_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.groups_list.currentItem() else None
        self.groups_list.clear()
        for g in self.peloton.groups:
            fm = self.active.get(g.name)
            if fm:
                fired = fm.total_rounds_fired()
                planned = fm.rounds_per_piece * len(g.member_names)
                status = f"FM {fm.id}  ·  {fm.method_of_fire.value}  ·  {fired}/{planned} rnd"
            else:
                status = "STANDBY"
            text = f"{g.name}  ·  PDF {g.pdf_mils:.0f} mils  ·  {len(g.member_names)} pc(s)  ·  {status}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, g.name)
            self.groups_list.addItem(item)
        if prev:
            for i in range(self.groups_list.count()):
                if self.groups_list.item(i).data(Qt.ItemDataRole.UserRole) == prev:
                    self.groups_list.setCurrentRow(i); break
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        # Replace the whole detail widget every refresh — guarantees a clean
        # slate. The previous in-place clear missed nested layout items, which
        # caused stale widgets to overlap new ones.
        self.detail = QWidget()
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(16, 16, 16, 16)
        self.detail_scroll.setWidget(self.detail)

        sel = self.groups_list.currentItem()
        if sel is None:
            placeholder = QLabel("Select a section on the left.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #888; font-size: 13px; padding: 40px;")
            self.detail_layout.addWidget(placeholder)
            self.detail_layout.addStretch(1)
            return
        group_name = sel.data(Qt.ItemDataRole.UserRole)
        try:
            group = self.peloton.group(group_name)
        except KeyError:
            return
        fm = self.active.get(group.name)
        if fm is None:
            self._build_new_fm_view(group)
        else:
            self._build_active_fm_view(group, fm)

    # ============================================================
    #         NEW FM — STANDBY summary + big Start button
    # ============================================================
    def _build_new_fm_view(self, group: Group) -> None:
        # Centered max-width container so the layout doesn't sprawl on wide
        # windows. Outer row uses stretch on both sides; inner column has a
        # fixed max width.
        outer = QHBoxLayout()
        outer.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(12)
        outer.addLayout(col, 0)
        outer.addStretch(1)
        self.detail_layout.addLayout(outer)
        self.detail_layout.addStretch(1)

        body = QWidget()
        body.setMaximumWidth(560)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        col.addWidget(body)

        # Header — section name on the left, STANDBY badge on the right
        header_row = QHBoxLayout()
        header = QLabel(f"Section '{group.name}'")
        header.setStyleSheet("font-weight: bold; font-size: 17px;")
        badge = QLabel("STANDBY")
        badge.setStyleSheet(
            "font-weight: bold; padding: 4px 12px; color: white; "
            "background: #7f8c8d; border-radius: 3px;"
        )
        header_row.addWidget(header)
        header_row.addStretch(1)
        header_row.addWidget(badge)
        body_layout.addLayout(header_row)

        # Empty section: hint and exit
        if not group.member_names:
            empty = QLabel(
                "No pieces assigned to this section.\n\n"
                "Go to 'Platoon & Lay' → click the section to assign pieces."
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #888; padding: 32px; font-size: 13px;")
            body_layout.addWidget(empty)
            return

        # Section facts in a tidy card with a key/value grid
        from ..battery import KNOWN_SHELLS

        # Per-shell totals (only show shells where the section actually has stock)
        shell_totals: dict[str, int] = {}
        for shell in KNOWN_SHELLS:
            t = sum(self.peloton.ammo_of(n, shell) for n in group.member_names)
            if t > 0 or shell == "HE":
                shell_totals[shell] = t
        # custom shells with stock
        seen = set(shell_totals)
        for n in group.member_names:
            for shell, count in self.peloton.ammo.get(n, {}).items():
                if shell not in seen and count > 0:
                    shell_totals[shell] = shell_totals.get(shell, 0) + count
                    seen.add(shell)

        low_in_section = [n for n in group.member_names
                          if n in self.peloton.low_ammo_pieces("HE")]

        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            "QFrame { background: rgba(255,255,255,0.04); "
            "border: 1px solid rgba(255,255,255,0.10); border-radius: 6px; }"
        )
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(8)

        self._add_fact(grid, 0, "Primary Direction of Fire",
                       f"{group.pdf_mils:.0f} mils")
        self._add_fact(grid, 1, "Pieces",
                       f"{len(group.member_names)}  ·  "
                       f"{', '.join(group.member_names)}")
        ammo_val = "   ·   ".join(f"{s} {n}" for s, n in shell_totals.items())
        if low_in_section:
            ammo_val += f"\n⚠ {len(low_in_section)} piece(s) low on HE: " \
                        f"{', '.join(low_in_section)}"
        self._add_fact(grid, 2, "Ammunition", ammo_val,
                       warn=bool(low_in_section))
        grid.setColumnStretch(1, 1)
        body_layout.addWidget(card)

        # Big primary action
        b_start = QPushButton("▶  Start fire mission")
        b_start.setMinimumHeight(64)
        b_start.setCursor(Qt.CursorShape.PointingHandCursor)
        b_start.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 16px; padding: 12px; "
            "background: #27ae60; color: white; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #2ecc71; }"
            "QPushButton:pressed { background: #229954; }"
        )
        b_start.clicked.connect(lambda: self._open_cff_dialog(group))
        body_layout.addWidget(b_start)

        hint = QLabel(
            "Opens the Call-For-Fire dialog · computes firing data per piece · "
            "starts the mission timeline"
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        body_layout.addWidget(hint)

    # ------------------------------------------------------------------
    @staticmethod
    def _add_fact(grid: QGridLayout, row: int, key: str, value: str,
                  warn: bool = False) -> None:
        k = QLabel(key)
        k.setStyleSheet("color: #888; font-size: 11px;")
        k.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        v = QLabel(value)
        v.setWordWrap(True)
        color = "#e67e22" if warn else "inherit"
        v.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
        v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(k, row, 0)
        grid.addWidget(v, row, 1)

    def _open_cff_dialog(self, group: Group) -> None:
        dlg = CallForFireDialog(
            peloton=self.peloton,
            library=self.library,
            group=group,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.result_fm is None or dlg.result_solutions is None:
            return
        self.active[group.name] = dlg.result_fm
        self.solutions[group.name] = dlg.result_solutions
        self.refresh()
        if self.on_changed:
            self.on_changed()

    # ============================================================
    #         ACTIVE FM — header row + two-column body
    # ============================================================
    def _build_active_fm_view(self, group: Group, fm: FireMission) -> None:
        sols = self.solutions.get(group.name, [])

        # ---- full-width header: title left, phase badge right ----
        header_row = QHBoxLayout()
        header = QLabel(f"{fm.id}  ·  Section '{group.name}'  ·  PDF {group.pdf_mils:.0f} mils")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        phase = QLabel(self._phase_text(fm))
        phase.setStyleSheet(self._phase_style(fm))
        header_row.addWidget(header)
        header_row.addStretch(1)
        header_row.addWidget(phase)
        self.detail_layout.addLayout(header_row)

        # ---- brief + target info row ----
        info_row = QHBoxLayout()
        brief = QLabel(fm.call_for_fire_brief())
        brief.setStyleSheet("font-family: monospace; color: #aaa;")
        info = QLabel(f"Target: {fm.target_position}    Control: {fm.control.value}")
        info.setStyleSheet("color: #aaa;")
        info_row.addWidget(brief)
        info_row.addStretch(1)
        info_row.addWidget(info)
        self.detail_layout.addLayout(info_row)

        # ---- two-column body: left = data display, right = action controls ----
        two_col = QHBoxLayout()
        left_col = QVBoxLayout()
        right_col = QVBoxLayout()
        two_col.addLayout(left_col, 3)
        two_col.addSpacing(8)
        two_col.addLayout(right_col, 2)
        self.detail_layout.addLayout(two_col, 1)

        # LEFT — MTO + firing data table
        mto_box = QGroupBox("Message To Observer (read back to FO)")
        mto_layout = QVBoxLayout(mto_box)
        mto_text = QTextEdit(); mto_text.setReadOnly(True)
        mto_text.setStyleSheet("font-family: monospace; font-size: 10pt; background: #0a1828; color: #e0f0ff;")
        mto_text.setPlainText(format_mto(fm, sols))
        mto_text.setFixedHeight(110)
        mto_layout.addWidget(mto_text)
        left_col.addWidget(mto_box)

        sol_box = QGroupBox(f"Firing data  (planned {fm.rounds_per_piece} rnd/piece)")
        sol_layout = QVBoxLayout(sol_box)
        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels(
            ["Piece", "Charge", "Elev (mils)", "Az (mils)", "Defl vs PDF", "TOF (s)", "Fired", "Remaining"]
        )
        table.setRowCount(len(sols))
        for i, s in enumerate(sols):
            fired = fm.rounds_fired.get(s.piece, 0)
            remaining = fm.rounds_remaining(s.piece)
            table.setItem(i, 0, QTableWidgetItem(s.piece))
            table.setItem(i, 1, QTableWidgetItem(str(s.charge)))
            table.setItem(i, 2, QTableWidgetItem(f"{s.elevation_mils:.0f}"))
            table.setItem(i, 3, QTableWidgetItem(f"{s.azimuth_mils:.0f}"))
            table.setItem(i, 4, QTableWidgetItem(f"{s.deflection_mils:.0f}"))
            table.setItem(i, 5, QTableWidgetItem(f"{s.tof_s:.1f}"))
            table.setItem(i, 6, QTableWidgetItem(f"{fired}"))
            rem_item = QTableWidgetItem(f"{remaining}")
            if remaining < 0: rem_item.setForeground(Qt.GlobalColor.red)
            table.setItem(i, 7, rem_item)
        table.resizeColumnsToContents()
        sol_layout.addWidget(table)
        total = fm.total_rounds_fired()
        planned_total = fm.rounds_per_piece * len(group.member_names)
        sol_layout.addWidget(QLabel(f"Total: {total} / {planned_total} rounds fired"))
        left_col.addWidget(sol_box, stretch=1)

        # RIGHT — fire commands + phase buttons + fire + correction + EOM
        cmd_box = QGroupBox("Fire commands to guns")
        cmd_layout = QVBoxLayout(cmd_box)
        cmd_text = QTextEdit(); cmd_text.setReadOnly(True)
        cmd_text.setStyleSheet("font-family: monospace; font-size: 10pt; background: #0a1828; color: #e0f0ff;")
        cmd_text.setPlainText(format_all_fire_commands(fm, sols))
        cmd_layout.addWidget(cmd_text)
        right_col.addWidget(cmd_box, stretch=1)

        comms_box = QGroupBox("Comms with FO (per phase)")
        comms_grid = QGridLayout(comms_box)
        b_mto = QPushButton("Send MTO"); b_mto.setToolTip("Mark MTO sent to FO")
        b_ready = QPushButton("Guns ready"); b_ready.setToolTip("Guns laid, ready to fire")
        b_shot = QPushButton("Shot, over"); b_shot.setToolTip("Round in flight — notify FO")
        b_splash = QPushButton("Splash, over"); b_splash.setToolTip("~5 s before impact — notify FO")
        b_complete = QPushButton("Rounds complete"); b_complete.setToolTip("All FFE rounds out — notify FO")
        comms_grid.addWidget(b_mto, 0, 0)
        comms_grid.addWidget(b_ready, 0, 1)
        comms_grid.addWidget(b_shot, 1, 0)
        comms_grid.addWidget(b_splash, 1, 1)
        comms_grid.addWidget(b_complete, 2, 0, 1, 2)
        right_col.addWidget(comms_box)

        fire_box = QGroupBox("Fire")
        fire_row = QHBoxLayout(fire_box)
        b_one = QPushButton("Fire 1 round  (adjustment)")
        b_full = QPushButton("Fire For Effect  (remaining rounds)")
        b_full.setStyleSheet("font-weight: bold;")
        fire_row.addWidget(b_one); fire_row.addWidget(b_full)
        right_col.addWidget(fire_box)

        corr_box = QGroupBox("Correction from FO")
        c_form = QFormLayout(corr_box)
        c_right = QDoubleSpinBox(); c_right.setRange(-2000, 2000); c_right.setSuffix(" m")
        c_add = QDoubleSpinBox(); c_add.setRange(-2000, 2000); c_add.setSuffix(" m")
        c_up = QDoubleSpinBox(); c_up.setRange(-500, 500); c_up.setSuffix(" m")
        c_form.addRow("Right (− = Left)", c_right)
        c_form.addRow("Add (− = Drop)", c_add)
        c_form.addRow("Up", c_up)
        b_corr = QPushButton("Apply + recompute")
        c_form.addRow(b_corr)
        right_col.addWidget(corr_box)

        actions = QHBoxLayout()
        b_pdf = QPushButton("Export card → PDF")
        b_pdf.clicked.connect(lambda: self._export_pdf(fm))
        b_eom = QPushButton("End of Mission")
        b_eom.setStyleSheet(
            "font-weight: bold; color: white; background: #c0392b; "
            "padding: 6px 12px; border-radius: 3px;"
        )
        actions.addWidget(b_pdf); actions.addStretch(1); actions.addWidget(b_eom)
        right_col.addLayout(actions)

        # ---- full-width mission log ----
        log_box = QGroupBox("Mission log")
        log_layout = QVBoxLayout(log_box)
        log = QTextEdit(); log.setReadOnly(True); log.setPlainText("\n".join(fm.log))
        log.setMaximumHeight(130)
        log_layout.addWidget(log)
        self.detail_layout.addWidget(log_box)

        # ---- handlers ----
        def _mark(state: MissionState, log_msg: str):
            fm.state = state
            fm.note(log_msg)
            self.refresh()
            if self.on_changed: self.on_changed()

        b_mto.clicked.connect(lambda: _mark(MissionState.MTO_SENT, "MTO sent to FO"))
        b_ready.clicked.connect(lambda: _mark(MissionState.READY, "Guns laid, ready to fire"))
        b_shot.clicked.connect(lambda: _mark(MissionState.SHOT, "Shot, over — round in flight"))
        b_splash.clicked.connect(lambda: _mark(MissionState.SPLASH, "Splash, over — ~5 s to impact"))
        b_complete.clicked.connect(lambda: _mark(MissionState.ROUNDS_COMPLETE, "Rounds complete, over"))

        def _fire_one():
            fm.state = MissionState.ADJUSTING if fm.method_of_fire == MethodOfFire.AF else MissionState.IN_EFFECT
            fm.record_salvo(group.member_names, rounds=1)
            for name in group.member_names:
                self.peloton.consume_ammo(name, fm.shell, 1)
            self._check_low_ammo(fm.shell)
            self.refresh()
            if self.on_changed: self.on_changed()

        def _fire_full():
            fm.state = MissionState.IN_EFFECT
            for name in group.member_names:
                rem = fm.rounds_remaining(name)
                if rem > 0:
                    fm.rounds_fired[name] = fm.rounds_fired.get(name, 0) + rem
                    self.peloton.consume_ammo(name, fm.shell, rem)
            fm.note(f"Full FFE fired — total now {fm.total_rounds_fired()} rounds")
            self._check_low_ammo(fm.shell)
            self.refresh()
            if self.on_changed: self.on_changed()

        def _apply_correction():
            corr = Correction(right_m=c_right.value(), add_m=c_add.value(), up_m=c_up.value())
            apply_correction(fm, corr)
            fm.target_spec = TargetByGrid(position=fm.target_position)
            try:
                sols2 = solve_mission(fm, self.peloton, self.library.resolve(fm.shell))
            except Exception as e:
                QMessageBox.critical(self, "Computation failed", str(e)); return
            self.solutions[group.name] = sols2
            fm.state = MissionState.ADJUSTING
            self.refresh()
            if self.on_changed: self.on_changed()

        def _eom():
            fm.state = MissionState.END_OF_MISSION
            fm.note(f"End of Mission — total rounds fired: {fm.total_rounds_fired()}")
            fm.final_solutions = list(self.solutions.get(group.name, []))
            if self.on_eom is not None:
                self.on_eom(fm)
            self.active[group.name] = None
            self.solutions.pop(group.name, None)
            self.refresh()
            if self.on_changed: self.on_changed()

        b_one.clicked.connect(_fire_one)
        b_full.clicked.connect(_fire_full)
        b_corr.clicked.connect(_apply_correction)
        b_eom.clicked.connect(_eom)

    # ---------- phase indicator helpers ----------
    @staticmethod
    def _phase_text(fm: FireMission) -> str:
        labels = {
            MissionState.RECEIVED: "PHASE 1 · RECEIVED — CFF in, computing",
            MissionState.COMPUTED: "PHASE 2 · COMPUTED — send MTO next",
            MissionState.MTO_SENT: "PHASE 3 · MTO SENT — wait for guns ready",
            MissionState.READY: "PHASE 4 · READY — fire when ordered",
            MissionState.SHOT: "PHASE 5 · SHOT — round in flight",
            MissionState.SPLASH: "PHASE 6 · SPLASH — ~5 s to impact",
            MissionState.ADJUSTING: "PHASE 7 · ADJUSTING — awaiting FO correction",
            MissionState.IN_EFFECT: "PHASE 8 · FIRE FOR EFFECT — FFE in progress",
            MissionState.ROUNDS_COMPLETE: "PHASE 9 · ROUNDS COMPLETE — awaiting BDA / EOM",
            MissionState.END_OF_MISSION: "PHASE 10 · END OF MISSION",
        }
        return labels.get(fm.state, fm.state.value)

    @staticmethod
    def _phase_style(fm: FireMission) -> str:
        color = {
            MissionState.RECEIVED: "#3498db",
            MissionState.COMPUTED: "#3498db",
            MissionState.MTO_SENT: "#9b59b6",
            MissionState.READY: "#27ae60",
            MissionState.SHOT: "#f39c12",
            MissionState.SPLASH: "#e67e22",
            MissionState.ADJUSTING: "#f1c40f",
            MissionState.IN_EFFECT: "#e74c3c",
            MissionState.ROUNDS_COMPLETE: "#16a085",
            MissionState.END_OF_MISSION: "#7f8c8d",
        }.get(fm.state, "#7f8c8d")
        return (
            f"font-weight: bold; font-size: 12px; padding: 4px 10px; "
            f"color: white; background: {color}; border-radius: 3px;"
        )

    def showEvent(self, ev) -> None:  # type: ignore[override]
        self.refresh()
        super().showEvent(ev)
