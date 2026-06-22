"""Backend HTTP façade and WebSocket monitor.

Both classes are safe to instantiate and call from any thread.
All GUI callbacks must be thread-safe (queue puts, not direct wx calls).
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from typing import Callable

import httpx


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


class BackendClient:
    """HTTP façade for Arrow backend endpoints (Façade pattern).

    Raises ``httpx.HTTPError`` / ``httpx.TransportError`` on network failure;
    callers should wrap in try/except and put an error message on the queue.
    """

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    def login(self, callsign: str, password: str) -> tuple[int, dict]:
        with httpx.Client(base_url=self._base, timeout=10.0) as cli:
            r = cli.post(
                "/auth/login", data={"username": callsign, "password": password}
            )
        try:
            body: dict = r.json()
        except Exception:
            body = {}
        return r.status_code, body

    def post_cot(self, xml: str, token: str) -> tuple[int, str]:
        with httpx.Client(base_url=self._base, timeout=10.0) as cli:
            r = cli.post(
                "/cot",
                content=xml.encode(),
                headers={
                    "Content-Type": "application/xml",
                    "Authorization": f"Bearer {token}",
                },
            )
        return r.status_code, r.text


class WsMonitor:
    """Asyncio WebSocket listener running in a daemon thread.

    Auto-reconnects with a 3-second back-off until ``stop()`` is called.

    Parameters
    ----------
    get_url:    callable returning the current backend HTTP URL (may change)
    get_token:  callable returning the current JWT token
    on_message: called with every raw JSON string received from the server
    on_status:  called with a status string: "CONNECTING" | "ON" | "OFF" | "ERR"
    """

    def __init__(
        self,
        get_url: Callable[[], str],
        get_token: Callable[[], str],
        on_message: Callable[[str], None],
        on_status: Callable[[str], None],
    ) -> None:
        self._get_url = get_url
        self._get_token = get_token
        self._on_msg = on_message
        self._on_status = on_status
        self._stop_ev = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_ev.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_ev.set()

    # ── internal ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        import websockets  # noqa: PLC0415

        url = self._get_url().replace("http://", "ws://").replace("https://", "wss://")
        uri = f"{url}/ws?token={self._get_token()}"

        self._on_status("CONNECTING")
        self._log(f"[{_ts()}] Connecting to {uri} …\n", "sys")

        while not self._stop_ev.is_set():
            try:
                async with websockets.connect(uri, ping_interval=20) as ws:
                    self._on_status("ON")
                    self._log(f"[{_ts()}] Connected.\n", "sys")
                    while not self._stop_ev.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            self._on_msg(raw)
                        except asyncio.TimeoutError:
                            continue
            except Exception as exc:
                if not self._stop_ev.is_set():
                    self._log(f"[{_ts()}] Error: {exc} — retry in 3s\n", "err")
                    self._on_status("ERR")
                    await asyncio.sleep(3)
            else:
                if not self._stop_ev.is_set():
                    self._log(f"[{_ts()}] Closed — retry in 3s\n", "sys")
                    await asyncio.sleep(3)

        self._on_status("OFF")
        self._log(f"[{_ts()}] Disconnected.\n", "sys")

    def _log(self, text: str, style: str) -> None:
        """Route an internal log line through on_message using a sentinel key."""
        self._on_msg(json.dumps({"__log__": True, "text": text, "style": style}))
