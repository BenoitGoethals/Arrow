"""Application entry-point — wires up autosave + crash recovery."""
from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from .ballistics import load_firetable, FireTableRepository
from .battery import Peloton
from .gui.assets import app_icon
from .gui.main_window import MainWindow
from .gui.theme import apply_theme, QSS
from .persistence import load_state
from .state import StateRepository


# Bundled firing tables, linked to their ammunition nature. Used to seed a fresh
# library and to back-fill natures missing from an existing one.
_BUNDLED_FIRETABLES: list[tuple[str, str]] = [
    ("HE", "m821_81mm_he.json"),
    ("SMOKE", "m819_81mm_smoke.json"),
    ("ILLUM", "m853a1_81mm_illum.json"),
    ("WP", "m375_81mm_wp.json"),
]


def _build_library(repo: FireTableRepository):
    """Load the saved firing-table library; seed/back-fill the bundled tables."""
    library = repo.load()
    added = False
    for shell, filename in _BUNDLED_FIRETABLES:
        if library.get(shell) is not None:
            continue  # keep the user's own table for this nature
        path = files("mortarcalc.data.firetables").joinpath(filename)
        try:
            library.add(shell, load_firetable(str(path)))
            added = True
        except Exception:
            pass  # a missing/corrupt bundled file must not block startup
    if added:
        try:
            repo.save(library)
        except Exception:
            pass  # non-fatal: run with the in-memory seed
    return library


def _load_default_scenario() -> tuple[Peloton, list, list]:
    """The bundled Otterburn scenario as (peloton, history, active).

    Falls back to building it in-memory, then to an empty platoon, so a missing
    or corrupt bundle never blocks startup.
    """
    try:
        path = files("mortarcalc.data.scenarios").joinpath("otterburn.json")
        return load_state(Path(str(path)))
    except Exception:
        try:
            from .simulator import build_demo_peloton
            return build_demo_peloton(), [], []
        except Exception:
            return Peloton(), [], []


def build_window(prompt_restore: bool = False) -> MainWindow:
    """Build a fully-wired MortarCalc FDC window without running an event loop.

    Loads the firing-table library, restores the autosave (silently unless
    ``prompt_restore`` is set, in which case the user is asked), or falls back to
    the bundled Otterburn scenario. MortarCalc's own military stylesheet is applied
    to the window only — not the whole QApplication — so the window can be embedded
    in a host Qt app (e.g. Arrow Front) without re-theming the host.

    The caller is responsible for ``show()`` and for keeping a reference to the
    returned window so it is not garbage-collected.
    """
    firetable_repo = FireTableRepository()
    library = _build_library(firetable_repo)

    autosave = StateRepository()
    peloton = Peloton()
    history: list = []
    active: list = []
    restored = False

    if autosave.exists():
        do_restore = True
        if prompt_restore:
            ret = QMessageBox.question(
                None, "Restore previous session?",
                f"An autosave was found:\n{autosave.path}\n\n"
                "Restore the previous session (pieces, fire plan, active and "
                "completed fire missions)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            do_restore = ret == QMessageBox.StandardButton.Yes
        if do_restore:
            try:
                peloton, history, active = autosave.load()
                restored = True
            except Exception as e:
                if prompt_restore:
                    QMessageBox.warning(None, "Restore failed",
                                        f"Could not load autosave:\n{e}\n\nStarting fresh.")
                peloton, history, active = Peloton(), [], []

    # Fresh start (no autosave, or restore declined/failed): load the bundled
    # Otterburn training-area scenario so the app opens with data.
    if not restored and not peloton.pieces:
        peloton, history, active = _load_default_scenario()

    window = MainWindow(
        peloton=peloton, library=library,
        autosave=autosave, firetable_repo=firetable_repo,
    )
    window.setStyleSheet(QSS)
    window.history_panel.set_history(history)
    window.mission_panel.restore_active(active)
    return window


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MortarCalc")
    app.setOrganizationName("MortarCalc")
    app.setWindowIcon(app_icon())
    apply_theme(app)

    window = build_window(prompt_restore=True)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
