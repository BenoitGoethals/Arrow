"""WebSocket voice bridge: browser ↔ Mumble server.

Each browser client gets its own pymumble connection.  Protocol
-----------------------------------------------------------------
Browser → backend (text / JSON):
  {"type":"connect","host":"…","port":64738,"username":"…","password":"…"}
  {"type":"ptt_start"}  {"type":"ptt_stop"}
  {"type":"mute"}       {"type":"unmute"}
  {"type":"deafen"}     {"type":"undeafen"}
  {"type":"join","channel_id":123}

Backend → browser (text / JSON):
  {"type":"state","state":"connecting"|"connected"|"disconnected"|"error","msg":"…"}
  {"type":"update","channels":[…],"users":[…]}
  {"type":"speaking","session":N,"name":"…","speaking":bool}

Backend → browser (binary): decoded PCM int16 LE, 48 kHz, mono
Browser → backend (binary): PCM int16 LE, 48 kHz, mono  (when PTT active)
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

# Audio constants — must match pymumble / Opus standard
SAMPLE_RATE = 48_000
CHUNK_MS = 20
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000  # 960 samples per 20 ms frame


class MumbleVoiceSession:
    """Manages one browser WebSocket ↔ one Mumble connection."""

    def __init__(self, ws, username: str):
        self._ws = ws
        self._username = username
        self._mumble = None
        self._audio_q: queue.Queue[bytes] = queue.Queue(maxsize=300)
        self._ptt = False
        self._stop = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Speaking detection
        self._last_audio: dict[int, float] = {}
        self._speaking: dict[int, bool] = {}

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(
        self,
        host: str,
        port: int,
        username: str,
        password: str = "",
        channel: str = "",
    ) -> None:
        self._loop = asyncio.get_event_loop()
        await self._send_json({"type": "state", "state": "connecting"})

        connected_ev = asyncio.Event()
        error: list[str] = []

        def _connect_thread():
            try:
                import pymumble_py3 as pymumble
                from pymumble_py3.callbacks import PYMUMBLE_CLBK_SOUNDRECEIVED

                m = pymumble.Mumble(
                    host,
                    username,
                    password=password,
                    port=port,
                    reconnect=False,
                    certfile=None,
                )
                m.set_application_string("Arrow Web")
                m.set_receive_sound(True)
                m.callbacks.set_callback(PYMUMBLE_CLBK_SOUNDRECEIVED, self._on_sound)
                m.start()
                m.is_ready()
                self._mumble = m
                # Auto-join the curated target channel (case-insensitive by name).
                if channel:
                    try:
                        for ch in m.channels.values():
                            if ch.get("name", "").lower() == channel.lower():
                                ch.move_in()
                                break
                    except Exception:
                        pass
            except Exception as exc:
                msg = str(exc)
                if "ConnectionRejectedError" in type(exc).__name__:
                    msg = "Server rejected connection — check credentials"
                error.append(msg)
            finally:
                self._loop.call_soon_threadsafe(connected_ev.set)

        threading.Thread(target=_connect_thread, daemon=True, name="mumble-ws").start()
        await connected_ev.wait()

        if error:
            await self._send_json({"type": "state", "state": "error", "msg": error[0]})
            return

        await self._send_json({"type": "state", "state": "connected"})

        bg = [
            asyncio.create_task(self._audio_send_loop()),
            asyncio.create_task(self._update_loop()),
            asyncio.create_task(self._speaking_loop()),
        ]
        try:
            await self._recv_loop()
        finally:
            self._stop.set()
            for t in bg:
                t.cancel()
            if self._mumble:
                try:
                    self._mumble.stop()
                except Exception:
                    pass
            await self._send_json({"type": "state", "state": "disconnected"})

    # ── Background tasks ──────────────────────────────────────────────────────

    async def _recv_loop(self):
        """Receive messages from the browser WebSocket."""
        try:
            while True:
                msg = await self._ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                raw_bytes = msg.get("bytes")
                raw_text = msg.get("text")
                if raw_bytes:
                    # PTT audio: PCM int16 from browser
                    if self._ptt and self._mumble:
                        try:
                            self._mumble.sound_output.add_sound(raw_bytes)
                        except Exception:
                            pass
                elif raw_text:
                    try:
                        await self._handle_cmd(json.loads(raw_text))
                    except Exception:
                        pass
        except Exception:
            pass

    async def _audio_send_loop(self):
        """Forward decoded PCM from Mumble → browser."""
        while not self._stop.is_set():
            try:
                pcm = self._audio_q.get_nowait()
                await self._ws.send_bytes(pcm)
            except queue.Empty:
                await asyncio.sleep(0.008)
            except Exception:
                break

    async def _update_loop(self):
        """Push channel + user list to browser every second."""
        while not self._stop.is_set():
            if self._mumble:
                try:
                    await self._send_json(
                        {
                            "type": "update",
                            "channels": self._snapshot_channels(),
                            "users": self._snapshot_users(),
                        }
                    )
                except Exception:
                    pass
            await asyncio.sleep(1)

    async def _speaking_loop(self):
        """Detect who is speaking and push events to browser."""
        while not self._stop.is_set():
            now = time.monotonic()
            for session, ts in list(self._last_audio.items()):
                speaking = (now - ts) < 0.4
                if self._speaking.get(session) != speaking:
                    self._speaking[session] = speaking
                    name = "?"
                    if self._mumble:
                        try:
                            name = self._mumble.users[session].get("name", str(session))
                        except Exception:
                            pass
                    try:
                        await self._send_json(
                            {
                                "type": "speaking",
                                "session": session,
                                "name": name,
                                "speaking": speaking,
                            }
                        )
                    except Exception:
                        pass
            await asyncio.sleep(0.15)

    # ── pymumble callback (runs in pymumble thread) ───────────────────────────

    def _on_sound(self, user, soundchunk):
        session = user.get("session", 0)
        self._last_audio[session] = time.monotonic()
        try:
            self._audio_q.put_nowait(soundchunk.pcm)
        except queue.Full:
            pass

    # ── Command handler ───────────────────────────────────────────────────────

    async def _handle_cmd(self, data: dict):
        cmd = data.get("type", "")
        m = self._mumble
        myself = m.users.myself if m else None

        if cmd == "ptt_start":
            self._ptt = True
        elif cmd == "ptt_stop":
            self._ptt = False
            # flush encoder
            if m:
                try:
                    m.sound_output.add_sound(b"\x00" * (CHUNK_FRAMES * 2))
                except Exception:
                    pass

        elif cmd == "mute" and myself:
            try:
                myself.mute()
            except Exception:
                pass
        elif cmd == "unmute" and myself:
            try:
                myself.unmute()
            except Exception:
                pass
        elif cmd == "deafen" and myself:
            try:
                myself.deafen()
            except Exception:
                pass
        elif cmd == "undeafen" and myself:
            try:
                myself.undeafen()
            except Exception:
                pass

        elif cmd == "join" and m:
            cid = data.get("channel_id")
            try:
                if cid in m.channels:
                    m.channels[cid].move_in()
            except Exception:
                pass

    # ── Snapshot helpers ──────────────────────────────────────────────────────

    def _snapshot_channels(self) -> list[dict]:
        if not self._mumble:
            return []
        try:
            return [
                {
                    "id": cid,
                    "name": ch.get("name", "?"),
                    "parent_id": ch.get("parent", -1),
                }
                for cid, ch in self._mumble.channels.items()
            ]
        except Exception:
            return []

    def _snapshot_users(self) -> list[dict]:
        if not self._mumble:
            return []
        try:
            my_s = self._mumble.users.myself_session
            return [
                {
                    "session": s,
                    "name": u.get("name", "?"),
                    "channel_id": u.get("channel_id", 0),
                    "muted": bool(u.get("mute") or u.get("self_mute")),
                    "deafened": bool(u.get("deaf") or u.get("self_deaf")),
                    "speaking": self._speaking.get(s, False),
                    "self": s == my_s,
                }
                for s, u in self._mumble.users.items()
            ]
        except Exception:
            return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _send_json(self, data: dict):
        try:
            await self._ws.send_text(json.dumps(data))
        except Exception:
            pass
