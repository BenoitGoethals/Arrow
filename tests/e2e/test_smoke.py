"""Phase 1 smoke tests: map loads, Leaflet initialises, no blackout on load.

Run:
    uv run pytest tests/e2e/test_smoke.py -v
    uv run pytest tests/e2e/test_smoke.py -v --headed   # show browser window
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page, expect

from tests.e2e.helpers.pixel import analyze_screenshot, save_screenshot

_SHOTS = Path("tests/e2e/screenshots")


def test_map_container_visible(map_page: Page) -> None:
    """#map div must be in the DOM and visible."""
    expect(map_page.locator("#map")).to_be_visible()


def test_leaflet_initialised(map_page: Page) -> None:
    """Leaflet must have added its pane structure inside #map."""
    # Leaflet appends .leaflet-map-pane once init() runs
    expect(map_page.locator("#map .leaflet-map-pane")).to_be_visible()


def test_sidebar_visible(map_page: Page) -> None:
    """Operator sidebar (#sidebar) must be present."""
    expect(map_page.locator("#sidebar")).to_be_visible()


def test_map_tiles_load(map_page: Page) -> None:
    """At least one tile must have finished loading within 10 s."""
    map_page.wait_for_selector(".leaflet-tile-loaded", timeout=10_000)
    count = map_page.locator(".leaflet-tile-loaded").count()
    assert count > 0, "No Leaflet tiles loaded"


def test_no_blackout_on_load(map_page: Page) -> None:
    """The map tile area must not be blacked out on initial load.

    Takes a full-page screenshot, crops out the sidebar and nav bar,
    and asserts that fewer than 50 % of pixels are near-black.
    Saves the screenshot to tests/e2e/screenshots/map_initial.png for review.
    """
    shot = map_page.screenshot(full_page=False)
    path = save_screenshot(shot, _SHOTS / "map_initial.png")

    report = analyze_screenshot(shot)
    assert not report.is_blackout, (
        f"Map appears blacked out on load: {report.black_ratio:.1%} of the "
        f"tile area ({report.map_width}×{report.map_height} px) is near-black. "
        f"Screenshot saved to {path}"
    )
