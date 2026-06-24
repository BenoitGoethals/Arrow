"""Tab 'Fire Plan' — beheer van voorbereide doelen (incl. FPF) en quick-engage.

The CRUD for individual planned targets lives in PlannedTargetDialog (modal).
This panel hosts only:
  * H-hour reference setter
  * Big table of preplotted targets
  * Toolbar: Add… / Edit… / Remove / Reset / Engage controls
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QDoubleSpinBox,
    QPushButton, QGroupBox, QComboBox, QMessageBox, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QDateTimeEdit, QDialog,
)

from ..ballistics import FireTableLibrary
from ..battery import Peloton
from ..geo import mgrs_to_utm
from .mgrs_field import MgrsLineEdit
from .planned_target_dialog import PlannedTargetDialog
from ..firemission import (
    FireMission, MethodOfFire, Sheaf, TargetType, Fuze, FireControl,
    Observer, TargetByGrid, solve_mission,
)


class FirePlanPanel(QWidget):
    """Beheer fire plan + quick-engage door FM aan te maken."""

    def __init__(
        self,
        peloton: Peloton,
        library: FireTableLibrary,
        engage_callback: Callable[[FireMission, list], None],
        archive_callback: Callable[[str], object] | None = None,
    ) -> None:
        super().__init__()
        self.peloton = peloton
        self.library = library
        self.engage_callback = engage_callback
        self.archive_callback = archive_callback

        root = QVBoxLayout(self)
        root.addWidget(self._build_hhour_group())
        root.addWidget(self._build_table_group(), stretch=1)

        # Live refresh van schedule-status (countdown / ACTIVE / PAST)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._refresh_schedule_only)
        self._tick_timer.start(1000)

    # ============================================================ H-hour
    def _build_hhour_group(self) -> QGroupBox:
        box = QGroupBox("H-hour (reference time for all plan timings)")
        layout = QHBoxLayout(box)
        self.h_edit = QDateTimeEdit()
        self.h_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.h_edit.setCalendarPopup(True)
        self.h_edit.setDateTime(QDateTime.currentDateTime())
        b_set = QPushButton("Set H-hour")
        b_set.clicked.connect(self._set_h_hour)
        b_now = QPushButton("Now")
        b_now.clicked.connect(self._h_hour_now)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self._clear_h_hour)
        self.h_status = QLabel("H-hour: not set")
        self.h_status.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.h_edit)
        layout.addWidget(b_set); layout.addWidget(b_now); layout.addWidget(b_clear)
        layout.addStretch(1)
        layout.addWidget(self.h_status)
        return box

    def _set_h_hour(self) -> None:
        py = self.h_edit.dateTime().toPython()
        if py.tzinfo is None:
            py = py.astimezone()
        self.peloton.h_hour = py
        self.refresh()

    def _h_hour_now(self) -> None:
        now = datetime.now().astimezone()
        self.peloton.h_hour = now
        self.h_edit.setDateTime(QDateTime.currentDateTime())
        self.refresh()

    def _clear_h_hour(self) -> None:
        self.peloton.h_hour = None
        self.refresh()

    # =================================================== Table + toolbar
    def _build_table_group(self) -> QGroupBox:
        box = QGroupBox("Fire plan — preplotted targets")
        wrap = QVBoxLayout(box)

        # ---- top toolbar: CRUD actions (modal) ----
        top_btns = QHBoxLayout()
        b_add = QPushButton("Add target…")
        b_add.setStyleSheet("font-weight: bold;")
        b_add.clicked.connect(self._add_target)
        b_edit = QPushButton("Edit selected…")
        b_edit.clicked.connect(self._edit_selected)
        b_del = QPushButton("Remove selected")
        b_del.clicked.connect(self._delete_selected)
        b_reset = QPushButton("Reset fire plan")
        b_reset.clicked.connect(self._reset_plan)
        top_btns.addWidget(b_add)
        top_btns.addWidget(b_edit)
        top_btns.addWidget(b_del)
        top_btns.addStretch(1)
        top_btns.addWidget(b_reset)
        wrap.addLayout(top_btns)

        # ---- big preplotted-targets table ----
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels([
            "#", "Name", "MGRS", "Alt", "Description", "Type",
            "Munition/Fuze", "Sheaf/Rounds", "FPF",
            "Timing", "Scheduled", "Status",
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(
            lambda _r, _c: self._edit_selected()
        )
        wrap.addWidget(self.table, stretch=1)

        # ---- engage row (FO details + Engage button) ----
        engage_box = QGroupBox("Engage")
        engage_row = QHBoxLayout(engage_box)
        engage_row.addWidget(QLabel("Section:"))
        self.engage_group_combo = QComboBox()
        engage_row.addWidget(self.engage_group_combo)
        engage_row.addWidget(QLabel("FO:"))
        self.engage_fo_call = QLineEdit()
        self.engage_fo_call.setPlaceholderText("FO call sign")
        engage_row.addWidget(self.engage_fo_call)
        self.engage_fo_mgrs = MgrsLineEdit()
        self.engage_fo_mgrs.setPlaceholderText("FO MGRS")
        engage_row.addWidget(self.engage_fo_mgrs)
        self.engage_fo_alt = QDoubleSpinBox()
        self.engage_fo_alt.setRange(-500, 9000); self.engage_fo_alt.setSuffix(" m")
        engage_row.addWidget(self.engage_fo_alt)
        b_engage = QPushButton("Engage selected target")
        b_engage.setStyleSheet("font-weight: bold; padding: 4px 10px;")
        b_engage.clicked.connect(self._engage_selected)
        engage_row.addWidget(b_engage)
        wrap.addWidget(engage_box)

        return box

    # ============================================================ CRUD
    def _selected_row(self) -> int:
        return self.table.currentRow()

    def _add_target(self) -> None:
        dlg = PlannedTargetDialog(self.peloton, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_target is None:
            return
        self.peloton.fire_plan.append(dlg.result_target)
        self.refresh()

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if row < 0 or row >= len(self.peloton.fire_plan):
            QMessageBox.information(
                self, "Selection", "Select a target first."
            )
            return
        target = self.peloton.fire_plan[row]
        dlg = PlannedTargetDialog(self.peloton, target=target, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_target is None:
            return
        # Replace in-place so the row position stays stable.
        self.peloton.fire_plan[row] = dlg.result_target
        # Default the engage section combo to the suggested group
        if dlg.result_target.suggested_group:
            i = self.engage_group_combo.findText(dlg.result_target.suggested_group)
            if i >= 0:
                self.engage_group_combo.setCurrentIndex(i)
        self.refresh()

    def _delete_selected(self) -> None:
        row = self._selected_row()
        if row < 0 or row >= len(self.peloton.fire_plan):
            return
        target = self.peloton.fire_plan[row]
        if QMessageBox.question(
            self, "Remove target",
            f"Remove planned target '{target.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        del self.peloton.fire_plan[row]
        self.refresh()

    def _reset_plan(self) -> None:
        if not self.peloton.fire_plan and self.peloton.h_hour is None:
            return
        if QMessageBox.question(
            self, "Reset fire plan",
            "Archive current state and remove all planned targets + H-hour?\n"
            "Snapshot saved under Archives → Browse archives.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.archive_callback is not None:
            try: self.archive_callback("before_reset_plan")
            except Exception: pass
        self.peloton.fire_plan.clear()
        self.peloton.h_hour = None
        self.refresh()

    # =========================================================== Engage
    def _engage_selected(self) -> None:
        row = self._selected_row()
        if row < 0 or row >= len(self.peloton.fire_plan):
            QMessageBox.information(self, "Selection", "Select a target first.")
            return
        if self.engage_group_combo.count() == 0:
            QMessageBox.information(self, "Section", "No sections available.")
            return
        group_name = self.engage_group_combo.currentText()
        t = self.peloton.fire_plan[row]
        try:
            fo_pos = mgrs_to_utm(self.engage_fo_mgrs.text().strip(),
                                 altitude_m=self.engage_fo_alt.value())
        except Exception as e:
            QMessageBox.warning(self, "FO MGRS",
                                f"Enter a valid FO position.\n{e}")
            return
        fm = FireMission(
            id=self.peloton.allocate_fm_id(),
            group_name=group_name,
            observer=Observer(
                call_sign=self.engage_fo_call.text().strip() or "FO",
                position=fo_pos,
            ),
            target_spec=TargetByGrid(position=t.position),
            target_description=f"{t.name} {t.description}".strip(),
            target_type=_enum_or_default(TargetType, t.target_type, TargetType.POINT),
            shell=t.shell,
            fuze=_enum_or_default(Fuze, t.fuze, Fuze.QUICK),
            method_of_fire=MethodOfFire.FFE if not t.is_fpf else MethodOfFire.FPF,
            sheaf=_enum_or_default(Sheaf, t.sheaf, Sheaf.CONVERGED),
            rounds_per_piece=t.rounds_per_piece,
            control=FireControl.WHEN_READY,
            line_azimuth_mils=t.line_azimuth_mils,
            line_length_m=t.line_length_m,
        )
        try:
            sols = solve_mission(fm, self.peloton, self.library.resolve(fm.shell))
        except Exception as e:
            QMessageBox.critical(self, "Computation failed", str(e))
            return
        fm.note(f"Engaged from fire plan: {t.name}")
        self.engage_callback(fm, sols)
        QMessageBox.information(
            self, "Engaged",
            f"FM created for {t.name} on section {group_name}.\n"
            "See 'Fire Missions' tab.",
        )

    # =========================================================== Refresh
    def refresh(self) -> None:
        # Sync h_edit with peloton.h_hour
        if self.peloton.h_hour is not None:
            qdt = QDateTime.fromString(
                self.peloton.h_hour.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                "yyyy-MM-dd HH:mm:ss",
            )
            if qdt.isValid():
                self.h_edit.setDateTime(qdt)
        # Sync engage section combo
        prev = self.engage_group_combo.currentText()
        self.engage_group_combo.clear()
        self.engage_group_combo.addItems([g.name for g in self.peloton.groups])
        if prev:
            i = self.engage_group_combo.findText(prev)
            if i >= 0:
                self.engage_group_combo.setCurrentIndex(i)
        # H-hour status label
        if self.peloton.h_hour is not None:
            local = self.peloton.h_hour.astimezone()
            self.h_status.setText(
                f"H-hour: {local.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.h_status.setStyleSheet("font-weight: bold; color: #2ecc71;")
        else:
            self.h_status.setText("H-hour: not set")
            self.h_status.setStyleSheet("font-weight: bold; color: #aaa;")

        # Chronological sort: timed entries first, on-call last
        def _sort_key(t):
            return (0, t.start_offset_min) if t.start_offset_min is not None else (1, 0)
        ordered = sorted(self.peloton.fire_plan, key=_sort_key)
        # Keep the underlying list in the same order so row-index lookups stay valid
        self.peloton.fire_plan[:] = ordered

        prev_row = self.table.currentRow()
        self.table.setRowCount(len(ordered))
        now_aware = datetime.now().astimezone()
        for i, t in enumerate(ordered):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            name_item = QTableWidgetItem(t.name)
            if t.is_fpf:
                name_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(i, 1, name_item)
            self.table.setItem(i, 2, QTableWidgetItem(t.position.to_mgrs()))
            self.table.setItem(i, 3, QTableWidgetItem(f"{t.position.altitude_m:.0f}"))
            self.table.setItem(i, 4, QTableWidgetItem(t.description))
            self.table.setItem(i, 5, QTableWidgetItem(t.target_type))
            self.table.setItem(i, 6, QTableWidgetItem(f"{t.shell} / {t.fuze}"))
            extra = ""
            if t.sheaf == "linear":
                extra = f" · az{t.line_azimuth_mils:.0f}/{t.line_length_m:.0f}m"
            self.table.setItem(
                i, 7,
                QTableWidgetItem(f"{t.sheaf} · {t.rounds_per_piece}rnd{extra}"),
            )
            self.table.setItem(i, 8, QTableWidgetItem("FPF" if t.is_fpf else ""))

            timing_label = t.offset_label()
            if t.duration_min > 0:
                timing_label += f" ({t.duration_min}m)"
            self.table.setItem(i, 9, QTableWidgetItem(timing_label))

            sched = t.scheduled_start(self.peloton.h_hour)
            sched_str = sched.astimezone().strftime("%H:%M:%S") if sched else "—"
            self.table.setItem(i, 10, QTableWidgetItem(sched_str))

            status_str, color = self._status_text(t, now_aware)
            status_item = QTableWidgetItem(status_str)
            if color is not None:
                status_item.setForeground(color)
            self.table.setItem(i, 11, status_item)
        # Restore selection if possible
        if 0 <= prev_row < self.table.rowCount():
            self.table.selectRow(prev_row)

    def _refresh_schedule_only(self) -> None:
        """Light refresh every second: only timing-status columns."""
        if self.peloton.h_hour is None and not self.peloton.fire_plan:
            return
        now_aware = datetime.now().astimezone()
        for i, t in enumerate(self.peloton.fire_plan):
            if i >= self.table.rowCount():
                break
            text, color = self._status_text(t, now_aware)
            item = self.table.item(i, 11)
            if item is None:
                item = QTableWidgetItem(text)
                self.table.setItem(i, 11, item)
            else:
                item.setText(text)
            if color is not None:
                item.setForeground(color)

    def _status_text(self, t, now_aware):
        from PyQt6.QtGui import QColor
        if t.start_offset_min is None:
            return ("On Call", QColor("#888"))
        h = self.peloton.h_hour
        if h is None:
            return ("(H-hour ?)", QColor("#888"))
        sched = t.scheduled_start(h)
        diff = (sched - now_aware).total_seconds()
        st = t.status_at(now_aware, h)
        if st == "SCHEDULED":
            mins, secs = divmod(int(diff), 60)
            return (f"in {mins:02d}:{secs:02d}", QColor("#3498db"))
        if st == "DUE":
            return ("DUE — NOW", QColor("#f1c40f"))
        if st == "ACTIVE":
            end = t.scheduled_end(h)
            rem = (end - now_aware).total_seconds()
            mins, secs = divmod(int(max(0, rem)), 60)
            return (f"ACTIVE ({mins:02d}:{secs:02d} left)", QColor("#e74c3c"))
        return ("PAST", QColor("#666"))

    def showEvent(self, ev) -> None:  # type: ignore[override]
        self.refresh()
        super().showEvent(ev)


def _enum_or_default(enum_cls, value: str, default):
    try:
        return enum_cls(value)
    except ValueError:
        return default
