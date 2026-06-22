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

_CONFIG_DIR = Path.home() / ".config" / "arrow"
_CONFIG_FILE = _CONFIG_DIR / "simulator.json"


def load_saved_backend() -> str | None:
    try:
        return json.loads(_CONFIG_FILE.read_text()).get("backend") or None
    except Exception:
        return None


def save_backend(url: str) -> None:
    try:
        # Normalise to HTTPS before persisting
        if (
            url.startswith("http://")
            and "localhost" not in url
            and "127.0.0.1" not in url
        ):
            url = "https://" + url[7:]
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
    map_center_lat: float | None = None,
    map_center_lng: float | None = None,
    map_zoom: int = 13,
) -> int | None:
    """Create a mission (or adopt an existing one with the same name) and start it.

    Returns the ``mission_id`` on success, ``None`` on failure.
    The caller should pass the id as ``X-Mission-ID`` on every subsequent request.
    """
    origin, prefix = split_base(base_url)
    base = f"{origin}{prefix}"
    hdr = {"Authorization": f"Bearer {token}"}

    payload: dict = {"name": name, "description": description, "map_zoom": map_zoom}
    if map_center_lat is not None:
        payload["map_center_lat"] = map_center_lat
        payload["map_center_lng"] = map_center_lng

    # ── create ────────────────────────────────────────────────────────────────
    r = client.post(f"{base}/missions", json=payload, headers=hdr, timeout=10)

    if r.status_code == 201:
        mission = r.json()
        log.info("Created mission '%s' (id=%d)", name, mission["id"])
    elif r.status_code == 409 or r.status_code == 422:
        # Might already exist — find it by name
        r2 = client.get(f"{base}/missions", headers=hdr, timeout=10)
        missions = r2.json() if r2.status_code == 200 else []
        mission = next((m for m in missions if m["name"] == name), None)
        if not mission:
            log.warning(
                "Cannot create or find mission '%s': %d %s",
                name,
                r.status_code,
                r.text[:120],
            )
            return None
        log.info(
            "Adopting existing mission '%s' (id=%d, status=%s)",
            name,
            mission["id"],
            mission["status"],
        )
    else:
        log.warning("Mission creation failed: %d %s", r.status_code, r.text[:120])
        return None

    mission_id = mission["id"]

    # ── patch map centre if the existing mission has none ─────────────────────
    if map_center_lat is not None and mission.get("map_center_lat") is None:
        client.patch(
            f"{base}/missions/{mission_id}",
            json={
                "map_center_lat": map_center_lat,
                "map_center_lng": map_center_lng,
                "map_zoom": map_zoom,
            },
            headers=hdr,
            timeout=10,
        )

    # ── start if still PLANNING ───────────────────────────────────────────────
    if mission.get("status") == "PLANNING":
        rs = client.post(f"{base}/missions/{mission_id}/start", headers=hdr, timeout=10)
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
    map_center_lat: float | None = None,
    map_center_lng: float | None = None,
    map_zoom: int = 13,
) -> int | None:
    """Async version of :func:`create_mission_sync`.

    ``base`` is the full API base URL including any path prefix
    (e.g. ``http://host:6001`` or ``http://host:6200/api``).
    """
    hdr = {"Authorization": f"Bearer {token}"}

    payload: dict = {"name": name, "description": description, "map_zoom": map_zoom}
    if map_center_lat is not None:
        payload["map_center_lat"] = map_center_lat
        payload["map_center_lng"] = map_center_lng

    r = await client.post(f"{base}/missions", json=payload, headers=hdr, timeout=10)

    if r.status_code == 201:
        mission = r.json()
        log.info("Created mission '%s' (id=%d)", name, mission["id"])
    else:
        # Fall back to finding an existing mission with the same name
        r2 = await client.get(f"{base}/missions", headers=hdr, timeout=10)
        missions = r2.json() if r2.status_code == 200 else []
        mission = next((m for m in missions if m["name"] == name), None)
        if not mission:
            log.warning(
                "Cannot create or find mission '%s': %d %s",
                name,
                r.status_code,
                r.text[:120],
            )
            return None
        log.info(
            "Adopting existing mission '%s' (id=%d, status=%s)",
            name,
            mission["id"],
            mission.get("status"),
        )

    mission_id = mission["id"]

    # ── patch map centre if the existing mission has none ─────────────────────
    if map_center_lat is not None and mission.get("map_center_lat") is None:
        await client.patch(
            f"{base}/missions/{mission_id}",
            json={
                "map_center_lat": map_center_lat,
                "map_center_lng": map_center_lng,
                "map_zoom": map_zoom,
            },
            headers=hdr,
            timeout=10,
        )

    if mission.get("status") == "PLANNING":
        rs = await client.post(
            f"{base}/missions/{mission_id}/start", headers=hdr, timeout=10
        )
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
        url = base_url.rstrip("/")
        if (
            url.startswith("http://")
            and "localhost" not in url
            and "127.0.0.1" not in url
        ):
            url = "https://" + url[7:]
        origin, self._prefix = split_base(url)
        self._base_url = url
        self.mission_id = mission_id
        self.c = httpx.Client(base_url=origin, timeout=30.0, verify=False)

    # ------------------------------------------------------------------
    def _p(self, path: str) -> str:
        if (
            not self._prefix
            or path.startswith(self._prefix + "/")
            or path == self._prefix
        ):
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

        r = self.c.post(
            self._p("/auth/login"), data={"username": callsign, "password": password}
        )
        if r.status_code != 200:
            sys.exit(f"login failed for {callsign} ({r.status_code}): {r.text}")
        p = r.json()
        if p.get("mfa_required"):
            sys.exit(f"{callsign} has MFA enabled — pick a non-MFA admin")
        return p["access_token"]

    def create_mission(
        self,
        token: str,
        name: str,
        description: str = "",
        map_center_lat: float | None = None,
        map_center_lng: float | None = None,
        map_zoom: int = 13,
    ) -> int | None:
        mid = create_mission_sync(
            self.c,
            self._base_url,
            token,
            name,
            description,
            map_center_lat,
            map_center_lng,
            map_zoom,
        )
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


# ── Geographic helpers ────────────────────────────────────────────────────────

import math as _math

LAT_DEG_PER_M: float = 1.0 / 111_000.0


def lon_deg_per_m(lat: float) -> float:
    return 1.0 / (111_000.0 * _math.cos(_math.radians(lat)))


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * 111_000
    dlon = (lon2 - lon1) * 111_000 * _math.cos(_math.radians((lat1 + lat2) / 2))
    return _math.hypot(dlat, dlon)


def step_towards(
    lat: float, lon: float, tlat: float, tlon: float, speed_ms: float, dt: float
) -> tuple[float, float]:
    d = dist_m(lat, lon, tlat, tlon)
    if d < 0.5:
        return tlat, tlon
    move = min(speed_ms * dt, d)
    dlat = (tlat - lat) * 111_000
    dlon = (tlon - lon) * 111_000 * _math.cos(_math.radians(lat))
    brg = _math.atan2(dlon, dlat)
    return (
        lat + move * _math.cos(brg) * LAT_DEG_PER_M,
        lon + move * _math.sin(brg) * lon_deg_per_m(lat),
    )


def jitter(
    lat: float, lon: float, north_m: float, east_m: float
) -> tuple[float, float]:
    return (
        lat + north_m * LAT_DEG_PER_M,
        lon + east_m * lon_deg_per_m(lat),
    )


# ── MGRS conversion (WGS-84, DMATM 8358.1) ───────────────────────────────────


def _utm_zone(lat: float, lon: float) -> int:
    if 56 <= lat < 64 and 3 <= lon < 12:
        return 32
    if 72 <= lat <= 84:
        if lon < 9:
            return 31
        if lon < 21:
            return 33
        if lon < 33:
            return 35
        if lon < 42:
            return 37
    return int((lon + 180) / 6) + 1


def _lat_band(lat: float) -> str:
    return "CDEFGHJKLMNPQRSTUVWX"[min(19, int((lat + 80) / 8))]


def _to_utm(lat: float, lon: float, zone: int) -> tuple[float, float]:
    a, f = 6_378_137, 1 / 298.257223563
    e2 = 2 * f - f * f
    e4 = e2 * e2
    e6 = e4 * e2
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    lr = _math.radians(lat)
    lo = _math.radians(lon)
    lo0 = _math.radians((zone - 1) * 6 - 180 + 3)
    N = a / _math.sqrt(1 - e2 * _math.sin(lr) ** 2)
    T = _math.tan(lr) ** 2
    C = ep2 * _math.cos(lr) ** 2
    av = _math.cos(lr) * (lo - lo0)
    M = a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lr
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * _math.sin(2 * lr)
        + (15 * e4 / 256 + 45 * e6 / 1024) * _math.sin(4 * lr)
        - (35 * e6 / 3072) * _math.sin(6 * lr)
    )
    e = (
        k0
        * N
        * (
            av
            + (1 - T + C) * av**3 / 6
            + (5 - 18 * T + T**2 + 72 * C - 58 * ep2) * av**5 / 120
        )
        + 500_000
    )
    n = k0 * (
        M
        + N
        * _math.tan(lr)
        * (
            av**2 / 2
            + (5 - T + 9 * C + 4 * C**2) * av**4 / 24
            + (61 - 58 * T + T**2 + 600 * C - 330 * ep2) * av**6 / 720
        )
    )
    if lat < 0:
        n += 10_000_000
    return e, n


_SET_COLS = ["ABCDEFGH", "JKLMNPQR", "STUVWXYZ"]
_ROW_ODD = "ABCDEFGHJKLMNPQRSTUV"
_ROW_EVEN = "FGHJKLMNPQRSTUVABCDE"


def mgrs(lat: float, lon: float, acc: int = 5) -> str:
    """Return an MGRS grid string for WGS-84 lat/lon (default 5-digit = 1 m precision)."""
    try:
        z = _utm_zone(lat, lon)
        b = _lat_band(lat)
        e, n = _to_utm(lat, lon, z)
        col = _SET_COLS[(z - 1) % 3][max(0, min(7, int(e / 100_000) - 1))]
        row = (_ROW_ODD if z % 2 else _ROW_EVEN)[int(n / 100_000) % 20]
        es = str(int(e % 100_000)).zfill(5)[:acc]
        ns = str(int(n % 100_000)).zfill(5)[:acc]
        return f"{z}{b}{col}{row} {es}{ns}"
    except Exception:
        return f"{lat:.4f},{lon:.4f}"


# ── Async simulation context ──────────────────────────────────────────────────


class AsyncSimContext:
    """Shared state for async simulators: base URL, mission ID, and HTTP helpers."""

    def __init__(self, base_url: str, sim_password: str = "Arrow2525!") -> None:
        url = base_url.rstrip("/")
        # Auto-upgrade HTTP → HTTPS for remote hosts; keep http:// for localhost
        if (
            url.startswith("http://")
            and "localhost" not in url
            and "127.0.0.1" not in url
        ):
            url = "https://" + url[7:]
        self._base = url
        self._password = sim_password
        self.mission_id: int | None = None
        self._fail_count = 0

    @property
    def base(self) -> str:
        return self._base

    def _hdr(self, token: str) -> dict[str, str]:
        h: dict[str, str] = {}
        if token:
            h["Authorization"] = f"Bearer {token}"
        if self.mission_id:
            h["X-Mission-ID"] = str(self.mission_id)
        return h

    async def api(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        token: str = "",
        **kwargs,
    ) -> "dict | list | None":
        headers = self._hdr(token)
        try:
            r = await client.request(
                method, f"{self._base}{path}", headers=headers, timeout=20, **kwargs
            )
            if 200 <= r.status_code < 300:
                return r.json() if r.content else {}
            self._fail_count += 1
            body = r.text[:400] if self._fail_count <= 5 else r.text[:80]
            log.warning("%-6s %-30s → %d  %s", method, path, r.status_code, body)
            return None
        except Exception as exc:
            self._fail_count += 1
            log.warning("%-6s %-30s → %s", method, path, exc)
            return None

    async def login(
        self, client: httpx.AsyncClient, callsign: str, password: str | None = None
    ) -> "str | None":
        pw = password if password is not None else self._password
        try:
            r = await client.post(
                f"{self._base}/auth/login",
                data={"username": callsign, "password": pw},
                timeout=15,
            )
            if r.status_code == 200:
                payload = r.json()
                if payload.get("mfa_required"):
                    log.warning(
                        "Account %s has MFA enabled — use a non-MFA admin.", callsign
                    )
                    return None
                return payload.get("access_token")
            log.warning(
                "login %s → HTTP %d  %s",
                callsign,
                r.status_code,
                (r.text or "<empty body>")[:200],
            )
        except httpx.ConnectError as exc:
            log.warning(
                "login %s → CONNECT-ERROR: %s (wrong --backend URL?)",
                callsign,
                exc or "no detail",
            )
        except Exception as exc:
            log.warning("login %s → %s: %s", callsign, type(exc).__name__, exc)
        return None
