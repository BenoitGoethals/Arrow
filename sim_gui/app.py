"""QApplication bootstrap."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

from sim_gui.main_window import MainWindow
from sim_gui.theme import STYLESHEET


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Arrow Scenario Simulator")
    app.setOrganizationName("Arrow")
    app.setStyleSheet(STYLESHEET)
    w = MainWindow()
    w.show()
    return app.exec()
