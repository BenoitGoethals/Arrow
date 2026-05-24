"""Proxy routes for the Octopus streaming server.

All calls to the Octopus API are made server-side so the API key is never
exposed to the browser and CORS is not an issue.

Config (config.xml <octopus> block, overrideable by env vars):
    ARROW_OCTOPUS_URL     — base URL, e.g. http://192.168.0.240:8080
    ARROW_OCTOPUS_API_KEY — API key
"""

from __future__ import annotations

import collections
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

# Ring buffer — last 20 webhook calls (any outcome)
_webhook_log: collections.deque[dict] = collections.deque(maxlen=20)


def _log_webhook_call(*, remote: str, status: str, detail: str,
                      payload: dict | None, headers: dict | None = None) -> None:
    _webhook_log.appendleft({
        "ts":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "remote":  remote,
        "status":  status,   # "broadcast" | "skipped" | "duplicate" | "rejected" | "error"
        "detail":  detail,
        "headers": headers,
        "payload": payload,
    })


# Octopus may use different field names for the event type; accept all common variants
_EVENT_ALIASES = ("event", "type", "event_type", "action")


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
    # If a DB row exists (even with empty value), it takes full precedence over
    # config.xml — an empty DB value means the user explicitly cleared the key.
    url = db_url.value if db_url is not None else xml.url
    key = db_key.value if db_key is not None else xml.api_key
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

@router.get("/webhook")
async def webhook_health() -> dict:
    """Reachability probe — Octopus or admin can GET this to confirm the endpoint is alive."""
    url, key = _cfg()
    return {
        "ok":          True,
        "endpoint":    "ready",
        "signature":   "required" if key else "disabled",
        "octopus_url": url or None,
    }


def _verify_sig(body: bytes, header: str, key: str) -> bool:
    expected = "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def octopus_webhook(request: Request) -> dict:
    import uuid as _uuid
    remote = request.client.host if request.client else "unknown"
    body   = await request.body()
    _, key = _cfg()

    sig = request.headers.get("X-Octopus-Signature", "")
    if key:
        # Dump every header so we can see what Octopus actually sends
        all_headers = {k: v for k, v in request.headers.items()
                       if k.lower() not in ("authorization", "cookie")}
        sig_candidates = {k: v for k, v in request.headers.items()
                          if "sig" in k.lower() or "hmac" in k.lower() or "token" in k.lower()}

        if not sig:
            detail = (
                f"Missing X-Octopus-Signature header. "
                f"Signature-like headers present: {sig_candidates or 'none'}. "
                f"All headers: {all_headers}"
            )
            _log_webhook_call(remote=remote, status="rejected", detail=detail,
                              payload=None, headers=all_headers)
            log.warning(
                "Octopus webhook from %s: missing signature — rejected\n"
                "  Signature-like headers: %s\n"
                "  All request headers:    %s",
                remote, sig_candidates or "none", all_headers,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing signature")
        if not _verify_sig(body, sig, key):
            detail = f"Invalid HMAC signature. Received: {sig!r}"
            _log_webhook_call(remote=remote, status="rejected", detail=detail,
                              payload=None, headers=all_headers)
            log.warning(
                "Octopus webhook from %s: invalid HMAC — rejected. Received sig: %s",
                remote, sig,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    else:
        log.debug("Octopus webhook from %s: no API key configured — accepting unsigned", remote)

    try:
        det = json.loads(body)
    except Exception:
        _log_webhook_call(remote=remote, status="error", detail="Invalid JSON body", payload=None)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON")

    # Accept event type from any common field name Octopus might use
    event_val = next((det[k] for k in _EVENT_ALIASES if k in det), None)
    if event_val != "detection":
        payload_keys  = list(det.keys())
        payload_preview = json.dumps(det, default=str)[:400]
        detail = (
            f"event field value={event_val!r} — none of {_EVENT_ALIASES} found. "
            f"Payload keys: {payload_keys}. "
            f"Full payload: {payload_preview}"
        )
        _log_webhook_call(remote=remote, status="skipped", detail=detail, payload=det)
        log.info(
            "Octopus webhook from %s: skipped\n"
            "  Expected: one of %s == 'detection'\n"
            "  Payload keys present: %s\n"
            "  Full payload: %s",
            remote, _EVENT_ALIASES, payload_keys, payload_preview,
        )
        return {"ok": True, "skipped": True, "detail": detail}

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
            _log_webhook_call(remote=remote, status="duplicate",
                              detail=f"event_id={event_id} already in DB", payload=det)
            return {"ok": True, "duplicate": True}

        row = OctopusDetection(
            event_id=event_id, stream_id=stream_id, label=label,
            confidence=confidence, description=description,
            bbox=bbox, snapshot_url=snapshot, occurred_at=occurred,
        )
        db.add(row); db.commit(); db.refresh(row)
        det_id = row.id
    except Exception as exc:
        _log_webhook_call(remote=remote, status="error", detail=f"DB error: {exc}", payload=det)
        log.exception("Octopus webhook DB error")
        raise
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
    _log_webhook_call(remote=remote, status="broadcast",
                      detail=f"label={label} conf={confidence:.0%} stream={stream_id}", payload=det)
    log.info("Octopus detection: %s (%.0f%%) on stream %s", label, confidence * 100, stream_id)
    return {"ok": True, "broadcast": True}


@router.get("/webhook/log")
def webhook_call_log(_: Operator = Depends(get_current_operator)) -> list[dict]:
    """Return the last 20 webhook calls for debugging — no auth beyond JWT."""
    return list(_webhook_log)


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
