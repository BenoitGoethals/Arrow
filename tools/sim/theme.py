"""GUI colour and font constants, plus small display helpers."""

from __future__ import annotations

from datetime import datetime

import wx

# ── Palette ───────────────────────────────────────────────────────────────────

C_BG     = wx.Colour(26,  31,  26)
C_PANEL  = wx.Colour(30,  42,  30)
C_CARD   = wx.Colour(28,  38,  28)
C_FG     = wx.Colour(200, 216, 200)
C_ACCENT = wx.Colour(74,  154, 106)
C_DIM    = wx.Colour(106, 138, 106)
C_OK     = wx.Colour(68,  204, 136)
C_WARN   = wx.Colour(204, 170, 68)
C_ERR    = wx.Colour(204, 68,  68)
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

def mono(size: int = 9) -> wx.Font:
    return wx.Font(size, wx.FONTFAMILY_TELETYPE,
                   wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)


def bold(size: int = 9) -> wx.Font:
    return wx.Font(size, wx.FONTFAMILY_TELETYPE,
                   wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)


# ── Misc ──────────────────────────────────────────────────────────────────────

def ts() -> str:
    """Current wall-clock time as HH:MM:SS string."""
    return datetime.now().strftime("%H:%M:%S")
