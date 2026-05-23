"""Proxy routes for the Octopus streaming server.

All calls to the Octopus API are made server-side so the API key is never
exposed to the browser and CORS is not an issue.

Config (config.xml <octopus> block, overrideable by env vars):
    ARROW_OCTOPUS_URL     — base URL, e.g. http://192.168.0.240:8080
    ARROW_OCTOPUS_API_KEY — API key
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import ExternalStream, Operator

router = APIRouter(prefix="/octopus", tags=["octopus"])

_TIMEOUT = 8.0  # seconds


def _cfg():
    from backend.config.xml_config import load_config
    c = load_config().octopus
    return c.url.rstrip("/"), c.api_key


def _client():
    return httpx.AsyncClient(timeout=_TIMEOUT, verify=False)


# ── Config probe ──────────────────────────────────────────────────────────────

@router.get("/config")
def octopus_config(_: Operator = Depends(get_current_operator)) -> dict:
    """Return whether Octopus is configured (never exposes the API key)."""
    url, key = _cfg()
    return {"configured": bool(url), "url": url}


# ── Stream list ───────────────────────────────────────────────────────────────

@router.get("/streams")
async def list_octopus_streams(
    _: Operator = Depends(get_current_operator),
) -> list[dict]:
    url, key = _cfg()
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Octopus server not configured")
    async with _client() as client:
        try:
            r = await client.get(
                f"{url}/api/client/streams",
                params={"api_key": key} if key else {},
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code,
                                f"Octopus error: {exc.response.text[:200]}")
        except httpx.RequestError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"Cannot reach Octopus: {exc}")
    return r.json()


# ── Stream detail ─────────────────────────────────────────────────────────────

@router.get("/streams/{stream_id}")
async def get_octopus_stream(
    stream_id: str,
    _: Operator = Depends(get_current_operator),
) -> dict:
    url, key = _cfg()
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Octopus server not configured")
    async with _client() as client:
        try:
            r = await client.get(
                f"{url}/api/client/streams/{stream_id}",
                params={"api_key": key} if key else {},
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code,
                                f"Octopus error: {exc.response.text[:200]}")
        except httpx.RequestError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"Cannot reach Octopus: {exc}")
    return r.json()


# ── Add Octopus stream as persistent external stream ─────────────────────────

class _AddIn:
    pass  # resolved inline below


from pydantic import BaseModel


class _AddBody(BaseModel):
    name:        str
    url:         str
    stream_type: str
    description: str = ""


@router.post("/streams/{stream_id}/add", status_code=status.HTTP_201_CREATED)
async def add_octopus_stream(
    stream_id: str,
    body: _AddBody,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> dict:
    """Persist an Octopus stream as an ExternalStream so it appears in the streams tab."""
    _VALID = {"mjpeg", "hls", "video"}
    if body.stream_type not in _VALID:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"stream_type must be one of: {', '.join(sorted(_VALID))}")
    row = ExternalStream(
        name=body.name.strip(),
        url=body.url.strip(),
        stream_type=body.stream_type,
        description=body.description.strip() or f"Octopus stream {stream_id}",
        added_by=current.id,
    )
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "url": row.url, "stream_type": row.stream_type}
