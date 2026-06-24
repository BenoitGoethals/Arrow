"""Bundled GUI assets (icon, map, Leaflet)."""
from __future__ import annotations

from importlib.resources import files

from PyQt6.QtGui import QIcon


def app_icon() -> QIcon:
    """Application/window icon, loaded from the bundled SVG."""
    path = files("mortarcalc.gui.assets").joinpath("icon.svg")
    return QIcon(str(path))
