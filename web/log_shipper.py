"""Ship the Flask web process's logs to the backend so the admin Logs viewer
shows web + backend + cot + connections in one place.

A buffering ``logging.Handler`` queues records and a daemon thread POSTs them in
batches to ``{backend_url}/admin/logs/ingest`` (category ``web``). HTTP-client
loggers are skipped to avoid a feedback loop (the POST itself logs).
"""

from __future__ import annotations

import logging
import queue
import threading
import time

import httpx

_SKIP_PREFIXES = ("httpx", "httpcore", "urllib3", "web.log_shipper")


class _ShipHandler(logging.Handler):
    def __init__(self, q: "queue.Queue[dict]") -> None:
        super().__init__()
        self._q = q

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_SKIP_PREFIXES):
            return
        try:
            msg = record.getMessage()
        except Exception:
            return
        ts = (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
              + f".{int(record.msecs):03d}")
        try:
            self._q.put_nowait({
                "ts": ts, "level": record.levelname,
                "logger": record.name, "category": "web", "message": msg,
            })
        except queue.Full:
            pass


def install(backend_url: str, token: str = "", level: int = logging.DEBUG) -> None:
    q: "queue.Queue[dict]" = queue.Queue(maxsize=5000)
    handler = _ShipHandler(q)
    handler.setLevel(level)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(level)

    url = backend_url.rstrip("/") + "/admin/logs/ingest"
    headers = {"X-Log-Token": token} if token else {}

    def _worker() -> None:
        while True:
            batch: list[dict] = []
            try:
                batch.append(q.get(timeout=2.0))
            except queue.Empty:
                continue
            while len(batch) < 200:
                try:
                    batch.append(q.get_nowait())
                except queue.Empty:
                    break
            try:
                httpx.post(url, json={"records": batch}, headers=headers, timeout=4.0)
            except Exception:
                pass  # backend down — drop this batch, keep running

    threading.Thread(target=_worker, name="web-log-shipper", daemon=True).start()
