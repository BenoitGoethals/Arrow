"""Phase 2: radial menu interaction and blackout detection.

Tests cover:
  1. Structural CSS check — detect the display:none→block pattern that causes
     GPU layer promotion and a full blackout in QtWebEngine / macOS Metal.
  2. Right-click interaction — radial opens, all 6 petals animate in.
  3. Petal pixel sampling — each button must show its accent color, not pure black.
  4. Recovery check — after closing the radial the map tile area must not be blacked out.

Run:
    uv run pytest tests/e2e/test_radial_menu.py -v
    uv run pytest tests/e2e/test_radial_menu.py -v --headed
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, expect

from tests.e2e.helpers.pixel import analyze_screenshot, save_screenshot

_SHOTS = Path("tests/e2e/screenshots")

_PETAL_IDS = [
    "ri-friendly",
    "ri-enemy",
    "ri-fire",
    "ri-objective",
    "ri-poi",
    "ri-report",
]

# Petal buttons have coloured backgrounds; anything this bright cannot be a blackout.
_PETAL_MIN_BRIGHTNESS = 30  # at least one channel must exceed this


# ── helpers ───────────────────────────────────────────────────────────────────


def _open_radial(page: Page) -> None:
    """Right-click the centre of #map and wait for all 6 petals to animate in."""
    bbox = page.locator("#map").bounding_box()
    assert bbox, "#map has no bounding box — is Leaflet initialised?"
    cx = bbox["x"] + bbox["width"] / 2
    cy = bbox["y"] + bbox["height"] / 2
    page.mouse.click(cx, cy, button="right")
    page.wait_for_selector("#radial-bg.open", timeout=5_000)
    # Petal animations are staggered at 40 ms each (6 × 40 = 240 ms); add buffer.
    page.wait_for_timeout(400)


def _close_radial(page: Page) -> None:
    """Click the dark scrim to close the radial and wait for it to disappear."""
    page.locator("#radial-bg.open").click()
    page.wait_for_function(
        "() => !document.getElementById('radial-bg').classList.contains('open')",
        timeout=3_000,
    )
    page.wait_for_timeout(200)


def _sample_petal(page: Page, img: Image.Image, petal_id: str) -> tuple[int, int, int]:
    """Return the RGB pixel at the visual centre of a petal button."""
    bb = page.locator(f"#{petal_id}.open").bounding_box()
    assert bb, f"#{petal_id}.open has no bounding box"
    px = max(0, min(int(bb["x"] + bb["width"] / 2), img.width - 1))
    py = max(0, min(int(bb["y"] + bb["height"] / 2), img.height - 1))
    return img.getpixel((px, py))  # type: ignore[return-value]


# ── 1. Structural CSS check ───────────────────────────────────────────────────


def test_radial_bg_not_display_none(map_page: Page) -> None:
    """#radial-bg must NOT use display:none — use visibility:hidden instead.

    display:none → display:block on right-click causes the browser to promote a
    new GPU compositing layer at interaction time.  In QtWebEngine on macOS Metal
    this makes the entire WebView go pitch-black until the next repaint event.
    The fix is to keep the element always-rendered (visibility:hidden keeps it in
    the GPU layer tree from page load) and only toggle visibility, never display.

    This test FAILS when the old pattern is present and PASSES once the fix is applied.
    """
    computed = map_page.evaluate(
        "() => window.getComputedStyle(document.getElementById('radial-bg')).display"
    )
    assert computed != "none", (
        f"#radial-bg computes to display:none (got '{computed}'). "
        "This will cause a GPU blackout in QtWebEngine / macOS Metal on every right-click. "
        "Fix: change CSS to visibility:hidden → visibility:visible + pointer-events toggle."
    )


# ── 2. Interaction ────────────────────────────────────────────────────────────


def test_right_click_opens_radial(map_page: Page) -> None:
    """Right-clicking the map must open the radial overlay and menu."""
    _open_radial(map_page)
    expect(map_page.locator("#radial-bg.open")).to_be_visible()
    expect(map_page.locator("#radial-menu.open")).to_be_visible()

    shot = map_page.screenshot(full_page=False)
    save_screenshot(shot, _SHOTS / "radial_open.png")


def test_radial_has_six_petals(map_page: Page) -> None:
    """All 6 petal buttons must have non-zero bounding boxes after the animation."""
    _open_radial(map_page)
    for pid in _PETAL_IDS:
        el = map_page.locator(f"#{pid}.open")
        expect(el).to_be_visible(timeout=2_000)
        bb = el.bounding_box()
        assert (
            bb and bb["width"] > 0 and bb["height"] > 0
        ), f"#{pid}.open rendered with zero size — petal did not animate in"


def test_radial_screenshot_before_after(map_page: Page) -> None:
    """Save before/after screenshots for visual inspection."""
    before = map_page.screenshot(full_page=False)
    save_screenshot(before, _SHOTS / "radial_before.png")

    _open_radial(map_page)

    after = map_page.screenshot(full_page=False)
    save_screenshot(after, _SHOTS / "radial_after.png")


# ── 3. Pixel-level blackout detection ────────────────────────────────────────


def test_radial_petals_not_blacked_out(map_page: Page) -> None:
    """Each petal button centre pixel must NOT be pure black.

    In a GPU blackout the entire WebView is painted black, including elements
    that should sit above the map tile layer.  Sampling the centre of each
    coloured petal button is a reliable blackout detector because these pixels
    should always be the button's accent colour (red, blue, amber, etc.).
    """
    _open_radial(map_page)
    shot = map_page.screenshot(full_page=False)
    save_screenshot(shot, _SHOTS / "radial_petal_check.png")

    img = Image.open(io.BytesIO(shot)).convert("RGB")
    failures: list[str] = []

    for pid in _PETAL_IDS:
        bb = map_page.locator(f"#{pid}.open").bounding_box()
        if not bb:
            failures.append(f"#{pid}: no bounding box")
            continue
        r, g, b = _sample_petal(map_page, img, pid)
        if max(r, g, b) < _PETAL_MIN_BRIGHTNESS:
            failures.append(
                f"#{pid}: centre pixel is ({r},{g},{b}) — "
                "nearly black, GPU blackout suspected"
            )

    assert not failures, (
        "Petal blackout detected:\n"
        + "\n".join(failures)
        + f"\nSee: {_SHOTS / 'radial_petal_check.png'}"
    )


# ── 4. Recovery after close ───────────────────────────────────────────────────


def test_map_recovers_after_radial_close(map_page: Page) -> None:
    """Map tile area must not be blacked out after the radial is closed.

    If a GPU layer was promoted during open but not released on close, the
    map tiles remain invisible even after the overlay disappears.
    """
    _open_radial(map_page)
    _close_radial(map_page)

    shot = map_page.screenshot(full_page=False)
    save_screenshot(shot, _SHOTS / "radial_after_close.png")

    report = analyze_screenshot(shot)
    assert not report.is_blackout, (
        f"Map is blacked out after closing the radial: "
        f"{report.black_ratio:.1%} of the tile area ({report.map_width}×{report.map_height} px) "
        f"is near-black.  A GPU layer was promoted but not restored on close. "
        f"See: {_SHOTS / 'radial_after_close.png'}"
    )
