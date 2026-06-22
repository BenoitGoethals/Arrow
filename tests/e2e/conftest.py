"""Playwright fixtures for Arrow web UI e2e tests.

Services are auto-started if not already running on their default ports.
Requires PostgreSQL to be available (connection comes from config.xml).
The entire suite is skipped (not failed) when services cannot start.

Usage:
    uv run pytest tests/e2e/test_smoke.py -v            # headless (default)
    uv run pytest tests/e2e/test_smoke.py --headed      # with browser window
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator

import httpx
import pytest

BACKEND_URL = "http://localhost:6001"
WEB_URL = "http://localhost:6002"
ADMIN_CALLSIGN = "benoit"
ADMIN_PASSWORD = "ranger14"
_PROBE_TIMEOUT = 3.0
_STARTUP_TIMEOUT = 30.0


# ── service management ────────────────────────────────────────────────────────


def _probe(url: str) -> bool:
    try:
        r = httpx.get(url, timeout=_PROBE_TIMEOUT, follow_redirects=True)
        return r.status_code < 500
    except Exception:
        return False


def _wait_for(url: str, timeout: float = _STARTUP_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _probe(url):
            return True
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def live_services() -> Iterator[None]:
    """Ensure both Arrow services are reachable; auto-start if needed."""
    started: list[subprocess.Popen[bytes]] = []

    def _teardown() -> None:
        for p in started:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    if not _probe(f"{BACKEND_URL}/health"):
        started.append(subprocess.Popen(["uv", "run", "arrow-backend"]))
        if not _wait_for(f"{BACKEND_URL}/health"):
            _teardown()
            pytest.skip(
                "Backend failed to start within 30 s. "
                "Is PostgreSQL running? Try `uv run arrow` manually."
            )

    if not _probe(f"{WEB_URL}/"):
        started.append(subprocess.Popen(["uv", "run", "arrow-web"]))
        if not _wait_for(f"{WEB_URL}/"):
            _teardown()
            pytest.skip("Web service (Flask :6002) failed to start within 30 s.")

    yield  # type: ignore[misc]

    _teardown()


@pytest.fixture(scope="session")
def admin_token(live_services: None) -> str:  # type: ignore[return]
    """JWT for the seeded admin account (benoit / ranger14)."""
    r = httpx.post(
        f"{BACKEND_URL}/auth/login",
        content=f"username={ADMIN_CALLSIGN}&password={ADMIN_PASSWORD}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10.0,
    )
    if r.status_code != 200:
        pytest.skip(f"Admin login failed {r.status_code}: {r.text}")
    data = r.json()
    if data.get("mfa_required"):
        pytest.skip(
            "MFA is enabled on the admin account. "
            "Disable it via /auth/mfa/disable before running e2e tests."
        )
    token: str = data["access_token"]
    return token


@pytest.fixture()
def map_page(page, admin_token: str, live_services: None):  # type: ignore[no-untyped-def]
    """Playwright Page pre-authenticated as admin, navigated to /map/.

    Token is injected into localStorage so no UI login is required.
    Waits for Leaflet initialisation before returning.
    """
    # Navigate to the origin first so localStorage is writable for this origin
    page.goto(f"{WEB_URL}/login")

    # Inject credentials — mirrors what the login JS does
    page.evaluate(
        f"localStorage.setItem('arrow_token', {admin_token!r});"
        f"localStorage.setItem('arrow_role', 'ADMIN');"
    )

    page.goto(f"{WEB_URL}/map/")
    page.wait_for_load_state("networkidle", timeout=20_000)

    # Leaflet adds .leaflet-pane children once the map is initialised
    page.wait_for_selector(".leaflet-pane", timeout=15_000)

    return page
