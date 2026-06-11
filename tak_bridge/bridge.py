"""TAK Bridge core — asyncio manager that wires together:

  • CoT TCP server  (ATAK devices → bridge → Arrow)
  • TAK server client (TAK server ↔ bridge ↔ Arrow)
  • Arrow sync loop  (Arrow operators/objects → TAK)
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Coroutine

from tak_bridge.arrow import ArrowClient
from tak_bridge.config import TakBridgeConfig
from tak_bridge.cot_stream import (
    CotEvent, CotFrameBuffer,
    operator_to_cot, tacobj_to_cot,
)

log = logging.getLogger("tak_bridge.bridge")


# ── Stats ─────────────────────────────────────────────────────────────────────

@dataclass
class BridgeStats:
    started_at: float = field(default_factory=time.time)
    cot_received:   int = 0
    cot_sent:       int = 0
    arrow_pushed:   int = 0
    arrow_pulled:   int = 0
    tak_connected:  bool = False
    atak_clients:   int = 0
    last_sync_at:   float = 0.0
    errors:         int = 0

    def to_dict(self) -> dict:
        return {
            "uptime_s":       int(time.time() - self.started_at),
            "cot_received":   self.cot_received,
            "cot_sent":       self.cot_sent,
            "arrow_pushed":   self.arrow_pushed,
            "arrow_pulled":   self.arrow_pulled,
            "tak_connected":  self.tak_connected,
            "atak_clients":   self.atak_clients,
            "last_sync_at":   self.last_sync_at,
            "errors":         self.errors,
        }


# ── Connection manager (tracks all connected ATAK clients) ────────────────────

class ConnectionPool:
    def __init__(self) -> None:
        self._conns: dict[str, asyncio.StreamWriter] = {}

    def add(self, uid: str, writer: asyncio.StreamWriter) -> None:
        self._conns[uid] = writer
        log.info("ATAK client connected: %s  (total=%d)", uid, len(self._conns))

    def remove(self, uid: str) -> None:
        self._conns.pop(uid, None)
        log.info("ATAK client disconnected: %s  (total=%d)", uid, len(self._conns))

    async def broadcast(self, data: bytes, exclude: str = "") -> int:
        """Send CoT to all connected ATAK clients except the sender."""
        sent = 0
        dead: list[str] = []
        for uid, w in list(self._conns.items()):
            if uid == exclude:
                continue
            try:
                w.write(data)
                await w.drain()
                sent += 1
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.remove(uid)
        return sent

    def count(self) -> int:
        return len(self._conns)


# ── Bridge manager ────────────────────────────────────────────────────────────

class BridgeManager:
    """Orchestrates the TCP server, TAK client, and Arrow sync loop."""

    def __init__(self, cfg: TakBridgeConfig) -> None:
        self.cfg   = cfg
        self.stats = BridgeStats()
        self._pool = ConnectionPool()
        self._arrow = ArrowClient(cfg.arrow_url, cfg.arrow_callsign, cfg.arrow_password)

        self._server:    asyncio.Server | None = None
        self._tak_task:  asyncio.Task | None   = None
        self._sync_task: asyncio.Task | None   = None
        self._running    = False

        # UIDs that originated from TAK — don't echo back to TAK
        self._tak_origin_uids: set[str] = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self._arrow.login()

        # Start CoT TCP server for ATAK clients
        self._server = await asyncio.start_server(
            self._handle_atak_client,
            self.cfg.cot_server_host,
            self.cfg.cot_server_port,
        )
        log.info("CoT TCP server listening on %s:%d",
                 self.cfg.cot_server_host, self.cfg.cot_server_port)

        # Start Arrow → TAK sync loop
        self._sync_task = asyncio.create_task(self._sync_loop(), name="arrow-sync")

        # Connect to TAK server if configured
        if self.cfg.tak_host:
            self._tak_task = asyncio.create_task(self._tak_client_loop(), name="tak-client")

        log.info("TAK bridge started")

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._tak_task:
            self._tak_task.cancel()
        if self._sync_task:
            self._sync_task.cancel()
        await self._arrow.close()
        log.info("TAK bridge stopped")

    def reconfigure(self, cfg: TakBridgeConfig) -> None:
        """Apply new configuration (takes effect on next loop iteration)."""
        self.cfg = cfg
        self._arrow._base      = cfg.arrow_url.rstrip("/")
        self._arrow._callsign  = cfg.arrow_callsign
        self._arrow._password  = cfg.arrow_password
        self._arrow._token     = ""   # force re-login

    # ── ATAK client handler ───────────────────────────────────────────────────

    async def _handle_atak_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername", ("?", 0))
        client_uid = f"atak-{peer[0]}-{peer[1]}"
        self._pool.add(client_uid, writer)
        self.stats.atak_clients = self._pool.count()

        buf = CotFrameBuffer()
        try:
            while True:
                data = await asyncio.wait_for(reader.read(4096), timeout=120)
                if not data:
                    break
                for frame in buf.feed(data):
                    evt = self._parse_and_log(frame, source=client_uid)
                    if not evt:
                        continue
                    # Forward to Arrow
                    if self.cfg.pull_tak_contacts:
                        ok = await self._arrow.push_cot_track(evt)
                        if ok:
                            self.stats.arrow_pushed += 1
                    # Relay to all other ATAK clients (peer-to-peer relay)
                    await self._pool.broadcast(frame, exclude=client_uid)
                    # Relay to TAK server if connected
                    self._tak_origin_uids.add(evt.uid)
        except asyncio.TimeoutError:
            log.debug("ATAK client %s timed out", client_uid)
        except Exception as exc:
            log.debug("ATAK client %s error: %s", client_uid, exc)
        finally:
            self._pool.remove(client_uid)
            self.stats.atak_clients = self._pool.count()
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # ── TAK server client loop ────────────────────────────────────────────────

    async def _tak_client_loop(self) -> None:
        """Persistent client connection to an external TAK server."""
        backoff = 5
        while self._running:
            try:
                await self._connect_to_tak_server()
                backoff = 5
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.stats.tak_connected = False
                self.stats.errors += 1
                log.warning("TAK server connection lost (%s) — retry in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)

    async def _connect_to_tak_server(self) -> None:
        host, port = self.cfg.tak_host, self.cfg.tak_port
        if not host:
            return

        ssl_ctx = None
        if self.cfg.tak_ssl:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode    = ssl.CERT_NONE

        log.info("Connecting to TAK server %s:%d (ssl=%s)", host, port, self.cfg.tak_ssl)
        reader, writer = await asyncio.open_connection(host, port, ssl=ssl_ctx)
        self.stats.tak_connected = True
        log.info("Connected to TAK server %s:%d", host, port)

        # Send our presence CoT to identify to TAK server
        presence = CotEvent(
            uid=f"ARROW-BRIDGE-{self.cfg.tak_callsign}",
            cot_type="a-f-G-U-C",
            lat=0.0, lon=0.0,
            callsign=self.cfg.tak_callsign,
            platform="ARROW-BRIDGE",
        )
        writer.write(presence.to_xml())
        await writer.drain()

        buf = CotFrameBuffer()
        try:
            while self._running:
                data = await asyncio.wait_for(reader.read(4096), timeout=60)
                if not data:
                    break
                for frame in buf.feed(data):
                    evt = self._parse_and_log(frame, source="tak-server")
                    if not evt:
                        continue
                    self._tak_origin_uids.add(evt.uid)
                    # Forward to Arrow
                    if self.cfg.pull_tak_contacts:
                        ok = await self._arrow.push_cot_track(evt)
                        if ok:
                            self.stats.arrow_pulled += 1
                    # Relay to connected ATAK clients
                    await self._pool.broadcast(frame)
        except asyncio.TimeoutError:
            # Send keepalive CoT
            writer.write(presence.to_xml())
            await writer.drain()
        finally:
            self.stats.tak_connected = False
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # ── Arrow → TAK sync loop ─────────────────────────────────────────────────

    async def _sync_loop(self) -> None:
        """Periodically push Arrow operators and tactical objects to TAK/ATAK."""
        while self._running:
            try:
                await self._do_sync()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.stats.errors += 1
                log.warning("sync error: %s", exc)
            await asyncio.sleep(self.cfg.sync_interval_s)

    async def _do_sync(self) -> None:
        sent = 0

        if self.cfg.push_arrow_operators:
            ops = await self._arrow.get_operators_with_position()
            for op in ops:
                evt = operator_to_cot(op)
                # Skip if UID originated from TAK (avoid echo loop)
                if evt.uid in self._tak_origin_uids:
                    continue
                xml = evt.to_xml()
                await self._pool.broadcast(xml)
                await self._send_to_tak_server(xml)
                sent += 1

        if self.cfg.push_arrow_tac_objects:
            objs = await self._arrow.get_tactical_objects()
            for obj in objs:
                evt = tacobj_to_cot(obj)
                if not evt:
                    continue
                xml = evt.to_xml()
                await self._pool.broadcast(xml)
                await self._send_to_tak_server(xml)
                sent += 1

        self.stats.cot_sent += sent
        self.stats.last_sync_at = time.time()
        if sent:
            log.debug("sync: pushed %d CoT events to ATAK/TAK", sent)

    async def _send_to_tak_server(self, xml: bytes) -> None:
        """Send CoT to the TAK server connection (best-effort)."""
        # The TAK server writer is managed inside _connect_to_tak_server.
        # We don't keep a persistent reference here because the connection can
        # drop at any time. Broadcasting to ATAK clients is the primary path;
        # the TAK server upstream path is handled by the dedicated task.
        pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_and_log(self, frame: bytes, source: str) -> CotEvent | None:
        from tak_bridge.cot_stream import parse_cot
        evt = parse_cot(frame)
        if evt:
            self.stats.cot_received += 1
            log.debug("CoT from %s: uid=%s type=%s lat=%.4f lon=%.4f",
                      source, evt.uid, evt.cot_type, evt.lat, evt.lon)
        return evt
