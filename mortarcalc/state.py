"""StateRepository — persistent application state with crash recovery.

Single Responsibility: this class owns *where and when* the full application
state lives on disk. It does not know about Qt or GUI panels — callers
pass in the data they want saved.

Crash recovery: every save is atomic (`tmp` file + rename). If the process
dies mid-write, the previous good file is preserved. On startup the GUI
checks `default_autosave_path()` and offers to restore.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .battery import Peloton
from .firemission import FireMission
from .persistence import load_state, save_state


def default_autosave_path() -> Path:
    """Platform-appropriate location for the autosave file.

    macOS:   ~/Library/Application Support/MortarCalc/autosave.json
    Linux:   $XDG_DATA_HOME/MortarCalc/autosave.json  (fallback ~/.local/share)
    Windows: %APPDATA%/MortarCalc/autosave.json
    """
    import sys
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "MortarCalc" / "autosave.json"


class StateRepository:
    """Reads and writes the entire app state to a single JSON file.

    Supports timestamped archives in `archives/` subdir for snapshot/reset flows.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_autosave_path()
        self._last_save: datetime | None = None

    @property
    def last_save(self) -> datetime | None:
        return self._last_save

    @property
    def archive_dir(self) -> Path:
        return self.path.parent / "archives"

    def exists(self) -> bool:
        return self.path.is_file()

    def save(
        self,
        peloton: Peloton,
        history: list[FireMission],
        active: list[FireMission],
    ) -> None:
        save_state(self.path, peloton, history, active)
        self._last_save = datetime.now()

    def load(self) -> tuple[Peloton, list[FireMission], list[FireMission]]:
        return load_state(self.path)

    def delete(self) -> None:
        if self.path.is_file():
            self.path.unlink()

    # ---------- archives ----------
    def archive(
        self,
        peloton: Peloton,
        history: list[FireMission],
        active: list[FireMission],
        label: str = "snapshot",
    ) -> Path:
        """Save a timestamped snapshot to `archives/`. Returns the file path."""
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
        archive_path = self.archive_dir / f"{safe_label}_{ts}.json"
        save_state(archive_path, peloton, history, active)
        return archive_path

    def list_archives(self) -> list[Path]:
        """All snapshot files in archives/, newest first."""
        if not self.archive_dir.is_dir():
            return []
        return sorted(self.archive_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    def load_archive(self, path: Path) -> tuple[Peloton, list[FireMission], list[FireMission]]:
        return load_state(path)
