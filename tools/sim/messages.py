"""Typed queue message dataclasses for thread-safe GUI updates.

Every cross-thread communication goes through ``queue.Queue[QueueMsg]``.
``SimFrame._handlers`` maps each type to its handler method, replacing a
fragile if/elif chain with a direct dispatch table (Command-map pattern).
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class MsgLoginOk:
    token: str


@dataclasses.dataclass
class MsgLoginErr:
    error: str


@dataclasses.dataclass
class MsgSendOk:
    status: int
    body:   str


@dataclasses.dataclass
class MsgSendErr:
    error: str


@dataclasses.dataclass
class MsgAutoTrigger:
    """Posted by AutoSend's background thread to request a send on the main thread."""


@dataclasses.dataclass
class MsgAutoStopped:
    """Posted when the AutoSend loop exits."""


@dataclasses.dataclass
class MsgWsStatus:
    """WebSocket connection state change. text: "ON" | "OFF" | "ERR" | "CONNECTING"."""
    text: str


@dataclasses.dataclass
class MsgWsBtn:
    """Request to update the WS connect/disconnect button label."""
    label: str


@dataclasses.dataclass
class MsgWsRaw:
    """Raw JSON string received from the WebSocket (or a ``__log__`` sentinel)."""
    raw: str


QueueMsg = (
    MsgLoginOk | MsgLoginErr
    | MsgSendOk | MsgSendErr
    | MsgAutoTrigger | MsgAutoStopped
    | MsgWsStatus | MsgWsBtn | MsgWsRaw
)
