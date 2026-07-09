from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("backend.websocket")
_CONN = {"cat": "connections"}

# Per-client send timeout. A slow or half-dead WebSocket is dropped rather than
# allowed to stall the broadcast to every other operator (head-of-line blocking).
_SEND_TIMEOUT = 5.0


class ConnectionManager:
    """In-memory pub/sub for live tactical updates.

    Pluggable: swap with a Redis pubsub backend without touching callers.
    """

    def __init__(self) -> None:
        # websocket → the operator's security clearance (0..4). A message is only
        # delivered to connections whose clearance >= the message's classification,
        # so a classified element never leaves the server to an uncleared client.
        self._connections: dict[WebSocket, int] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, clearance: int = 0) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[websocket] = int(clearance or 0)
            n = len(self._connections)
        client = getattr(websocket, "client", None)
        log.info(
            "WS connect: %s  (total=%d)", getattr(client, "host", "?"), n, extra=_CONN
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(websocket, None)
            n = len(self._connections)
        log.info("WS disconnect  (total=%d)", n, extra=_CONN)

    async def broadcast(self, message: dict[str, Any]) -> None:
        # Classification of this message (default 0 → delivered to everyone, so
        # presence/tracking/*-deleted and other system events always flow).
        required = 0
        data = message.get("data")
        if isinstance(data, dict):
            try:
                required = int(data.get("classification", 0) or 0)
            except (TypeError, ValueError):
                required = 0
        async with self._lock:
            targets = [
                ws
                for ws, clearance in self._connections.items()
                if clearance >= required
            ]
        if not targets:
            return
        # Send to every client concurrently with a per-client timeout so one slow
        # or unresponsive socket can't delay delivery to the others. A send that
        # errors or times out marks that client dead for cleanup.
        results = await asyncio.gather(
            *(self._send(ws, message) for ws in targets),
            return_exceptions=True,
        )
        dead = [ws for ws, ok in zip(targets, results) if ok is not True]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.pop(ws, None)

    async def _send(self, ws: WebSocket, message: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(ws.send_json(message), timeout=_SEND_TIMEOUT)
            return True
        except Exception:
            return False


broadcaster = ConnectionManager()
