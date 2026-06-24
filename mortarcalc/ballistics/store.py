"""FireTableRepository — bewaart de vuurtafel-bibliotheek op schijf.

De bibliotheek is *globaal* (weapon reference data), losgekoppeld van de
platoon-state: één keer uploaden, beschikbaar in elk platoon-bestand en elke
sessie. Layout in de app-data map:

    <appdata>/MortarCalc/firetables/
        manifest.json          # { "default": "HE", "entries": {"HE": "HE.json", ...} }
        HE.json                # ruwe FireTable-JSON (round-trip via firetable_to_dict)
        ILLUM.json
        ...

Schrijfacties zijn atomisch (tmp + rename) zodat een crash mid-write de vorige
goede staat niet beschadigt — zelfde patroon als StateRepository.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .firetable import FireTable, firetable_from_dict, firetable_to_dict
from .library import FireTableLibrary

MANIFEST_NAME = "manifest.json"


def default_firetables_dir() -> Path:
    """Platform-gepaste map voor de vuurtafel-bibliotheek (naast autosave)."""
    import sys

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "MortarCalc" / "firetables"


def _slug(shell: str) -> str:
    """Bestandsnaam-veilige variant van een munitienaam."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in shell).strip("_") or "table"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


class FireTableRepository:
    """Leest/schrijft de FireTableLibrary als JSON-bestanden in `dir`."""

    def __init__(self, directory: Path | None = None) -> None:
        self.dir = Path(directory) if directory else default_firetables_dir()

    @property
    def manifest_path(self) -> Path:
        return self.dir / MANIFEST_NAME

    def exists(self) -> bool:
        return self.manifest_path.is_file()

    # ---------- laden ----------
    def load(self) -> FireTableLibrary:
        """Laad de bibliotheek; lege bibliotheek als er nog niets bewaard is.

        Een enkele onleesbare/corrupte tafel wordt overgeslagen i.p.v. de hele
        bibliotheek te laten falen.
        """
        if not self.exists():
            return FireTableLibrary()
        manifest = json.loads(self.manifest_path.read_text())
        lib = FireTableLibrary()
        for shell, filename in manifest.get("entries", {}).items():
            try:
                data = json.loads((self.dir / filename).read_text())
                lib.tables[shell] = firetable_from_dict(data)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        default = manifest.get("default")
        lib.default_shell = default if default in lib.tables else next(iter(lib.tables), None)
        return lib

    # ---------- bewaren ----------
    def save(self, library: FireTableLibrary) -> None:
        """Schrijf elke tafel naar een eigen bestand + een manifest.

        Verweesde tafel-bestanden (van verwijderde koppelingen) worden opgeruimd.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        entries: dict[str, str] = {}
        for shell, table in library.tables.items():
            filename = f"{_slug(shell)}.json"
            _atomic_write(self.dir / filename, json.dumps(firetable_to_dict(table), indent=2))
            entries[shell] = filename
        manifest = {"default": library.default_shell, "entries": entries}
        _atomic_write(self.manifest_path, json.dumps(manifest, indent=2))
        keep = set(entries.values()) | {MANIFEST_NAME}
        for f in self.dir.glob("*.json"):
            if f.name not in keep:
                f.unlink()

    def import_file(self, path: Path) -> FireTable:
        """Valideer en lees een geüploade vuurtafel-JSON (zonder te bewaren)."""
        return firetable_from_dict(json.loads(Path(path).read_text()))
