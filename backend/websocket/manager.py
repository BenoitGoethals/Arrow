from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("backend.websocket")
_CONN = {"cat": "connections"}


class ConnectionManager:
    """In-memory pub/sub for live tactical updates.

    Pluggable: swap with a Redis pubsub backend without touching callers.
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            n = len(self._connections)
        client = getattr(websocket, "client", None)
        log.info(
            "WS connect: %s  (total=%d)", getattr(client, "host", "?"), n, extra=_CONN
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            n = len(self._connections)
        log.info("WS disconnect  (total=%d)", n, extra=_CONN)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._connections)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)


broadcaster = ConnectionManager()
