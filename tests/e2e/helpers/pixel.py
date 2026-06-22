"""Screenshot pixel analysis for map blackout detection."""

from __future__ import annotations

import io
from pathlib import Path
from typing import NamedTuple

from PIL import Image

# Approximate layout constants (pixels at 1x DPR, 1280×800 viewport)
SIDEBAR_WIDTH = 340
NAV_HEIGHT = 56
# Tile layer is dark (#0d1117 background), so only pure black is a blackout signal.
# A true blackout: WebView paints nothing — pixels are (0,0,0) or very close.
BLACK_THRESHOLD = 15  # per-channel max value to count as "black"
BLACKOUT_RATIO = 0.50  # >50% black pixels in the map area = blackout


class PixelReport(NamedTuple):
    black_ratio: float
    is_blackout: bool
    map_width: int
    map_height: int


def analyze_screenshot(
    screenshot: bytes,
    *,
    crop_left: int = SIDEBAR_WIDTH,
    crop_top: int = NAV_HEIGHT,
    black_threshold: int = BLACK_THRESHOLD,
    blackout_ratio: float = BLACKOUT_RATIO,
) -> PixelReport:
    """Return pixel stats for the map tile area of a full-page screenshot.

    Crops out the sidebar and nav bar so only the Leaflet canvas region is
    analysed. A ratio >= blackout_ratio indicates a Metal/GPU blackout.
    """
    img = Image.open(io.BytesIO(screenshot)).convert("RGB")
    w, h = img.size

    # Guard: if the screenshot is smaller than the sidebar, skip cropping
    left = min(crop_left, w // 2)
    top = min(crop_top, h // 4)
    map_area = img.crop((left, top, w, h))
    mw, mh = map_area.size

    pixels = list(map_area.getdata())
    black = sum(
        1
        for r, g, b in pixels
        if r < black_threshold and g < black_threshold and b < black_threshold
    )
    total = mw * mh
    ratio = black / total if total else 0.0

    return PixelReport(
        black_ratio=ratio,
        is_blackout=ratio >= blackout_ratio,
        map_width=mw,
        map_height=mh,
    )


def save_screenshot(data: bytes, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p
