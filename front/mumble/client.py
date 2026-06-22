"""Mumble voice client — pymumble wrapper with sounddevice audio I/O.

Thread model
------------
- pymumble.Mumble runs its own daemon thread (TCP keepalive + audio decode).
- _PollThread (QThread) polls channel/user state every 500 ms and emits signals.
- sounddevice InputStream  → captures mic → feeds mumble when PTT active.
- sounddevice OutputStream → plays received PCM from _audio_out_q.
"""

from __future__ import annotations

import queue
import logging
import threading
import time
from typing import Optional

import front.mumble.opus_fix as _opus_fix  # patches ctypes + ssl before opuslib loads

import numpy as np
import sounddevice as sd

try:
    import pymumble_py3 as pymumble
    from pymumble_py3.callbacks import PYMUMBLE_CLBK_SOUNDRECEIVED

    MUMBLE_AVAILABLE = True
    _MUMBLE_ERR = ""
except Exception as _e:
    MUMBLE_AVAILABLE = False
    _hint = _opus_fix.OPUS_INSTALL_HINT
    _MUMBLE_ERR = f"{_e}" + (f" — {_hint}" if _hint else "")

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer, Qt

log = logging.getLogger(__name__)

SAMPLE_RATE = 48_000
CHUNK_MS = 20
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000  # 960


# ─────────────────────────────────────────────────────────────────────────────
# Audio helpers
# ─────────────────────────────────────────────────────────────────────────────


class _AudioOut:
    """Thread-safe PCM queue fed into a sounddevice OutputStream."""

    def __init__(self, device=None):
        self._q: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._stream: Optional[sd.OutputStream] = None
        self._device = device

    def start(self):
        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_FRAMES,
            device=self._device,
            callback=self._cb,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        # drain
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def push(self, pcm: bytes):
        try:
            self._q.put_nowait(pcm)
        except queue.Full:
            pass

    def _cb(self, outdata, frames, _time, _status):
        out = np.zeros(frames, dtype=np.int16)
        written = 0
        while written < frames:
            try:
                chunk = self._q.get_nowait()
            except queue.Empty:
                break
            arr = np.frombuffer(chunk, dtype=np.int16)
            n = min(len(arr), frames - written)
            out[written : written + n] = arr[:n]
            written += n
        outdata[:, 0] = out


class _AudioIn:
    """sounddevice InputStream → feeds PCM to a callback when PTT is active."""

    def __init__(self, on_chunk, device=None):
        self._on_chunk = on_chunk
        self._device = device
        self._active = False
        self._stream: Optional[sd.InputStream] = None

    def start(self):
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_FRAMES,
            device=self._device,
            callback=self._cb,
        )
        self._stream.start()

    def stop(self):
        self._active = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def set_active(self, active: bool):
        self._active = active

    def _cb(self, indata, frames, _time, _status):
        if self._active:
            self._on_chunk(bytes(indata[:, 0]))


# ─────────────────────────────────────────────────────────────────────────────
# Poll thread — keeps channel/user state fresh
# ─────────────────────────────────────────────────────────────────────────────


class _PollThread(QThread):
    channels_updated = pyqtSignal(list)
    users_updated = pyqtSignal(list)

    def __init__(self, client_ref, parent=None):
        super().__init__(parent)
        self._client = client_ref
        self._stop = threading.Event()

    def run(self):
        while not self._stop.wait(0.5):
            m = self._client._mumble
            if m is None:
                continue
            try:
                channels = self._client._build_channels()
                users = self._client._build_users()
                self.channels_updated.emit(channels)
                self.users_updated.emit(users)
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        self.wait(2000)


# ─────────────────────────────────────────────────────────────────────────────
# Main client
# ─────────────────────────────────────────────────────────────────────────────


class MumbleClient(QObject):
    """High-level Mumble client — connect, PTT, channel management."""

    state_changed = pyqtSignal(
        str
    )  # 'disconnected' | 'connecting' | 'connected' | 'error:msg'
    channels_updated = pyqtSignal(list)  # [{id, name, parent_id, depth}]
    users_updated = pyqtSignal(
        list
    )  # [{session, name, channel_id, muted, deafened, speaking, self}]
    speaking_changed = pyqtSignal(str, bool)  # username, is_speaking

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mumble: Optional[object] = None
        self._poll: Optional[_PollThread] = None
        self._audio_out: Optional[_AudioOut] = None
        self._audio_in: Optional[_AudioIn] = None
        self._ptt_active = False
        self._muted = False
        self._deafened = False
        self._in_device = None
        self._out_device = None
        self._username = ""

        # Speaking detection: track when we last received audio per session
        self._last_audio: dict[int, float] = {}
        self._speaking: dict[int, bool] = {}
        self._speak_timer = QTimer(self)
        self._speak_timer.setInterval(200)
        self._speak_timer.timeout.connect(self._check_speaking)

        # Manage the timer from the main thread via queued signal connection
        # (pymumble callbacks fire from a daemon thread; QTimers can't be
        # started/stopped from there)
        self.state_changed.connect(
            self._on_state_for_timer, type=Qt.ConnectionType.QueuedConnection
        )

    def _on_state_for_timer(self, state: str):
        """Runs in the main thread (queued connection) — safe to touch QTimer."""
        if state == "connected":
            self._speak_timer.start()
        else:
            self._speak_timer.stop()
            self._last_audio.clear()
            self._speaking.clear()

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return MUMBLE_AVAILABLE

    @property
    def unavailable_reason(self) -> str:
        return "" if MUMBLE_AVAILABLE else _MUMBLE_ERR

    def set_devices(self, in_device=None, out_device=None):
        self._in_device = in_device
        self._out_device = out_device

    def connect_to(
        self, host: str, port: int, username: str, password: str = "", channel: str = ""
    ):
        if not MUMBLE_AVAILABLE:
            self.state_changed.emit(f"error:Mumble not available — {_MUMBLE_ERR}")
            return
        self.disconnect()
        self._username = username
        self.state_changed.emit("connecting")

        def _do():
            try:
                m = pymumble.Mumble(
                    host,
                    username,
                    password=password,
                    port=port,
                    reconnect=False,
                    certfile=None,
                )
                m.set_application_string("Arrow Front")
                m.callbacks.set_callback(PYMUMBLE_CLBK_SOUNDRECEIVED, self._on_sound)
                m.start()
                m.is_ready()  # blocks until connected (or raises)
                self._mumble = m

                # Emit "connected" here — is_ready() returning is the authoritative
                # "fully connected" signal.  The CLBK_CONNECTED callback is unreliable
                # (it fires from inside connect() before is_ready() unblocks, racing
                # with Qt's queued event processing).
                self.state_changed.emit("connected")

                # Join requested channel
                if channel:
                    for cid, ch in m.channels.items():
                        if ch.get("name", "").lower() == channel.lower():
                            ch.move_in()
                            break

                self._start_audio()
                self._start_poll()
                # speak timer started via state_changed → _on_state_for_timer (main thread)

            except Exception as exc:
                msg = str(exc)
                # Unwrap pymumble's generic wrapper to show the real cause
                if "ConnectionRejectedError" in type(exc).__name__:
                    msg = "Server rejected connection — check host/port/password"
                self.state_changed.emit(f"error:{msg}")
                self._mumble = None

        threading.Thread(target=_do, daemon=True).start()

    def disconnect(self):
        # _speak_timer stopped via state_changed → _on_state_for_timer (main thread)
        self._stop_poll()
        self._stop_audio()
        if self._mumble:
            try:
                self._mumble.stop()
            except Exception:
                pass
            self._mumble = None
        self.state_changed.emit("disconnected")

    def set_ptt(self, active: bool):
        self._ptt_active = active
        if self._audio_in:
            self._audio_in.set_active(active and not self._muted)
        elif active:
            log.warning(
                "PTT pressed but audio input is not available — check mic permissions"
            )

    def set_muted(self, muted: bool):
        self._muted = muted
        if self._audio_in:
            self._audio_in.set_active(self._ptt_active and not muted)
        if self._mumble:
            try:
                myself = self._mumble.users.myself
                if myself:
                    myself.mute() if muted else myself.unmute()
            except Exception:
                pass

    def set_deafened(self, deafened: bool):
        self._deafened = deafened
        if self._mumble:
            try:
                myself = self._mumble.users.myself
                if myself:
                    myself.deafen() if deafened else myself.undeafen()
            except Exception:
                pass

    def join_channel(self, channel_id: int):
        if self._mumble and channel_id in self._mumble.channels:
            self._mumble.channels[channel_id].move_in()

    def send_text(self, message: str):
        if self._mumble:
            try:
                self._mumble.my_channel().send_text_message(message)
            except Exception:
                pass

    # ── Callbacks (called from pymumble thread) ───────────────────────────────

    def _on_sound(self, user, soundchunk):
        """Received audio from a remote user."""
        if self._deafened or self._audio_out is None:
            return
        self._audio_out.push(soundchunk.pcm)
        session = user.get("session", 0)
        self._last_audio[session] = time.monotonic()

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _start_audio(self):
        try:
            self._audio_out = _AudioOut(device=self._out_device)
            self._audio_out.start()
        except Exception as exc:
            log.warning("Mumble: audio output failed to start: %s", exc)
            self._audio_out = None
        try:
            self._audio_in = _AudioIn(self._feed_mic, device=self._in_device)
            self._audio_in.start()
        except Exception as exc:
            log.warning(
                "Mumble: audio input failed to start: %s — mic may need permission", exc
            )
            self._audio_in = None

    def _stop_audio(self):
        self._ptt_active = False
        if self._audio_in:
            self._audio_in.stop()
            self._audio_in = None
        if self._audio_out:
            self._audio_out.stop()
            self._audio_out = None

    def _feed_mic(self, pcm: bytes):
        if self._mumble:
            try:
                self._mumble.sound_output.add_sound(pcm)
            except Exception:
                pass

    def _start_poll(self):
        self._poll = _PollThread(self)
        self._poll.channels_updated.connect(self.channels_updated)
        self._poll.users_updated.connect(self.users_updated)
        self._poll.start()

    def _stop_poll(self):
        if self._poll:
            self._poll.stop()
            self._poll = None

    def _check_speaking(self):
        now = time.monotonic()
        if self._mumble is None:
            return
        for session, ts in list(self._last_audio.items()):
            speaking = (now - ts) < 0.4
            if self._speaking.get(session) != speaking:
                self._speaking[session] = speaking
                try:
                    name = self._mumble.users[session].get("name", str(session))
                except Exception:
                    name = str(session)
                self.speaking_changed.emit(name, speaking)

    def _build_channels(self) -> list[dict]:
        if not self._mumble:
            return []
        out = []
        for cid, ch in self._mumble.channels.items():
            out.append(
                {
                    "id": cid,
                    "name": ch.get("name", "?"),
                    "parent_id": ch.get("parent", -1),
                }
            )
        return out

    def _build_users(self) -> list[dict]:
        if not self._mumble:
            return []
        try:
            my_session = self._mumble.users.myself.get("session", -1)
        except Exception:
            my_session = -1
        out = []
        for session, u in self._mumble.users.items():
            out.append(
                {
                    "session": session,
                    "name": u.get("name", "?"),
                    "channel_id": u.get("channel_id", 0),
                    "muted": bool(u.get("mute") or u.get("self_mute")),
                    "deafened": bool(u.get("deaf") or u.get("self_deaf")),
                    "speaking": self._speaking.get(session, False),
                    "self": session == my_session,
                }
            )
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Device enumeration helper
# ─────────────────────────────────────────────────────────────────────────────


def list_audio_devices() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return (input_devices, output_devices) as (index, name) tuples."""
    inputs, outputs = [], []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                inputs.append((i, d["name"]))
            if d["max_output_channels"] > 0:
                outputs.append((i, d["name"]))
    except Exception:
        pass
    return inputs, outputs
