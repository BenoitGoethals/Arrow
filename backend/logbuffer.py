"""In-memory ring buffer of log records for the admin Logs viewer.

A single ``RingBufferHandler`` is attached to the root logger so it captures
*every* record from every source in the backend process (backend domain
loggers, the CoT TCP server, uvicorn, etc.) at whatever level the logger emits.
The web (Flask) process ships its own records here over HTTP via :func:`ingest`.

Records are tagged with a coarse **category** so the admin UI can separate:
  • ``connections`` — ATAK TCP + WebSocket connect/disconnect/presence
  • ``cot``         — Cursor-on-Target encode/decode/relay
  • ``web``         — the Flask dashboard process
  • ``backend``     — everything else (API, auth, db, services)

A logger may set an explicit category with ``logger.info(msg, extra={"cat": "connections"})``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

_MAX = 5000
_LOCK = threading.Lock()
_BUF: deque[dict] = deque(maxlen=_MAX)
_SEQ = 0

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def category_for(logger_name: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    n = logger_name or ""
    if n.startswith("backend.cot"):
        return "cot"
    if n.startswith("backend.websocket"):
        return "connections"
    if n.startswith("web"):
        return "web"
    return "backend"


def _append(rec: dict) -> None:
    global _SEQ
    with _LOCK:
        _SEQ += 1
        rec["id"] = _SEQ
        _BUF.append(rec)


class RingBufferHandler(logging.Handler):
    """Capture every log record into the shared ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(getattr(record, "msg", ""))
        if record.exc_info:
            try:
                msg += "\n" + self.formatException(record.exc_info)
            except Exception:
                pass
        ts = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
              + f".{int(record.msecs):03d}")
        _append({
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "category": category_for(record.name, getattr(record, "cat", None)),
            "message": msg,
        })


def install(level: int = logging.DEBUG) -> RingBufferHandler:
    """Attach the ring-buffer handler to the root logger (idempotent)."""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, RingBufferHandler):
            return h
    handler = RingBufferHandler()
    handler.setLevel(level)
    root.addHandler(handler)
    return handler


def ingest(records: list[dict]) -> int:
    """Add externally-shipped records (e.g. from the Flask web process)."""
    n = 0
    for r in records or []:
        if not isinstance(r, dict):
            continue
        _append({
            "ts":       str(r.get("ts", "")),
            "level":    str(r.get("level", "INFO")).upper(),
            "logger":   str(r.get("logger", "web")),
            "category": str(r.get("category", "web")),
            "message":  str(r.get("message", "")),
        })
        n += 1
    return n


def query(category: str | None = None, level: str | None = None,
          q: str | None = None, since: int = 0, limit: int = 500) -> dict:
    """Filtered slice of the buffer. ``since`` is the last seen record id."""
    minlvl = _LEVELS.get((level or "").upper(), 0)
    ql = (q or "").lower()
    with _LOCK:
        items = list(_BUF)
        last_id = _SEQ
    out: list[dict] = []
    for r in items:
        if r["id"] <= since:
            continue
        if category and category != "all" and r["category"] != category:
            continue
        if minlvl and _LEVELS.get(r["level"], 0) < minlvl:
            continue
        if ql and ql not in r["message"].lower() and ql not in r["logger"].lower():
            continue
        out.append(r)
    return {"logs": out[-limit:], "last_id": last_id}


def categories() -> dict:
    """Per-category counts for the admin UI badges."""
    counts: dict[str, int] = {}
    with _LOCK:
        for r in _BUF:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
    return counts
