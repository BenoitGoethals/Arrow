"""Arrow Front — logging configuration.

Call setup_logging() once at startup (before QApplication is created).

Log file: ~/.arrow/logs/arrow_front.log  (rotating, 5 MB × 3 files)
Level   : INFO by default; set ARROW_LOG_LEVEL=DEBUG for verbose output.

In-app access: use get_recent_lines(n) to populate the log panel.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_LOG_DIR = Path.home() / ".arrow" / "logs"
_LOG_FILE = _LOG_DIR / "arrow_front.log"

_FMT = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
    datefmt="%H:%M:%S",
)


# In-memory ring-buffer so the log panel can read recent entries
class _RingHandler(logging.Handler):
    def __init__(self, maxlines: int = 2000):
        super().__init__()
        self._buf: list[str] = []
        self._max = maxlines

    def emit(self, record: logging.LogRecord):
        line = self.format(record)
        self._buf.append(line)
        if len(self._buf) > self._max:
            self._buf = self._buf[-self._max :]

    def lines(self, n: int = 200) -> list[str]:
        return self._buf[-n:]


_ring: _RingHandler | None = None


def setup_logging() -> None:
    global _ring

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    level_name = os.environ.get("ARROW_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # ── Rotating file ─────────────────────────────────────────────────────
    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(_FMT)

    # ── Console (stderr) ──────────────────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setFormatter(_FMT)

    # ── In-memory ring ─────────────────────────────────────────────────────
    _ring = _RingHandler(maxlines=2000)
    _ring.setFormatter(_FMT)

    # ── Root logger for "front.*" namespace ───────────────────────────────
    root = logging.getLogger("front")
    root.setLevel(level)
    root.propagate = False
    for h in (fh, ch, _ring):
        root.addHandler(h)

    # Silence noisy third-party loggers
    for noisy in ("urllib3", "httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root.info("Arrow Front logging started — level=%s  file=%s", level_name, _LOG_FILE)


def get_recent_lines(n: int = 200) -> list[str]:
    return _ring.lines(n) if _ring else []


def log_file_path() -> Path:
    return _LOG_FILE
