"""Main window — modern dark layout with scenario cards, pipeline timeline,
log, and map preview."""

from __future__ import annotations

import logging
import threading
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from sim_gui.backend_client import BackendCredentials
from sim_gui.facade import ScenarioFacade
from sim_gui.map_preview import MapPreview
from sim_gui.pipeline_timeline import PipelineTimeline
from sim_gui.qt_workers import DynamicLogRelay, ScenarioRunWorker
from sim_gui.scenarios.base import ScenarioMeta
from sim_gui.settings_dialog import SettingsDialog
from sim_gui.theme import ACCENT, BG_PANEL, BORDER, SUCCESS, TEXT, TEXT_DIM, TEXT_MUTED

log = logging.getLogger("sim.ui")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Arrow Scenario Simulator")
        self.resize(1480, 880)

        self._facade: ScenarioFacade | None = None
        self._creds: BackendCredentials | None = None
        self._worker: ScenarioRunWorker | None = None
        self._dynamic_stop: threading.Event | None = None
        self._scenario_start: float | None = None
        self._scenario_total_label: QLabel | None = None
        self._log_relay = DynamicLogRelay()
        self._log_relay.line.connect(self._append_log)

        self._build_menu()
        self._build_central()
        self._populate_scenarios()
        self._refresh_buttons()

        # Wall-clock ticker for the footer's "running for…" label.
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(200)
        self._tick_timer.timeout.connect(self._tick_elapsed)
        self._tick_timer.start()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        bar = self.menuBar()
        assert bar is not None
        file_menu = bar.addMenu("&File")
        assert file_menu is not None

        a_settings = QAction("Backend &Settings…", self)
        a_settings.triggered.connect(self._open_settings)
        file_menu.addAction(a_settings)

        a_connect = QAction("&Connect", self)
        a_connect.triggered.connect(self._connect_backend)
        file_menu.addAction(a_connect)

        file_menu.addSeparator()
        a_quit = QAction("&Quit", self)
        a_quit.triggered.connect(self.close)
        file_menu.addAction(a_quit)

        sb = QStatusBar(self)
        self.setStatusBar(sb)
        sb.showMessage("disconnected")

    def _build_central(self) -> None:
        outer = QWidget()
        outer_l = QVBoxLayout(outer)
        outer_l.setContentsMargins(0, 0, 0, 0)
        outer_l.setSpacing(0)

        outer_l.addWidget(self._build_header())
        outer_l.addWidget(self._build_body(), 1)
        outer_l.addWidget(self._build_footer())

        self.setCentralWidget(outer)

    # -- header -----------------------------------------------------------
    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("HeaderBar")
        bar.setFixedHeight(60)
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 8, 20, 8)
        h.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel("Arrow Scenario Simulator")
        title.setObjectName("HeaderTitle")
        sub = QLabel("3 PARA / SOR scenario launcher")
        sub.setObjectName("HeaderSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        h.addLayout(title_col)
        h.addStretch(1)

        self._conn_pill = QLabel("● Disconnected")
        self._conn_pill.setObjectName("ConnectionPill")
        self._conn_pill.setProperty("state", "disconnected")
        h.addWidget(self._conn_pill)

        self._settings_btn = QPushButton("Backend…")
        self._settings_btn.clicked.connect(self._open_settings)
        h.addWidget(self._settings_btn)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("PrimaryButton")
        self._connect_btn.clicked.connect(self._connect_backend)
        h.addWidget(self._connect_btn)
        return bar

    # -- body -------------------------------------------------------------
    def _build_body(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        splitter.addWidget(self._build_scenarios_pane())
        splitter.addWidget(self._build_center_pane())
        splitter.addWidget(self._build_right_pane())

        splitter.setSizes([320, 540, 620])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        return splitter

    def _build_scenarios_pane(self) -> QWidget:
        pane = QFrame()
        pane.setObjectName("SidePanel")
        v = QVBoxLayout(pane)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr = QLabel("SCENARIOS")
        hdr.setObjectName("PanelHeader")
        v.addWidget(hdr)

        self._list = QListWidget()
        self._list.setSpacing(0)
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.currentRowChanged.connect(self._on_scenario_selected)
        v.addWidget(self._list, 1)
        return pane

    def _build_center_pane(self) -> QWidget:
        pane = QFrame()
        pane.setObjectName("CenterPanel")
        v = QVBoxLayout(pane)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr_row = QWidget()
        hdr_l = QHBoxLayout(hdr_row)
        hdr_l.setContentsMargins(14, 14, 14, 4)
        hdr_l.setSpacing(10)

        hdr = QLabel("PIPELINE")
        hdr.setObjectName("PanelHeader")
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr_l.addWidget(hdr)
        hdr_l.addStretch(1)
        self._pipeline_status = QLabel("Idle")
        self._pipeline_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        hdr_l.addWidget(self._pipeline_status)
        v.addWidget(hdr_row)

        self._timeline = PipelineTimeline()
        v.addWidget(self._timeline, 0)

        # Log
        log_hdr_row = QWidget()
        lh = QHBoxLayout(log_hdr_row)
        lh.setContentsMargins(14, 8, 14, 4)
        log_hdr = QLabel("LOG")
        log_hdr.setObjectName("PanelHeader")
        log_hdr.setContentsMargins(0, 0, 0, 0)
        lh.addWidget(log_hdr)
        lh.addStretch(1)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self._log.clear())
        lh.addWidget(clear_btn)
        v.addWidget(log_hdr_row)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        log_wrap = QWidget()
        lw = QVBoxLayout(log_wrap)
        lw.setContentsMargins(8, 0, 8, 8)
        lw.addWidget(self._log)
        v.addWidget(log_wrap, 1)
        return pane

    def _build_right_pane(self) -> QWidget:
        pane = QFrame()
        pane.setObjectName("RightPanel")
        v = QVBoxLayout(pane)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        hdr = QLabel("MAP PREVIEW")
        hdr.setObjectName("PanelHeader")
        v.addWidget(hdr)

        self._scenario_card = self._build_scenario_card()
        v.addWidget(self._scenario_card)

        self._map = MapPreview()
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(8, 0, 8, 8)
        wl.addWidget(self._map)
        v.addWidget(wrap, 1)
        return pane

    def _build_scenario_card(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {BG_PANEL};"
            f" border: 1px solid {BORDER}; border-radius: 8px; }}"
            f" QLabel {{ background: transparent; border: none; }}"
        )
        card.setContentsMargins(0, 0, 0, 0)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(4)

        self._sel_name = QLabel("—")
        nf = self._sel_name.font()
        nf.setBold(True)
        nf.setPointSize(nf.pointSize() + 2)
        self._sel_name.setFont(nf)
        self._sel_type = QLabel("Select a scenario")
        self._sel_type.setStyleSheet(f"color: {ACCENT}; font-size: 11px;")
        self._sel_real = QLabel("")
        self._sel_real.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._sel_real.setWordWrap(True)
        self._sel_summary = QLabel("")
        self._sel_summary.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self._sel_summary.setWordWrap(True)

        outer.addWidget(self._sel_name)
        outer.addWidget(self._sel_type)
        outer.addWidget(self._sel_real)
        outer.addSpacing(4)
        outer.addWidget(self._sel_summary)

        wrap = QWidget()
        wrap_l = QVBoxLayout(wrap)
        wrap_l.setContentsMargins(8, 0, 8, 8)
        wrap_l.addWidget(card)
        return wrap

    # -- footer -----------------------------------------------------------
    def _build_footer(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background-color: {BG_PANEL};"
            f" border-top: 1px solid {BORDER}; }}"
        )
        bar.setFixedHeight(56)
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 8, 20, 8)
        h.setSpacing(12)

        col = QVBoxLayout()
        col.setSpacing(0)
        self._running_label = QLabel("Ready")
        self._running_label.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
        col.addWidget(self._running_label)
        elapsed = QLabel("")
        elapsed.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        col.addWidget(elapsed)
        self._scenario_total_label = elapsed
        h.addLayout(col)
        h.addStretch(1)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setObjectName("DangerButton")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        h.addWidget(self._stop_btn)

        self._run_btn = QPushButton("Run scenario")
        self._run_btn.setObjectName("PrimaryButton")
        self._run_btn.clicked.connect(self._on_run_clicked)
        h.addWidget(self._run_btn)
        return bar

    # ── scenario list ────────────────────────────────────────────────────

    def _populate_scenarios(self) -> None:
        self._list.clear()
        for meta in ScenarioFacade.list_scenarios():
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, meta)
            text = (
                f"<div style='font-weight:600; font-size:13px; color:{TEXT};'>"
                f"{meta.name}</div>"
                f"<div style='color:{ACCENT}; font-size:11px; margin-top:1px;'>"
                f"{meta.mission_type}</div>"
                f"<div style='color:{TEXT_MUTED}; font-size:11px; margin-top:1px;'>"
                f"{meta.real_world}</div>"
            )
            # QListWidgetItem doesn't render HTML directly; use a label widget.
            label = QLabel(text)
            label.setStyleSheet("background: transparent;")
            label.setWordWrap(True)
            label.setContentsMargins(0, 0, 0, 0)
            self._list.addItem(item)
            # The item sizeHint must match the rendered label.
            label.adjustSize()
            item.setSizeHint(label.sizeHint())
            self._list.setItemWidget(item, label)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _current_meta(self) -> ScenarioMeta | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_scenario_selected(self, _row: int) -> None:
        meta = self._current_meta()
        if meta is None:
            return
        self._sel_name.setText(meta.name)
        self._sel_type.setText(meta.mission_type)
        self._sel_real.setText(meta.real_world)
        self._sel_summary.setText(meta.summary)
        self._map.centre_on(meta.aor_center[0], meta.aor_center[1], meta.map_zoom)
        self._timeline.reset()
        self._refresh_buttons()

    # ── buttons & connection ─────────────────────────────────────────────

    def _refresh_buttons(self) -> None:
        connected = self._facade is not None
        running = self._worker is not None and self._worker.isRunning()
        dynamic_active = self._dynamic_stop is not None
        self._run_btn.setEnabled(connected and not running and not dynamic_active)
        meta = self._current_meta()
        on_phased = meta is not None and self._scenario_has_runtime(meta.id)
        self._stop_btn.setEnabled(bool(dynamic_active or (running and on_phased)))
        self._connect_btn.setText("Reconnect" if connected else "Connect")
        if not connected:
            self._run_btn.setToolTip("Connect to a backend first")
        else:
            self._run_btn.setToolTip("")

    @staticmethod
    def _scenario_has_runtime(scenario_id: str) -> bool:
        from sim_gui.scenarios.catalog import BY_ID

        mod = BY_ID.get(scenario_id)
        return mod is not None and hasattr(mod, "start_runtime")

    def _set_connection_state(self, state: str, label: str) -> None:
        self._conn_pill.setProperty("state", state)
        # Force re-polish so dynamic property selectors re-apply.
        style = self._conn_pill.style()
        if style is not None:
            style.unpolish(self._conn_pill)
            style.polish(self._conn_pill)
        glyph = "●" if state == "connected" else "○"
        self._conn_pill.setText(f"{glyph} {label}")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._append_log("settings saved — press Connect")

    def _connect_backend(self) -> None:
        dlg = SettingsDialog(self)
        url, callsign, password = dlg.values()
        if not password:
            QMessageBox.warning(
                self,
                "No password",
                "Open Backend… and enter the ADMIN password first.",
            )
            return
        creds = BackendCredentials(
            base_url=url, admin_callsign=callsign, admin_password=password
        )
        try:
            facade = ScenarioFacade.connect(creds)
        except SystemExit as e:
            QMessageBox.critical(self, "Login failed", str(e))
            self._set_connection_state("error", "Login failed")
            return
        except Exception as e:
            QMessageBox.critical(self, "Connection failed", f"{type(e).__name__}: {e}")
            self._set_connection_state("error", "Connection failed")
            return
        self._creds = creds
        self._facade = facade
        sb = self.statusBar()
        if sb is not None:
            sb.showMessage(f"connected to {url} as {callsign}")
        self._set_connection_state("connected", f"{callsign} @ {self._host(url)}")
        self._append_log(f"connected to {url}")
        self._map.subscribe(url, facade.session.token)
        self._refresh_buttons()

    @staticmethod
    def _host(url: str) -> str:
        # Compact "http://host:port/prefix" → "host:port".
        from urllib.parse import urlsplit

        return urlsplit(url).netloc or url

    def _on_run_clicked(self) -> None:
        if self._facade is None:
            QMessageBox.warning(self, "Not connected", "Connect to a backend first.")
            return
        meta = self._current_meta()
        if meta is None:
            return
        self._map.clear_overlay()
        self._timeline.reset()
        self._scenario_start = time.monotonic()
        self._running_label.setText(f"Running: {meta.name}")
        self._pipeline_status.setText("starting…")
        self._pipeline_status.setStyleSheet(
            f"color: {ACCENT}; font-size: 11px; font-weight: 600;"
        )
        self._append_log(f"▶ running '{meta.name}'")
        self._worker = ScenarioRunWorker(self._facade, meta.id)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished_ok)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        self._refresh_buttons()

    def _on_stop_clicked(self) -> None:
        if self._facade is not None:
            self._facade.stop_runtime()
        self._dynamic_stop = None
        self._running_label.setText("Stopped")
        self._pipeline_status.setText("phase clock stopped")
        self._pipeline_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self._append_log("⏹ phase clock: stop requested")
        self._refresh_buttons()

    # ── worker callbacks ─────────────────────────────────────────────────

    def _on_progress(self, step: str, message: str) -> None:
        self._timeline.start_step(step, message)
        if step == "done":
            self._pipeline_status.setText("complete")
            self._pipeline_status.setStyleSheet(
                f"color: {SUCCESS}; font-size: 11px; font-weight: 600;"
            )
        else:
            self._pipeline_status.setText(f"{step} · {message}")
        self._append_log(f"[{step}] {message}")

    def _on_finished_ok(self, result) -> None:
        self._append_log(
            f"✓ DONE — mission_id={result.mission_id}, "
            f"hierarchy={result.hierarchy}, vehicles={result.vehicles}, "
            f"overlay={result.inject.overlay_objects} obj"
        )
        self._running_label.setText(f"Completed: {result.scenario_name}")
        if self._facade and self._facade.has_runtime():
            self._dynamic_stop = self._facade.start_runtime(self._log_relay.emit_line)
            self._running_label.setText(f"Phase clock active: {result.scenario_name}")
            self._pipeline_status.setText("phase clock running")
            self._pipeline_status.setStyleSheet(
                f"color: {ACCENT}; font-size: 11px; font-weight: 600;"
            )
            self._append_log("▶ phase clock: started")
        self._worker = None
        self._refresh_buttons()

    def _on_failed(self, msg: str) -> None:
        self._timeline.fail_current(msg)
        self._append_log(f"✗ FAILED: {msg}")
        self._pipeline_status.setText("failed")
        self._pipeline_status.setStyleSheet(
            "color: #ef4444; font-size: 11px; font-weight: 600;"
        )
        self._running_label.setText("Failed")
        QMessageBox.critical(self, "Scenario failed", msg)
        self._worker = None
        self._refresh_buttons()

    # ── log + clock ──────────────────────────────────────────────────────

    def _append_log(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log.appendPlainText(f"{stamp}  {line}")

    def _tick_elapsed(self) -> None:
        if self._scenario_total_label is None:
            return
        if self._scenario_start is None or (
            self._worker is None and self._dynamic_stop is None
        ):
            self._scenario_total_label.setText("")
            return
        dt = time.monotonic() - self._scenario_start
        mins, secs = divmod(int(dt), 60)
        self._scenario_total_label.setText(f"running for {mins:02d}:{secs:02d}")
