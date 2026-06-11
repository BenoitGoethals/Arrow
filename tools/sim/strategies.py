"""Send strategies — interchangeable send behaviours (Strategy pattern).

All strategies accept a ``post_fn: Callable[[], None]`` that performs one send.
``OnceSend`` and ``BurstSend`` are one-shot; ``AutoSend`` runs in a daemon
thread and must be stopped explicitly.
"""

from __future__ import annotations

import threading
from typing import Callable, Protocol


class SendStrategy(Protocol):
    """Structural protocol satisfied by OnceSend and BurstSend."""

    def execute(self, post_fn: Callable[[], None]) -> None: ...


class OnceSend:
    """Send exactly one message."""

    def execute(self, post_fn: Callable[[], None]) -> None:
        post_fn()


class BurstSend:
    """Send *count* messages back-to-back."""

    def __init__(self, count: int) -> None:
        self._count = max(1, count)

    def execute(self, post_fn: Callable[[], None]) -> None:
        for _ in range(self._count):
            post_fn()


class AutoSend:
    """Send repeatedly every *interval* seconds in a daemon thread.

    Stopping is responsive: uses ``threading.Event.wait`` so the thread wakes
    immediately on ``stop()`` rather than sleeping out the full interval.

    ``trigger_fn`` must be thread-safe (i.e. a queue put, not a wx API call).
    ``on_done`` is called from the background thread when the loop exits.
    """

    def __init__(self, interval: float) -> None:
        self._interval = max(0.1, interval)
        self._stop_ev  = threading.Event()

    def start(self, trigger_fn: Callable[[], None],
              on_done: Callable[[], None]) -> None:
        self._stop_ev.clear()

        def _loop() -> None:
            trigger_fn()                               # immediate first fire
            while not self._stop_ev.wait(self._interval):
                trigger_fn()
            on_done()

        threading.Thread(target=_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop_ev.set()
