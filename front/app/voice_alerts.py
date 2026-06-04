"""Voice alert player — TTS speech + synthesised alarm tone played in parallel."""
from __future__ import annotations

import threading
import time
import logging

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QObject
from PyQt6.QtTextToSpeech import QTextToSpeech

log = logging.getLogger(__name__)

_SAMPLE_RATE = 44_100
_TONE_SECS   = 3.0
_TONE_DELAY  = 1.2   # seconds after speech starts before tone kicks in

# alert_type → (spoken text, tone freq Hz, waveform)
_VOICES: dict[str, tuple[str, float, str]] = {
    "TIC":          ("Contact, contact, contact",           1200, "square"),
    "DRONE_SPOTTED":("Drone spotted, drone spotted",         540, "drone"),
    "MEDICAL":      ("Medical emergency, medical emergency",  880, "sawtooth"),
    "EVAC":         ("Evacuation, evacuation",                660, "sine"),
    "LOST_COMMS":   ("Lost comms, lost comms",                440, "sine"),
}


def _build_tone(freq: float, waveform: str, duration: float) -> np.ndarray:
    n   = int(_SAMPLE_RATE * duration)
    t   = np.linspace(0, duration, n, endpoint=False)

    if waveform == "square":
        raw = np.sign(np.sin(2 * np.pi * freq * t)).astype(np.float32)
    elif waveform == "sawtooth":
        raw = (2 * (t * freq - np.floor(t * freq + 0.5))).astype(np.float32)
    elif waveform == "drone":
        carrier = np.sin(2 * np.pi * freq * t)
        lfo     = np.sign(np.sin(2 * np.pi * 12 * t))
        raw     = (carrier * (0.5 + 0.5 * lfo)).astype(np.float32)
    else:
        raw = np.sin(2 * np.pi * freq * t).astype(np.float32)

    # 0.3 s on / 0.2 s off pulsing envelope
    period = int(_SAMPLE_RATE * 0.5)
    on_len = int(_SAMPLE_RATE * 0.3)
    mask   = np.zeros(n, dtype=np.float32)
    for i in range(0, n, period):
        mask[i : i + on_len] = 1.0
    raw *= mask * 0.55

    # Fade out over the last quarter
    fade_start = int(n * 0.75)
    raw[fade_start:] *= np.linspace(1.0, 0.0, n - fade_start, dtype=np.float32)
    return raw


def _play_tone_after(freq: float, waveform: str, delay: float):
    """Background thread: wait `delay` seconds then play the alarm tone."""
    def _run():
        try:
            if delay > 0:
                time.sleep(delay)
            tone = _build_tone(freq, waveform, _TONE_SECS)
            sd.play(tone, samplerate=_SAMPLE_RATE, blocking=True)
        except Exception as exc:
            log.debug("Voice alert tone error: %s", exc)
    threading.Thread(target=_run, daemon=True).start()


class VoiceAlertPlayer(QObject):
    """Call play(alert_type) from the main thread to speak + beep."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = True

        try:
            self._tts = QTextToSpeech(self)
            self._tts.setRate(-0.1)
            self._tts.setVolume(1.0)
            if self._tts.state() == QTextToSpeech.State.Error:
                log.warning("QTextToSpeech error: %s", self._tts.errorString())
                self._tts = None
        except Exception as exc:
            log.warning("QTextToSpeech unavailable: %s", exc)
            self._tts = None

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, v: bool):
        self._enabled = bool(v)

    def play(self, alert_type: str):
        if not self._enabled:
            return
        text, freq, waveform = _VOICES.get(
            alert_type,
            (f"Alert: {alert_type.replace('_', ' ').lower()}", 880, "sawtooth"),
        )

        # Speak the alert (non-blocking — Qt handles it internally)
        if self._tts is not None:
            try:
                self._tts.stop()
                self._tts.say(text)
            except Exception as exc:
                log.debug("TTS say() error: %s", exc)

        # Play alarm tone in background after speech has had time to start
        delay = _TONE_DELAY if self._tts is not None else 0.0
        _play_tone_after(freq, waveform, delay)
