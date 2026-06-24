"""Main window: tabs + File menu + autosave / crash recovery."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QStatusBar,
    QFileDialog,
    QMessageBox,
    QDialog,
)

from ..ballistics import FireTableLibrary, FireTableRepository
from ..battery import Peloton
from ..persistence import save_state, load_state
from ..state import StateRepository
from .assets import app_icon
from .section_panel import SectionPanel
from .mission_panel import MissionPanel
from .history_panel import HistoryPanel
from .map_panel import MapPanel
from .fireplan_panel import FirePlanPanel
from .ammo_panel import AmmoPanel
from .firetable_panel import FireTablePanel
from .archive_dialog import ArchiveDialog


class MainWindow(QMainWindow):
    AUTOSAVE_INTERVAL_MS = 5000

    #: Emitted whenever the platoon / missions change so external observers
    #: (e.g. the Arrow Front COP map) can re-mirror pieces, FOs and targets.
    state_changed = pyqtSignal()
    #: Emitted from closeEvent so external observers can tear down their
    #: mirrored markers when the FDC window is closed.
    closing = pyqtSignal()

    def __init__(
        self,
        peloton: Peloton,
        library: FireTableLibrary,
        autosave: StateRepository | None = None,
        firetable_repo: FireTableRepository | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("MortarCalc — 81 mm FDC")
        self.setWindowIcon(app_icon())
        self.resize(1320, 820)

        self.peloton = peloton
        self.library = library
        self.firetable_repo = firetable_repo or FireTableRepository()
        self.autosave_repo = autosave or StateRepository()
        self.current_file: Path | None = None

        self.history_panel = HistoryPanel(
            archive_callback=self._archive_now,
            reengage_callback=self._reengage_from_history,
        )
        self.mission_panel = MissionPanel(
            peloton=peloton,
            library=library,
            on_changed=self._on_changed,
            on_eom=self._on_eom,
            archive_callback=self._archive_now,
        )
        self.section_panel = SectionPanel(
            peloton=peloton,
            on_changed=self._on_changed,
            archive_callback=self._archive_now,
            library=library,
        )
        self.fireplan_panel = FirePlanPanel(
            peloton=peloton,
            library=library,
            engage_callback=self._engage_from_fire_plan,
            archive_callback=self._archive_now,
        )
        self.map_panel = MapPanel(
            peloton=peloton,
            mission_panel=self.mission_panel,
            library=library,
        )
        self.ammo_panel = AmmoPanel(peloton=peloton, on_changed=self._on_changed)
        self.firetable_panel = FireTablePanel(
            library=library,
            repository=self.firetable_repo,
            on_changed=self._on_changed,
        )

        tabs = QTabWidget()
        tabs.addTab(self.section_panel, "Platoon && Lay")
        tabs.addTab(self.ammo_panel, "Ammunition")
        tabs.addTab(self.firetable_panel, "Firing Tables")
        tabs.addTab(self.fireplan_panel, "Fire Plan")
        tabs.addTab(self.mission_panel, "Fire Missions")
        tabs.addTab(self.history_panel, "History")
        tabs.addTab(self.map_panel, "Map")
        tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs = tabs
        self.setCentralWidget(tabs)

        self.setStatusBar(QStatusBar())
        self._build_menu()

        # Autosave timer: belt-and-suspenders save every N seconds even if
        # nothing triggers on_changed (covers timer-driven state in fireplan).
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave_now)
        self._autosave_timer.start(self.AUTOSAVE_INTERVAL_MS)

        self._update_status()

    # ---------- menu ----------
    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu("&File")
        a_new = QAction("New", self)
        a_new.setShortcut(QKeySequence.StandardKey.New)
        a_new.triggered.connect(self._file_new)
        a_open = QAction("Open…", self)
        a_open.setShortcut(QKeySequence.StandardKey.Open)
        a_open.triggered.connect(self._file_open)
        a_save = QAction("Save", self)
        a_save.setShortcut(QKeySequence.StandardKey.Save)
        a_save.triggered.connect(self._file_save)
        a_save_as = QAction("Save As…", self)
        a_save_as.setShortcut("Ctrl+Shift+S")
        a_save_as.triggered.connect(self._file_save_as)
        a_quit = QAction("Quit", self)
        a_quit.setShortcut(QKeySequence.StandardKey.Quit)
        a_quit.triggered.connect(self.close)
        for a in (a_new, a_open, a_save, a_save_as):
            m_file.addAction(a)

        m_archives = self.menuBar().addMenu("&Archives")
        a_archive = QAction("Archive current state…", self)
        a_archive.triggered.connect(self._archive_named)
        a_browse = QAction("Browse archives…", self)
        a_browse.triggered.connect(self._browse_archives)
        a_reset_all = QAction("Reset All (archive + clear)", self)
        a_reset_all.triggered.connect(self._reset_all)
        m_archives.addAction(a_archive)
        m_archives.addAction(a_browse)
        m_archives.addSeparator()
        m_archives.addAction(a_reset_all)

        m_sim = self.menuBar().addMenu("&Simulator")
        a_demo = QAction("Load demo scenario (3×2 mortars + FOs)…", self)
        a_demo.triggered.connect(self._load_demo)
        m_sim.addAction(a_demo)

        m_file.addSeparator()
        m_file.addAction(a_quit)

    # ---------- change hooks ----------
    def _on_changed(self) -> None:
        # mission_panel itself refreshes before calling on_changed; we don't re-refresh it
        # to avoid a callback loop. Just propagate to other panels and autosave.
        self.mission_panel.refresh()
        self.map_panel.refresh()
        if hasattr(self, "fireplan_panel"):
            self.fireplan_panel.refresh()
        if hasattr(self, "ammo_panel"):
            self.ammo_panel.refresh()
        self._autosave_now()
        self._update_status()
        self.state_changed.emit()

    def _on_eom(self, fm) -> None:
        self.history_panel.add(fm)
        self._autosave_now()

    def _on_tab_changed(self, idx: int) -> None:
        w = self.tabs.widget(idx)
        if hasattr(w, "refresh"):
            w.refresh()

    def _engage_from_fire_plan(self, fm, solutions) -> None:
        self.mission_panel.inject_mission(fm, solutions)
        self.tabs.setCurrentWidget(self.mission_panel)
        self._autosave_now()

    def _reengage_from_history(self, old_fm) -> None:
        """Create a fresh FM re-using target/observer/method from a completed one."""
        new_fm = self.mission_panel.reengage(old_fm)
        if new_fm is None:
            return
        self.tabs.setCurrentWidget(self.mission_panel)
        self._autosave_now()

    # ---------- status ----------
    def _update_status(self) -> None:
        f = f" — {self.current_file.name}" if self.current_file else ""
        last = self.autosave_repo.last_save
        autosave_str = f" (autosaved {last.strftime('%H:%M:%S')})" if last else ""
        n_tables = len(self.library)
        default = self.library.default_shell or "—"
        self.statusBar().showMessage(
            f"Platoon: {len(self.peloton.pieces)} pc(s), {len(self.peloton.groups)} section(s), "
            f"{len(self.peloton.aiming_points)} AP  ·  "
            f"firing tables: {n_tables} (default {default}){f}{autosave_str}"
        )

    # ---------- autosave ----------
    def _autosave_now(self) -> None:
        try:
            self.autosave_repo.save(
                self.peloton,
                self.history_panel.missions,
                self.mission_panel.active_missions(),
            )
        except Exception as e:
            self.statusBar().showMessage(f"Autosave failed: {e}", 5000)
            return
        self._update_status()

    # ---------- archives ----------
    def _archive_now(self, label: str = "snapshot") -> Path | None:
        """Save a timestamped snapshot. Used before destructive resets."""
        try:
            return self.autosave_repo.archive(
                self.peloton,
                self.history_panel.missions,
                self.mission_panel.active_missions(),
                label=label,
            )
        except Exception as e:
            QMessageBox.warning(self, "Archive failed", str(e))
            return None

    def _archive_named(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(
            self,
            "Archive label",
            "Label for this snapshot (timestamp appended automatically):",
            text="snapshot",
        )
        if not ok or not text.strip():
            return
        path = self._archive_now(label=text.strip())
        if path is not None:
            QMessageBox.information(self, "Archived", f"Saved to:\n{path}")

    def _browse_archives(self) -> None:
        dlg = ArchiveDialog(self.autosave_repo, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.selected_path is None:
            return
        # Archive the *current* state first so nothing is lost.
        self._archive_now(label="pre_restore")
        self._load_state_from(dlg.selected_path)

    def _load_demo(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Load demo scenario",
                "Archive the current state and load a demo platoon?\n\n"
                "3 sections × 2 mortars (each with a base gun and sector limits), "
                "DOS ammunition per tube, shared aiming points, and 2 FOs per section.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        from ..simulator import build_demo_peloton

        self._archive_now(label="before_demo")
        demo = build_demo_peloton()
        self.peloton.pieces[:] = demo.pieces
        self.peloton.groups[:] = demo.groups
        self.peloton.aiming_points[:] = demo.aiming_points
        self.peloton.observers[:] = demo.observers
        self.peloton.ammo = demo.ammo
        self.peloton.fire_plan = demo.fire_plan
        self.peloton.h_hour = demo.h_hour
        self.peloton.next_fm_number = demo.next_fm_number
        self.history_panel.clear()
        self.mission_panel.clear_active()
        self.current_file = None
        self._refresh_all()

    def _reset_all(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Reset All",
                "Archive the current state and clear everything?\n"
                "This wipes pieces, sections, aiming points, fire plan, active and completed missions.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._archive_now(label="before_reset_all")
        self.peloton.pieces.clear()
        self.peloton.groups.clear()
        self.peloton.aiming_points.clear()
        self.peloton.observers.clear()
        self.peloton.ammo.clear()
        self.peloton.fire_plan.clear()
        self.peloton.h_hour = None
        self.peloton.next_fm_number = 1
        self.history_panel.clear()
        self.mission_panel.clear_active()
        self.current_file = None
        self._refresh_all()

    # ---------- file actions ----------
    def _file_new(self) -> None:
        if (
            QMessageBox.question(
                self,
                "New file",
                "Archive current state and start fresh?\n"
                "(The current platoon, fire plan, and missions will be archived "
                "for later reuse via Archives → Browse archives.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._archive_now(label="before_new")
        self.peloton.pieces.clear()
        self.peloton.groups.clear()
        self.peloton.aiming_points.clear()
        self.peloton.observers.clear()
        self.peloton.ammo.clear()
        self.peloton.fire_plan.clear()
        self.peloton.h_hour = None
        self.peloton.next_fm_number = 1
        self.history_panel.clear()
        self.mission_panel.clear_active()
        self.current_file = None
        self._refresh_all()

    def _file_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open platoon state", "", "JSON (*.json)"
        )
        if not path:
            return
        self._load_state_from(Path(path))

    def _load_state_from(self, path: Path) -> None:
        try:
            pel, history, active = load_state(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        self.peloton.pieces[:] = pel.pieces
        self.peloton.groups[:] = pel.groups
        self.peloton.aiming_points[:] = pel.aiming_points
        self.peloton.observers[:] = pel.observers
        self.peloton.ammo = pel.ammo
        self.peloton.low_ammo_threshold = pel.low_ammo_threshold
        self.peloton.fire_plan = pel.fire_plan
        self.peloton.h_hour = pel.h_hour
        self.peloton.next_fm_number = pel.next_fm_number
        self.history_panel.set_history(history)
        self.mission_panel.restore_active(active)
        self.current_file = path
        self._refresh_all()

    def _file_save(self) -> None:
        if self.current_file is None:
            self._file_save_as()
            return
        self._write_to(self.current_file)

    def _file_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save platoon state", "platoon.json", "JSON (*.json)"
        )
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"
        self.current_file = Path(path)
        self._write_to(self.current_file)

    def _write_to(self, path: Path) -> None:
        try:
            save_state(
                path,
                self.peloton,
                self.history_panel.missions,
                self.mission_panel.active_missions(),
            )
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self._update_status()

    def _refresh_all(self) -> None:
        self.section_panel._refresh_all()
        self.mission_panel.refresh()
        self.history_panel.refresh()
        self.map_panel.refresh()
        self.fireplan_panel.refresh()
        self.ammo_panel.refresh()
        self.firetable_panel.refresh()
        self._update_status()
        self.state_changed.emit()

    # ---------- lifecycle ----------
    def closeEvent(self, event) -> None:  # noqa: N802
        # Let external observers (Front COP map) remove mirrored markers.
        self.closing.emit()
        super().closeEvent(event)
