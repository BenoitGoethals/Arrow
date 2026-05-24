"""Proxy routes for the Octopus streaming server.

All calls to the Octopus API are made server-side so the API key is never
exposed to the browser and CORS is not an issue.

Config (config.xml <octopus> block, overrideable by env vars):
    ARROW_OCTOPUS_URL     — base URL, e.g. http://192.168.0.240:8080
    ARROW_OCTOPUS_API_KEY — API key
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import ExternalStream, Operator, OctopusDetection
from backend.websocket.manager import broadcaster

log = logging.getLogger(__name__)

router = APIRouter(prefix="/octopus", tags=["octopus"])

_TIMEOUT = 8.0  # seconds


def _cfg():
    """Return (url, api_key) — DB settings win over config.xml."""
    from backend.config.xml_config import load_config
    from backend.storage.database import SessionLocal
    from backend.storage.models import SystemSetting
    db = SessionLocal()
    try:
        db_url = db.get(SystemSetting, "octopus.url")
        db_key = db.get(SystemSetting, "octopus.api_key")
    finally:
        db.close()
    xml = load_config().octopus
    url = (db_url.value if db_url else None) or xml.url
    key = (db_key.value if db_key else None) or xml.api_key
    return url.rstrip("/"), key


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
    data = r.json()

    # Always route HLS through Arrow's own proxy so the browser never needs
    # direct access to the Octopus port (which is often firewalled).
    # Return a root-relative path; the JS prepends ARROW_BACKEND_URL.
    data["hls_url"] = f"/octopus/hls/{stream_id}/live.m3u8"

    return data


# ── HLS proxy ─────────────────────────────────────────────────────────────────

@router.get("/hls/{stream_id}/{filename:path}")
async def hls_proxy(
    stream_id: str,
    filename: str,
) -> Response:
    """Proxy Octopus HLS playlists and fMP4 segments through Arrow.

    No JWT auth — stream IDs are UUIDs (unguessable), Octopus enforces its
    own api_key, and the Octopus port is internal.  Routing here avoids
    requiring the browser to reach the Octopus port directly.
    """
    url, key = _cfg()
    if not url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Octopus not configured")

    seg_url = f"{url}/static/hls/{stream_id}/{filename}"
    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        try:
            params = {"api_key": key} if key else {}
            r = await client.get(seg_url, params=params)
        except httpx.RequestError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                                f"Cannot reach Octopus: {exc}")

    if r.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{filename} not found")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text[:200])

    if filename.endswith(".m3u8"):
        media_type = "application/vnd.apple.mpegurl"
    elif filename.endswith((".mp4", ".m4s")):
        media_type = "video/mp4"
    else:
        media_type = r.headers.get("content-type", "application/octet-stream")

    return Response(content=r.content, media_type=media_type)


# ── Add Octopus stream as persistent external stream ─────────────────────────

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


# ── Webhook receiver (called by Octopus, no JWT auth) ─────────────────────────

def _verify_sig(body: bytes, header: str, key: str) -> bool:
    expected = "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def octopus_webhook(request: Request) -> dict:
    body = await request.body()
    _, key = _cfg()

    sig = request.headers.get("X-Octopus-Signature", "")
    if key:
        if not sig:
            log.warning("Octopus webhook: missing signature — rejected")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing signature")
        if not _verify_sig(body, sig, key):
            log.warning("Octopus webhook: invalid signature — rejected")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    else:
        log.warning("Octopus webhook received but no API key configured — skipping signature check")

    try:
        det = json.loads(body)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON")

    if det.get("event") != "detection":
        return {"ok": True, "skipped": True}

    import uuid as _uuid
    event_id    = det.get("id") or str(_uuid.uuid4())
    stream_id   = det.get("stream_id", "")
    label       = det.get("label", "")
    confidence  = float(det.get("confidence", 0.0))
    description = det.get("description", "")
    bbox        = json.dumps(det.get("bbox", []))
    snapshot    = det.get("snapshot_url", "")
    ts_raw      = det.get("timestamp", "")
    try:
        occurred = datetime.fromisoformat(ts_raw).replace(tzinfo=timezone.utc)
    except Exception:
        occurred = datetime.now(timezone.utc)

    db = _db_session()
    try:
        # Deduplicate only when the sender supplied an explicit event_id
        if det.get("id") and db.query(OctopusDetection).filter(
            OctopusDetection.event_id == event_id
        ).first():
            return {"ok": True, "duplicate": True}

        row = OctopusDetection(
            event_id=event_id, stream_id=stream_id, label=label,
            confidence=confidence, description=description,
            bbox=bbox, snapshot_url=snapshot, occurred_at=occurred,
        )
        db.add(row); db.commit(); db.refresh(row)
        det_id = row.id
    finally:
        db.close()

    await broadcaster.broadcast({
        "channel": "octopus-detection",
        "event":   "detection",
        "data": {
            "id":           det_id,
            "event_id":     event_id,
            "stream_id":    stream_id,
            "label":        label,
            "confidence":   confidence,
            "description":  description,
            "bbox":         det.get("bbox", []),
            "snapshot_url": f"/octopus/detections/{det_id}/snapshot",
            "occurred_at":  occurred.isoformat(),
        },
    })
    log.info("Octopus detection: %s (%.0f%%) on stream %s", label, confidence * 100, stream_id)
    return {"ok": True, "broadcast": True}


def _db_session():
    from backend.storage.database import SessionLocal
    return SessionLocal()


# ── Recent detections list ────────────────────────────────────────────────────

@router.get("/detections")
def list_detections(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[dict]:
    rows = (db.query(OctopusDetection)
              .order_by(OctopusDetection.occurred_at.desc())
              .limit(limit).all())
    return [
        {
            "id":           r.id,
            "stream_id":    r.stream_id,
            "label":        r.label,
            "confidence":   r.confidence,
            "description":  r.description,
            "bbox":         json.loads(r.bbox or "[]"),
            "snapshot_url": f"/octopus/detections/{r.id}/snapshot",
            "occurred_at":  r.occurred_at.isoformat() if r.occurred_at else None,
        }
        for r in rows
    ]


# ── Snapshot proxy ────────────────────────────────────────────────────────────

@router.get("/detections/{detection_id}/snapshot")
async def detection_snapshot(
    detection_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Response:
    row = db.get(OctopusDetection, detection_id)
    if not row or not row.snapshot_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    base_url, key = _cfg()
    snap = row.snapshot_url
    if snap.startswith("/"):
        snap = base_url + snap

    async with _client() as client:
        try:
            params = {"api_key": key} if key else {}
            r = await client.get(snap, params=params)
            r.raise_for_status()
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Cannot fetch snapshot: {exc}")

    return Response(
        content=r.content,
        media_type=r.headers.get("content-type", "image/jpeg"),
    )
