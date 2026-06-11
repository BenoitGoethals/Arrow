"""GUI colour and font constants, plus small display helpers."""

from __future__ import annotations

from datetime import datetime

import wx

# ── Palette ───────────────────────────────────────────────────────────────────

C_BG     = wx.Colour(26,  31,  26)
C_PANEL  = wx.Colour(30,  42,  30)
C_CARD   = wx.Colour(28,  38,  28)
C_FG     = wx.Colour(200, 216, 200)
C_ACCENT = wx.Colour( 34, 197, 94)   # vivid green — primary action buttons
C_INFO   = wx.Colour( 59, 130, 246)  # NATO friendly blue — login / nav
C_DIM    = wx.Colour(148, 163, 184)  # slate-300, readable on dark panels
C_OK     = wx.Colour( 34, 197, 94)
C_WARN   = wx.Colour(245, 158,  11)
C_ERR    = wx.Colour(220,  38,  38)
C_XML    = wx.Colour(136, 204, 136)
C_WS     = wx.Colour(136, 136, 255)
C_TS     = wx.Colour(74,  154, 106)

# WebSocket status string → indicator colour
WS_STATUS_COLOUR: dict[str, wx.Colour] = {
    "ON":         C_OK,
    "OFF":        C_ERR,
    "ERR":        C_ERR,
    "CONNECTING": C_WARN,
}

# Category name → (R, G, B) tuple for list row colouring
CAT_COLOUR: dict[str, tuple[int, int, int]] = {
    "Friendly": (85,  153, 255),
    "Hostile":  (255, 85,  85),
    "Unknown":  (255, 204, 68),
    "POI":      (85,  221, 153),
}

# ── Fonts ─────────────────────────────────────────────────────────────────────

import sys

# wxPython on macOS reports a smaller default point size than GTK; bump by
# +3 there so the UI is legible on Retina displays. Override at runtime
# via ARROW_SIM_FONT_BUMP=N if needed.
import os
_DEFAULT_BUMP = 3 if sys.platform == "darwin" else 0
FONT_BUMP = int(os.environ.get("ARROW_SIM_FONT_BUMP", _DEFAULT_BUMP))


def mono(size: int = 11) -> wx.Font:
    return wx.Font(size + FONT_BUMP, wx.FONTFAMILY_TELETYPE,
                   wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)


def bold(size: int = 11) -> wx.Font:
    return wx.Font(size + FONT_BUMP, wx.FONTFAMILY_TELETYPE,
                   wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)


def apply_default_font(top_window: "wx.Window") -> None:
    """Set the application-wide default UI font so labels, list items,
    text controls and choices grow with the same bump as our mono/bold
    helpers. Call once from the top-level Frame after construction."""
    base = top_window.GetFont()
    base.SetPointSize(base.GetPointSize() + FONT_BUMP)
    top_window.SetFont(base)
    # Propagate to existing children so anything constructed before this
    # call also picks up the new size.
    def _recurse(w: "wx.Window") -> None:
        for child in w.GetChildren():
            child.SetFont(base)
            _recurse(child)
    _recurse(top_window)


# ── Misc ──────────────────────────────────────────────────────────────────────

def ts() -> str:
    """Current wall-clock time as HH:MM:SS string."""
    return datetime.now().strftime("%H:%M:%S")
