"""Archive browser: list timestamped snapshots and restore one."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QTextEdit, QSplitter,
)

from ..state import StateRepository


class ArchiveDialog(QDialog):
    """Pick an archived state file. The selected path is in `selected_path`."""

    def __init__(self, repo: StateRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Browse archived states")
        self.resize(720, 480)
        self.repo = repo
        self.selected_path: Path | None = None

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Archive folder: {repo.archive_dir}"))

        split = QSplitter(Qt.Orientation.Horizontal)
        self.listw = QListWidget()
        self.listw.itemSelectionChanged.connect(self._update_preview)
        split.addWidget(self.listw)

        self.preview = QTextEdit(); self.preview.setReadOnly(True)
        self.preview.setStyleSheet("font-family: monospace; font-size: 10pt;")
        split.addWidget(self.preview)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 2)
        root.addWidget(split, stretch=1)

        btns = QHBoxLayout()
        b_restore = QPushButton("Restore selected")
        b_restore.setStyleSheet("font-weight: bold;")
        b_restore.clicked.connect(self._restore)
        b_delete = QPushButton("Delete selected")
        b_delete.clicked.connect(self._delete_selected)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.reject)
        btns.addWidget(b_delete); btns.addStretch(1); btns.addWidget(b_restore); btns.addWidget(b_close)
        root.addLayout(btns)

        self._refresh_list()

    def _refresh_list(self) -> None:
        self.listw.clear()
        for path in self.repo.list_archives():
            ts = datetime.fromtimestamp(path.stat().st_mtime)
            label = f"{ts.strftime('%Y-%m-%d %H:%M:%S')}    {path.name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.listw.addItem(item)

    def _selected_path(self) -> Path | None:
        item = self.listw.currentItem()
        if item is None: return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _update_preview(self) -> None:
        p = self._selected_path()
        if p is None:
            self.preview.clear(); return
        try:
            data = json.loads(p.read_text())
        except Exception as e:
            self.preview.setPlainText(f"<read error: {e}>"); return
        pel = data.get("peloton", {})
        n_pieces = len(pel.get("pieces", []))
        n_groups = len(pel.get("groups", []))
        n_aps = len(pel.get("aiming_points", []))
        n_plan = len(pel.get("fire_plan", []))
        n_hist = len(data.get("missions", []))
        n_active = len(data.get("active_missions", []))
        h = pel.get("h_hour") or "—"
        next_fm = pel.get("next_fm_number", 1)
        self.preview.setPlainText(
            f"File:   {p}\n"
            f"Size:   {p.stat().st_size} bytes\n"
            f"Version: {data.get('version', '?')}\n\n"
            f"Pieces:           {n_pieces}\n"
            f"Sections:         {n_groups}\n"
            f"Aiming points:    {n_aps}\n"
            f"Fire plan items:  {n_plan}\n"
            f"H-hour:           {h}\n"
            f"Next FM number:   {next_fm}\n"
            f"Active missions:  {n_active}\n"
            f"Completed (hist): {n_hist}\n"
        )

    def _restore(self) -> None:
        p = self._selected_path()
        if p is None:
            QMessageBox.information(self, "Selection", "Pick a snapshot first."); return
        self.selected_path = p
        self.accept()

    def _delete_selected(self) -> None:
        p = self._selected_path()
        if p is None: return
        if QMessageBox.question(
            self, "Delete archive",
            f"Permanently delete {p.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            p.unlink()
        except Exception as e:
            QMessageBox.warning(self, "Delete failed", str(e)); return
        self._refresh_list()
