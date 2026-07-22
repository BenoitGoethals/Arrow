"""Arrow Front (Kivy) — logging configuration.

Same structure as front/utils/log_setup.py, targeting the "front_kivy"
logger namespace and a separate log file so the two front clients don't
interleave/rotate each other's logs when run side by side during the port.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_LOG_DIR = Path.home() / ".arrow" / "logs"
_LOG_FILE = _LOG_DIR / "arrow_front_kivy.log"

_FMT = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
    datefmt="%H:%M:%S",
)


def setup_logging() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    level_name = os.environ.get("ARROW_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(_FMT)

    ch = logging.StreamHandler()
    ch.setFormatter(_FMT)

    root = logging.getLogger("front_kivy")
    root.setLevel(level)
    root.propagate = False
    for h in (fh, ch):
        root.addHandler(h)

    for noisy in ("urllib3", "httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root.info(
        "Arrow Front (Kivy) logging started — level=%s  file=%s", level_name, _LOG_FILE
    )
