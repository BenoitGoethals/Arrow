"""Tab 'History' — completed fire missions (End of Mission)."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTableWidget, QTableWidgetItem,
    QGroupBox, QLabel, QTextEdit, QAbstractItemView, QPushButton, QFileDialog,
    QMessageBox,
)

from ..export import export_fm_to_pdf
from ..firemission import FireMission


class HistoryPanel(QWidget):
    def __init__(
        self,
        archive_callback: Callable[[str], object] | None = None,
        reengage_callback: Callable[[FireMission], None] | None = None,
    ) -> None:
        super().__init__()
        self.missions: list[FireMission] = []
        self.archive_callback = archive_callback
        self.reengage_callback = reengage_callback

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Completed fire missions:"))
        top.addStretch(1)
        b_clear = QPushButton("Reset history"); b_clear.clicked.connect(self._reset_history)
        top.addWidget(b_clear)
        root.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["FM", "Section", "Time", "Target", "FO", "Description", "Method", "Sheaf", "Ammo"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._refresh_detail)
        split.addWidget(self.table)

        right = QWidget(); right_layout = QVBoxLayout(right)
        self.detail_header = QLabel("Select an FM on the left.")
        self.detail_header.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.detail_header)

        sol_box = QGroupBox("Final firing data")
        sol_layout = QVBoxLayout(sol_box)
        self.sol_table = QTableWidget(0, 7)
        self.sol_table.setHorizontalHeaderLabels(
            ["Piece", "Charge", "Elev (mils)", "Az (mils)", "Defl", "TOF (s)", "Fired"]
        )
        sol_layout.addWidget(self.sol_table)
        right_layout.addWidget(sol_box)

        log_box = QGroupBox("Mission log")
        log_layout = QVBoxLayout(log_box)
        self.log = QTextEdit(); self.log.setReadOnly(True)
        log_layout.addWidget(self.log)
        right_layout.addWidget(log_box, stretch=1)

        action_row = QHBoxLayout()
        b_reengage = QPushButton("Engage again")
        b_reengage.setStyleSheet("font-weight: bold;")
        b_reengage.setToolTip("Create a new fire mission re-using this target, FO and method")
        b_reengage.clicked.connect(self._reengage)
        b_pdf = QPushButton("Export card → PDF"); b_pdf.clicked.connect(self._export_pdf)
        action_row.addWidget(b_reengage); action_row.addStretch(1); action_row.addWidget(b_pdf)
        right_layout.addLayout(action_row)

        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        root.addWidget(split, stretch=1)

    # ---------- public ----------
    def add(self, fm: FireMission) -> None:
        self.missions.append(fm); self.refresh()

    def clear(self) -> None:
        self.missions.clear(); self.refresh()

    def _reset_history(self) -> None:
        if not self.missions:
            return
        if QMessageBox.question(
            self, "Reset history",
            "Archive current state and clear all completed missions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.archive_callback is not None:
            try: self.archive_callback("before_reset_history")
            except Exception: pass
        self.clear()

    def set_history(self, missions: list[FireMission]) -> None:
        self.missions = list(missions); self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(len(self.missions))
        for i, fm in enumerate(self.missions):
            tgt = fm.target_position.to_mgrs() if fm.target_position else "—"
            fired = fm.total_rounds_fired()
            self.table.setItem(i, 0, QTableWidgetItem(fm.id))
            self.table.setItem(i, 1, QTableWidgetItem(fm.group_name))
            self.table.setItem(i, 2, QTableWidgetItem(fm.received_at.strftime("%Y-%m-%d %H:%M:%S")))
            self.table.setItem(i, 3, QTableWidgetItem(tgt))
            self.table.setItem(i, 4, QTableWidgetItem(fm.observer.call_sign))
            self.table.setItem(i, 5, QTableWidgetItem(fm.target_description))
            self.table.setItem(i, 6, QTableWidgetItem(fm.method_of_fire.value))
            self.table.setItem(i, 7, QTableWidgetItem(fm.sheaf.value))
            self.table.setItem(i, 8, QTableWidgetItem(f"{fired} rnd ({fm.rounds_per_piece}/pc planned)"))
        self._refresh_detail()

    def _reengage(self) -> None:
        sel = self.table.currentRow()
        if sel < 0 or sel >= len(self.missions):
            QMessageBox.information(self, "Selection", "Select a completed FM first."); return
        if self.reengage_callback is None:
            QMessageBox.warning(self, "Not wired up", "Re-engage callback not set."); return
        try:
            self.reengage_callback(self.missions[sel])
        except Exception as e:
            QMessageBox.critical(self, "Re-engage failed", str(e)); return

    def _export_pdf(self) -> None:
        sel = self.table.currentRow()
        if sel < 0 or sel >= len(self.missions):
            QMessageBox.information(self, "Selection", "Select an FM first."); return
        fm = self.missions[sel]
        sols = fm.final_solutions or []
        path, _ = QFileDialog.getSaveFileName(
            self, "Save FM card as PDF", f"{fm.id}_{fm.group_name}.pdf", "PDF (*.pdf)"
        )
        if not path: return
        if not path.lower().endswith(".pdf"): path += ".pdf"
        try:
            export_fm_to_pdf(path, fm, sols)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e)); return
        QMessageBox.information(self, "Export", f"PDF saved:\n{path}")

    def _refresh_detail(self) -> None:
        sel = self.table.currentRow()
        if sel < 0 or sel >= len(self.missions):
            self.detail_header.setText("Select an FM on the left.")
            self.sol_table.setRowCount(0); self.log.clear(); return
        fm = self.missions[sel]
        self.detail_header.setText(f"{fm.id} — {fm.group_name} — {fm.call_for_fire_brief()}")
        sols = fm.final_solutions or []
        self.sol_table.setRowCount(len(sols))
        for i, s in enumerate(sols):
            self.sol_table.setItem(i, 0, QTableWidgetItem(s.piece))
            self.sol_table.setItem(i, 1, QTableWidgetItem(str(s.charge)))
            self.sol_table.setItem(i, 2, QTableWidgetItem(f"{s.elevation_mils:.0f}"))
            self.sol_table.setItem(i, 3, QTableWidgetItem(f"{s.azimuth_mils:.0f}"))
            self.sol_table.setItem(i, 4, QTableWidgetItem(f"{s.deflection_mils:.0f}"))
            self.sol_table.setItem(i, 5, QTableWidgetItem(f"{s.tof_s:.1f}"))
            self.sol_table.setItem(i, 6, QTableWidgetItem(f"{fm.rounds_fired.get(s.piece, 0)}"))
        self.log.setPlainText("\n".join(fm.log))
