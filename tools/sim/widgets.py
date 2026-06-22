"""Styled log widget helpers (wx.stc.StyledTextCtrl with named colour slots)."""

from __future__ import annotations

import wx
import wx.stc as stc
import wx.lib.buttons as wxbtn
from typing import Callable

from .theme import (
    C_PANEL,
    C_ACCENT,
    C_TS,
    C_OK,
    C_ERR,
    C_WARN,
    C_XML,
    C_WS,
    C_DIM,
    bold,
    mono,
)


# ── Cross-platform high-contrast button ──────────────────────────────────────
def make_btn(
    parent: wx.Window,
    label: str,
    handler: Callable[[wx.CommandEvent], None],
    *,
    bg: wx.Colour = C_ACCENT,
    fg: wx.Colour = wx.WHITE,
    size: tuple[int, int] = (-1, 30),
) -> wxbtn.GenButton:
    """High-contrast owner-drawn button that respects fg/bg on every OS.

    Native ``wx.Button.SetBackgroundColour`` is ignored on macOS (Aqua keeps
    the system tint), so white text ends up unreadable on a light button.
    ``GenButton`` is owner-drawn so the colours we set are the colours
    rendered everywhere.
    """
    b = wxbtn.GenButton(parent, label=label, size=size, style=wx.BORDER_NONE)
    b.SetUseFocusIndicator(True)
    b.SetFont(bold(11))
    b.SetBackgroundColour(bg)
    b.SetForegroundColour(fg)
    b.SetBezelWidth(1)
    b.Bind(wx.EVT_BUTTON, handler)
    return b


# ── Style slot indices ────────────────────────────────────────────────────────

ST_DEFAULT = 0
ST_TS = 1
ST_OK = 2
ST_ERR = 3
ST_WARN = 4
ST_XML = 5
ST_DATA = 6
ST_CHANNEL = 7
ST_SYS = 8

# Maps the ``style`` string used in WsMonitor._log() to a slot index.
LOG_STYLE_MAP: dict[str, int] = {
    "sys": ST_SYS,
    "err": ST_ERR,
    "ok": ST_OK,
    "warn": ST_WARN,
}


# ── Factory ───────────────────────────────────────────────────────────────────


def make_log(parent: wx.Window, fg_default: wx.Colour) -> stc.StyledTextCtrl:
    """Create a read-only styled text log control parented to *parent*."""
    ctrl = stc.StyledTextCtrl(parent, style=wx.BORDER_NONE)
    ctrl.SetReadOnly(True)
    ctrl.SetMarginWidth(0, 0)
    ctrl.SetMarginWidth(1, 0)
    ctrl.SetScrollWidthTracking(True)
    ctrl.SetWrapMode(stc.STC_WRAP_NONE)

    def _sty(n: int, fg: wx.Colour) -> None:
        ctrl.StyleSetForeground(n, fg)
        ctrl.StyleSetBackground(n, C_PANEL)
        ctrl.StyleSetFont(n, mono(9))

    _sty(stc.STC_STYLE_DEFAULT, fg_default)
    ctrl.StyleClearAll()
    for idx, colour in [
        (ST_DEFAULT, fg_default),
        (ST_TS, C_TS),
        (ST_OK, C_OK),
        (ST_ERR, C_ERR),
        (ST_WARN, C_WARN),
        (ST_XML, C_XML),
        (ST_DATA, C_WS),
        (ST_CHANNEL, C_WARN),
        (ST_SYS, C_DIM),
    ]:
        _sty(idx, colour)

    ctrl.SetCaretForeground(C_ACCENT)
    ctrl.SetSelBackground(True, C_ACCENT)
    ctrl.SetSelForeground(True, wx.WHITE)
    return ctrl


def log_append(ctrl: stc.StyledTextCtrl, text: str, style: int = ST_DEFAULT) -> None:
    """Append *text* to *ctrl* with the given style slot, then scroll to end."""
    ctrl.SetReadOnly(False)
    pos = ctrl.GetLength()
    ctrl.AppendText(text)
    ctrl.StartStyling(pos)
    ctrl.SetStyling(len(text.encode()), style)
    ctrl.GotoPos(ctrl.GetLength())
    ctrl.SetReadOnly(True)
