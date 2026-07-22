"""Small JSON-file settings store — replaces QSettings("Arrow", "ArrowFront").

Kivy has no per-app OS-backed key/value store equivalent to QSettings; this
just persists a flat dict as JSON under ~/.arrow/front_kivy_settings.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PATH = Path.home() / ".arrow" / "front_kivy_settings.json"


def load() -> dict[str, Any]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(values: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    data = load()
    data.update(values)
    _PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
