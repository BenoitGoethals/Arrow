"""QThread workers — run the facade off the UI thread.

`ScenarioRunWorker` runs `ScenarioFacade.run(scenario_id, …)` and emits
progress + finished signals back to the main window. The `DynamicLogRelay`
exists separately so the dynamic scenario's runtime thread (which is plain
`threading.Thread`, not a QThread) can safely surface log lines via a Qt
signal too.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from sim_gui.facade import ScenarioFacade


class DynamicLogRelay(QObject):
    """Bridge plain-Python log calls onto a Qt signal — thread-safe via queued
    connections, which Qt does automatically across thread affinities."""

    line = pyqtSignal(str)

    def emit_line(self, msg: str) -> None:
        self.line.emit(msg)


class ScenarioRunWorker(QThread):
    progress = pyqtSignal(str, str)  # step, message
    finished_ok = pyqtSignal(object)  # RunResult
    failed = pyqtSignal(str)  # error message

    def __init__(self, facade: ScenarioFacade, scenario_id: str) -> None:
        super().__init__()
        self._facade = facade
        self._scenario_id = scenario_id

    def run(self) -> None:  # noqa: D401 (QThread override)
        try:
            result = self._facade.run(self._scenario_id, self._emit_progress)
            self.finished_ok.emit(result)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")

    def _emit_progress(self, step: str, message: str) -> None:
        self.progress.emit(step, message)
