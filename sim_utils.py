"""Shared utilities for all Arrow simulators.

Every simulator:
  1. Imports this module.
  2. Calls ``create_mission_sync`` or ``create_mission_async`` right after
     obtaining the admin token.
  3. Stores the returned ``mission_id`` and passes it to all API calls so the
     server scopes every object to the correct mission.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("sim")

# ── Persistent backend URL ────────────────────────────────────────────────────

_CONFIG_DIR  = Path.home() / ".config" / "arrow"
_CONFIG_FILE = _CONFIG_DIR / "simulator.json"


def load_saved_backend() -> str | None:
    try:
        return json.loads(_CONFIG_FILE.read_text()).get("backend") or None
    except Exception:
        return None


def save_backend(url: str) -> None:
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps({"backend": url}, indent=2))
    except Exception as e:
        log.debug("could not save backend URL: %s", e)


def split_base(base_url: str) -> tuple[str, str]:
    """Return *(origin, path_prefix)* from a base URL.

    Examples::

        "http://192.168.0.240:6001"      -> ("http://192.168.0.240:6001", "")
        "http://192.168.0.240:6200/api"  -> ("http://192.168.0.240:6200", "/api")
    """
    parts = urlsplit(base_url)
    prefix = (parts.path or "").rstrip("/")
    origin = f"{parts.scheme}://{parts.netloc}"
    return origin, prefix


# ── Synchronous mission helpers ───────────────────────────────────────────────

def create_mission_sync(
    client: httpx.Client,
    base_url: str,
    token: str,
    name: str,
    description: str = "",
) -> int | None:
    """Create a mission (or adopt an existing one with the same name) and start it.

    Returns the ``mission_id`` on success, ``None`` on failure.
    The caller should pass the id as ``X-Mission-ID`` on every subsequent request.
    """
    origin, prefix = split_base(base_url)
    base = f"{origin}{prefix}"
    hdr  = {"Authorization": f"Bearer {token}"}

    # ── create ────────────────────────────────────────────────────────────────
    r = client.post(f"{base}/missions",
                    json={"name": name, "description": description},
                    headers=hdr, timeout=10)

    if r.status_code == 201:
        mission = r.json()
        log.info("Created mission '%s' (id=%d)", name, mission["id"])
    elif r.status_code == 409 or r.status_code == 422:
        # Might already exist — find it by name
        r2 = client.get(f"{base}/missions", headers=hdr, timeout=10)
        missions = r2.json() if r2.status_code == 200 else []
        mission = next((m for m in missions if m["name"] == name), None)
        if not mission:
            log.warning("Cannot create or find mission '%s': %d %s",
                        name, r.status_code, r.text[:120])
            return None
        log.info("Adopting existing mission '%s' (id=%d, status=%s)",
                 name, mission["id"], mission["status"])
    else:
        log.warning("Mission creation failed: %d %s", r.status_code, r.text[:120])
        return None

    mission_id = mission["id"]

    # ── start if still PLANNING ───────────────────────────────────────────────
    if mission.get("status") == "PLANNING":
        rs = client.post(f"{base}/missions/{mission_id}/start",
                         headers=hdr, timeout=10)
        if rs.status_code == 200:
            log.info("Mission '%s' started", name)
        else:
            log.warning("Could not start mission: %d", rs.status_code)

    return mission_id


# ── Async mission helpers ─────────────────────────────────────────────────────

async def create_mission_async(
    client: httpx.AsyncClient,
    base: str,
    token: str,
    name: str,
    description: str = "",
) -> int | None:
    """Async version of :func:`create_mission_sync`.

    ``base`` is the full API base URL including any path prefix
    (e.g. ``http://host:6001`` or ``http://host:6200/api``).
    """
    hdr = {"Authorization": f"Bearer {token}"}

    r = await client.post(f"{base}/missions",
                          json={"name": name, "description": description},
                          headers=hdr, timeout=10)

    if r.status_code == 201:
        mission = r.json()
        log.info("Created mission '%s' (id=%d)", name, mission["id"])
    else:
        # Fall back to finding an existing mission with the same name
        r2 = await client.get(f"{base}/missions", headers=hdr, timeout=10)
        missions = r2.json() if r2.status_code == 200 else []
        mission = next((m for m in missions if m["name"] == name), None)
        if not mission:
            log.warning("Cannot create or find mission '%s': %d %s",
                        name, r.status_code, r.text[:120])
            return None
        log.info("Adopting existing mission '%s' (id=%d, status=%s)",
                 name, mission["id"], mission.get("status"))

    mission_id = mission["id"]

    if mission.get("status") == "PLANNING":
        rs = await client.post(f"{base}/missions/{mission_id}/start",
                               headers=hdr, timeout=10)
        if rs.status_code == 200:
            log.info("Mission '%s' started", name)

    return mission_id


# ── Mission-aware Api class (for sync simulators) ─────────────────────────────

class Api:
    """Synchronous HTTP client with optional mission scoping.

    Pass any of these as ``base_url`` and the leading-slash paths in the
    rest of the script keep working unchanged::

        http://host:6001              (direct backend)
        http://host:6200/api          (Caddy with /api prefix)
    """

    def __init__(self, base_url: str, mission_id: int | None = None) -> None:
        origin, self._prefix = split_base(base_url)
        self._base_url  = base_url
        self.mission_id = mission_id
        self.c = httpx.Client(base_url=origin, timeout=30.0)

    # ------------------------------------------------------------------
    def _p(self, path: str) -> str:
        if not self._prefix or path.startswith(self._prefix + "/") or path == self._prefix:
            return path
        return self._prefix + path

    def _hdr(self, tok: str) -> dict[str, str]:
        h: dict[str, str] = {"Authorization": f"Bearer {tok}"}
        if self.mission_id:
            h["X-Mission-ID"] = str(self.mission_id)
        return h

    # ------------------------------------------------------------------
    def login(self, callsign: str, password: str) -> str:
        import sys
        r = self.c.post(self._p("/auth/login"),
                        data={"username": callsign, "password": password})
        if r.status_code != 200:
            sys.exit(f"login failed for {callsign} ({r.status_code}): {r.text}")
        p = r.json()
        if p.get("mfa_required"):
            sys.exit(f"{callsign} has MFA enabled — pick a non-MFA admin")
        return p["access_token"]

    def create_mission(self, token: str, name: str, description: str = "") -> int | None:
        mid = create_mission_sync(self.c, self._base_url, token, name, description)
        if mid:
            self.mission_id = mid
        return mid

    def get(self, path: str, tok: str) -> object:
        r = self.c.get(self._p(path), headers=self._hdr(tok))
        r.raise_for_status()
        return r.json()

    def post(self, path: str, tok: str, body: dict) -> object:
        r = self.c.post(self._p(path), json=body, headers=self._hdr(tok))
        if r.status_code >= 400:
            log.warning("POST %s -> %d: %s", path, r.status_code, r.text[:200])
            r.raise_for_status()
        return r.json() if r.content else {}

    def patch(self, path: str, tok: str, body: dict) -> object:
        r = self.c.patch(self._p(path), json=body, headers=self._hdr(tok))
        if r.status_code >= 400:
            log.warning("PATCH %s -> %d: %s", path, r.status_code, r.text[:200])
        return r.json() if r.content else {}

    def delete(self, path: str, tok: str) -> int:
        r = self.c.delete(self._p(path), headers=self._hdr(tok))
        return r.status_code
