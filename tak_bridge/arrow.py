"""Arrow backend HTTP client for the TAK bridge.

Handles auth (JWT), operator position fetching, and pushing inbound
CoT events into Arrow as CotTrack or operator position updates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from tak_bridge.cot_stream import CotEvent

log = logging.getLogger("tak_bridge.arrow")


class ArrowClient:
    """Async HTTP client wrapping the Arrow REST API."""

    def __init__(self, base_url: str, callsign: str, password: str) -> None:
        self._base = base_url.rstrip("/")
        self._callsign = callsign
        self._password = password
        self._token: str = ""
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=15.0,
            verify=False,
        )

    async def login(self) -> bool:
        try:
            r = await self._client.post(
                "/auth/login",
                data={"username": self._callsign, "password": self._password},
            )
            if r.status_code == 200:
                p = r.json()
                self._token = p.get("access_token", "")
                log.info("Arrow login OK (callsign=%s)", self._callsign)
                return True
            log.warning("Arrow login failed: %d %s", r.status_code, r.text[:80])
        except Exception as exc:
            log.warning("Arrow login error: %s", exc)
        return False

    def _hdr(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _ensure_token(self) -> bool:
        if not self._token:
            return await self.login()
        return True

    async def _get(self, path: str) -> Any | None:
        if not await self._ensure_token():
            return None
        try:
            r = await self._client.get(path, headers=self._hdr())
            if r.status_code == 401:
                await self.login()
                r = await self._client.get(path, headers=self._hdr())
            return r.json() if r.status_code == 200 else None
        except Exception as exc:
            log.debug("GET %s error: %s", path, exc)
            return None

    # ── Arrow data fetchers ───────────────────────────────────────────────────

    async def get_operators_with_position(self) -> list[dict]:
        """Return all operators that have GPS coordinates."""
        hierarchy = await self._get("/hierarchy")
        if not hierarchy:
            return []
        ops: list[dict] = []
        for co in hierarchy.get("companies", []):
            for plt in co.get("platoons", []):
                for sec in plt.get("sections", []):
                    for team in sec.get("teams", []):
                        for op in team.get("operators", []):
                            if op.get("latitude") and op.get("longitude"):
                                ops.append(op)
        # Also include unassigned operators with positions
        for op in hierarchy.get("unassigned_operators", []):
            if op.get("latitude") and op.get("longitude"):
                ops.append(op)
        return ops

    async def get_tactical_objects(self) -> list[dict]:
        """Return all tactical objects (enemy positions, POIs, etc.)."""
        return await self._get("/tactical-objects") or []

    async def get_vehicles(self) -> list[dict]:
        """Return all vehicles with online operators."""
        return await self._get("/vehicles") or []

    # ── Push CoT into Arrow ───────────────────────────────────────────────────

    async def push_cot_track(self, evt: CotEvent) -> bool:
        """Upsert a foreign CoT event as a CotTrack in Arrow."""
        if not await self._ensure_token():
            return False
        body = {
            "type": "SPOT",  # reuse SPOT report type for inbound TAK contact
            "payload": {
                "source": "TAK_BRIDGE",
                "cot_uid": evt.uid,
                "cot_type": evt.cot_type,
                "callsign": evt.callsign or evt.uid,
                "latitude": evt.lat,
                "longitude": evt.lon,
                "altitude": evt.hae,
                "speed": evt.speed,
                "course": evt.course,
                "team": evt.team,
                "platform": evt.platform,
                "dtg": datetime.now(timezone.utc).isoformat(),
            },
        }
        try:
            # Post raw CoT XML to the CoT endpoint (fastest path — no translation)
            r = await self._client.post(
                "/cot",
                content=evt.raw_xml or evt.to_xml(),
                headers={**self._hdr(), "Content-Type": "application/xml"},
            )
            if r.status_code in (200, 201):
                return True
            if r.status_code == 401:
                await self.login()
                r = await self._client.post(
                    "/cot",
                    content=evt.raw_xml or evt.to_xml(),
                    headers={**self._hdr(), "Content-Type": "application/xml"},
                )
                return r.status_code in (200, 201)
            log.debug("push_cot_track %s → %d", evt.uid, r.status_code)
        except Exception as exc:
            log.debug("push_cot_track error: %s", exc)
        return False

    async def close(self) -> None:
        await self._client.aclose()
