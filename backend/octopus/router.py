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


def _log_webhook_call(
    *,
    remote: str,
    status: str,
    detail: str,
    payload: dict | None,
    headers: dict | None = None,
) -> None:
    _webhook_log.appendleft(
        {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "remote": remote,
            "status": status,  # "broadcast" | "skipped" | "duplicate" | "rejected" | "error"
            "detail": detail,
            "headers": headers,
            "payload": payload,
        }
    )


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
    url = (db_url.value.strip() if db_url is not None else None) or xml.url
    key = (db_key.value.strip() if db_key is not None else None) or xml.api_key
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
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Octopus server not configured"
        )
    params = {"api_key": key} if key else {}
    async with _client() as client:
        # Try the client API first; fall back to admin list if auth is required
        for endpoint in (f"{url}/api/client/streams", f"{url}/api/streams"):
            try:
                r = await client.get(endpoint, params=params)
                if r.status_code in (401, 403) and "client" in endpoint:
                    continue  # no key configured — try admin endpoint
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403) and "client" in endpoint:
                    continue
                raise HTTPException(
                    exc.response.status_code,
                    f"Octopus error: {exc.response.text[:200]}",
                )
            except httpx.RequestError as exc:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, f"Cannot reach Octopus: {exc}"
                )
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Cannot list Octopus streams")


# ── Stream detail ─────────────────────────────────────────────────────────────


@router.get("/streams/{stream_id}")
async def get_octopus_stream(
    stream_id: str,
    _: Operator = Depends(get_current_operator),
) -> dict:
    url, key = _cfg()
    if not url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Octopus server not configured"
        )
    from urllib.parse import urlparse as _urlparse

    async def _fetch_stream_data(client: httpx.AsyncClient) -> dict:
        """Return stream detail dict from Octopus.

        Strategy:
        1. Try /api/client/streams/{id} — authenticated, returns absolute hls_url.
        2. On 401/403/404 try admin /api/streams/{id} directly (no auth).
        3. Last resort: fetch full admin list and match by name or UUID.
        """
        params = {"api_key": key} if key else {}

        # 1. Client API (needs valid API key + stream access grant)
        try:
            r = await client.get(f"{url}/api/client/streams/{stream_id}", params=params)
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (401, 403, 404):
                r.raise_for_status()
        except httpx.HTTPStatusError, httpx.RequestError:
            pass

        # 2. Admin detail endpoint — fast O(1) lookup, no auth required
        try:
            r = await client.get(f"{url}/api/streams/{stream_id}", params=params)
            if r.status_code == 200:
                return r.json()
        except httpx.HTTPStatusError, httpx.RequestError:
            pass

        # 3. Admin list + match by name (stream_id may be a human name, not UUID)
        try:
            r = await client.get(f"{url}/api/streams", params=params)
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                exc.response.status_code, f"Octopus error: {exc.response.text[:200]}"
            )
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Cannot reach Octopus: {exc}"
            )
        body = r.json()
        streams = body if isinstance(body, list) else []
        match = next((s for s in streams if s.get("name") == stream_id), None)
        if match is None:
            match = next((s for s in streams if s.get("id") == stream_id), None)
        if match is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Stream {stream_id!r} not found in Octopus"
            )

        # Try to fetch richer detail by UUID if we only have the list entry
        uuid = match.get("id", "")
        if uuid and uuid != stream_id:
            try:
                r2 = await client.get(f"{url}/api/streams/{uuid}", params=params)
                if r2.status_code == 200:
                    return r2.json()
            except httpx.HTTPStatusError, httpx.RequestError:
                pass
        return match

    async with _client() as client:
        data = await _fetch_stream_data(client)

    # Normalise hls_url to an Arrow-relative proxy path.
    # Octopus admin API: hls_url is relative ("/static/hls/UUID/live.m3u8") or None.
    # Octopus client API: hls_url is absolute ("http://host/static/hls/UUID/live.m3u8").
    # When hls_url is None but the stream is active, synthesise the canonical path —
    # this matches what Octopus client API does when the transcoder is still starting.
    raw_hls = (
        data.get("hls_url") or data.get("stream_url") or data.get("playback_url") or ""
    )
    if not raw_hls:
        stream_uuid = data.get("id", "")
        is_active = (
            data.get("is_active")
            or data.get("active")
            or data.get("status") == "active"
        )
        if is_active and stream_uuid:
            raw_hls = f"/static/hls/{stream_uuid}/live.m3u8"
            log.debug(
                "stream detail: synthesised canonical hls path for active stream %s",
                stream_uuid,
            )

    if raw_hls:
        if raw_hls.startswith(("http://", "https://")):
            oct_path = _urlparse(raw_hls).path.lstrip("/")
        else:
            oct_path = raw_hls.lstrip("/")
        data["hls_url"] = f"/octopus/hls/{oct_path}"
        data["octopus_hls_url"] = f"{url}/{oct_path}"  # absolute for debug bar
    else:
        data["hls_url"] = ""
        data["octopus_hls_url"] = ""

    log.debug(
        "stream detail: id=%s hls_url=%r octopus_hls_url=%r",
        stream_id,
        data["hls_url"],
        data["octopus_hls_url"],
    )
    return data


# ── HLS proxy ─────────────────────────────────────────────────────────────────

import re as _re


def _rewrite_m3u8(content: bytes, octopus_base: str) -> bytes:
    """Rewrite Octopus URLs in an HLS playlist to route through Arrow's proxy.

    Rewrites to /api/octopus/hls/<path> so the Flask reverse-proxy routes to
    the FastAPI backend.  Three forms are handled:

    1. Full absolute URL segments:  http://octopus/static/hls/UUID/seg.ts
    2. Absolute-path segments:      /static/hls/UUID/seg.ts
    3. URI= attributes (both forms): URI="http://octopus/..." or URI="/path/..."

    Relative segment references (e.g. "seg0001.ts") are left unchanged —
    hls.js resolves them relative to the proxied playlist URL, which is
    already routed through Arrow.
    """
    text = content.decode("utf-8", errors="replace")

    # 1. Rewrite URI="http://octopus-base/..." attributes
    def _rewrite_uri_abs(m: _re.Match) -> str:
        path = m.group(1)[len(octopus_base) :].lstrip("/")
        return f'URI="/api/octopus/hls/{path}"'

    text = _re.sub(
        r'URI="(' + _re.escape(octopus_base) + r'[^"]*)"',
        _rewrite_uri_abs,
        text,
    )

    # 2. Rewrite URI="/absolute-path/..." attributes
    text = _re.sub(
        r'URI="(/[^"]*)"',
        lambda m: f'URI="/api/octopus/hls{m.group(1)}"',
        text,
    )

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(octopus_base):
            # Full absolute URL segment line
            path = stripped[len(octopus_base) :].lstrip("/")
            line = f"/api/octopus/hls/{path}"
        elif stripped.startswith("/") and not stripped.startswith("#"):
            # Absolute-path segment line (e.g. /static/hls/UUID/seg.ts)
            line = f"/api/octopus/hls{stripped}"
        lines.append(line)
    return "\n".join(lines).encode("utf-8")


@router.get("/hls/{path:path}")
async def hls_proxy(path: str) -> Response:
    """Proxy Octopus HLS playlists and segments through Arrow.

    `path` is the exact Octopus URL path (e.g. static/hls/UUID/live.m3u8).
    No JWT — stream UUIDs are unguessable and short-lived.
    Absolute segment URLs in .m3u8 playlists are rewritten to Arrow-relative
    paths so the browser never contacts the Octopus host directly.
    """
    oct_url, key = _cfg()
    if not oct_url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Octopus not configured"
        )

    candidate = f"{oct_url}/{path}"
    params = {"api_key": key} if key else {}

    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        try:
            resp = await client.get(candidate, params=params)
        except httpx.RequestError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Cannot reach Octopus: {exc}"
            )

    if resp.status_code != 200:
        log.warning("hls_proxy: %s → %d", candidate, resp.status_code)
        raise HTTPException(
            resp.status_code, f"Octopus returned {resp.status_code} for {candidate}"
        )

    log.debug("hls_proxy: %s → 200", candidate)

    if path.endswith(".m3u8"):
        content = _rewrite_m3u8(resp.content, oct_url)
        media_type = "application/vnd.apple.mpegurl"
    elif path.endswith((".mp4", ".m4s")):
        content = resp.content
        media_type = "video/mp4"
    elif path.endswith(".ts"):
        content = resp.content
        media_type = "video/mp2t"
    else:
        content = resp.content
        media_type = resp.headers.get("content-type", "application/octet-stream")

    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )


# ── HLS connectivity diagnostic ──────────────────────────────────────────────


@router.get("/hls-test")
async def hls_test(_: Operator = Depends(get_current_operator)) -> Response:
    """Fetch the first available HLS stream from Octopus and return the raw
    playlist with diagnostic headers — open in browser to check connectivity."""
    oct_url, key = _cfg()
    if not oct_url:
        return Response(
            "ERROR: Octopus not configured (no URL in config.xml or DB)",
            media_type="text/plain",
            status_code=503,
        )
    params = {"api_key": key} if key else {}
    async with _client() as client:
        # 1. List streams
        streams = []
        for ep in (f"{oct_url}/api/client/streams", f"{oct_url}/api/streams"):
            try:
                r = await client.get(ep, params=params)
                if r.status_code == 200:
                    streams = r.json()
                    break
            except Exception:
                pass
        if not streams:
            return Response(
                f"ERROR: Could not list streams from {oct_url}",
                media_type="text/plain",
                status_code=502,
            )

        # 2. Pick first stream with an HLS URL
        hls_path = ""
        for s in (streams if isinstance(streams, list) else []):
            raw = s.get("hls_url") or s.get("stream_url") or ""
            if raw:
                from urllib.parse import urlparse as _up

                hls_path = (
                    _up(raw).path.lstrip("/")
                    if raw.startswith("http")
                    else raw.lstrip("/")
                )
                break
        if not hls_path:
            return Response(
                f"ERROR: No hls_url found in any stream.\n\nStreams: {streams}",
                media_type="text/plain",
                status_code=404,
            )

        # 3. Fetch the manifest
        m3u8_url = f"{oct_url}/{hls_path}"
        try:
            r = await client.get(m3u8_url, params=params)
        except Exception as exc:
            return Response(
                f"ERROR: Cannot reach {m3u8_url}\n{exc}",
                media_type="text/plain",
                status_code=502,
            )
        if r.status_code != 200:
            return Response(
                f"ERROR: {m3u8_url} returned HTTP {r.status_code}\n{r.text[:500]}",
                media_type="text/plain",
                status_code=r.status_code,
            )

        rewritten = _rewrite_m3u8(r.content, oct_url).decode("utf-8", errors="replace")
        body = (
            f"# Arrow HLS connectivity test — OK\n"
            f"# Octopus URL : {oct_url}\n"
            f"# Manifest    : {m3u8_url}\n"
            f"# Proxy path  : /api/octopus/hls/{hls_path}\n"
            f"# ─────────────────────────────────────\n"
            f"{rewritten}"
        )
        return Response(
            body, media_type="text/plain", headers={"Cache-Control": "no-cache"}
        )


# ── Add Octopus stream as persistent external stream ─────────────────────────


class _AddBody(BaseModel):
    name: str
    url: str
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
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"stream_type must be one of: {', '.join(sorted(_VALID))}",
        )
    row = ExternalStream(
        name=body.name.strip(),
        url=body.url.strip(),
        stream_type=body.stream_type,
        description=body.description.strip() or f"Octopus stream {stream_id}",
        added_by=current.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "stream_type": row.stream_type,
    }


# ── Webhook receiver (called by Octopus, no JWT auth) ─────────────────────────


@router.get("/webhook")
async def webhook_health() -> dict:
    """Reachability probe — Octopus or admin can GET this to confirm the endpoint is alive."""
    url, key = _cfg()
    return {
        "ok": True,
        "endpoint": "ready",
        "signature": "required" if key else "disabled",
        "octopus_url": url or None,
    }


def _verify_sig(body: bytes, header: str, key: str) -> bool:
    expected = "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def octopus_webhook(request: Request) -> dict:
    import uuid as _uuid

    remote = request.client.host if request.client else "unknown"
    body = await request.body()
    _, key = _cfg()

    sig = request.headers.get("X-Octopus-Signature", "")
    if key:
        # Dump every header so we can see what Octopus actually sends
        all_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("authorization", "cookie")
        }
        sig_candidates = {
            k: v
            for k, v in request.headers.items()
            if "sig" in k.lower() or "hmac" in k.lower() or "token" in k.lower()
        }

        if not sig:
            detail = (
                f"Missing X-Octopus-Signature header. "
                f"Signature-like headers present: {sig_candidates or 'none'}. "
                f"All headers: {all_headers}"
            )
            _log_webhook_call(
                remote=remote,
                status="rejected",
                detail=detail,
                payload=None,
                headers=all_headers,
            )
            log.warning(
                "Octopus webhook from %s: missing signature — rejected\n"
                "  Signature-like headers: %s\n"
                "  All request headers:    %s",
                remote,
                sig_candidates or "none",
                all_headers,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing signature")
        if not _verify_sig(body, sig, key):
            detail = f"Invalid HMAC signature. Received: {sig!r}"
            _log_webhook_call(
                remote=remote,
                status="rejected",
                detail=detail,
                payload=None,
                headers=all_headers,
            )
            log.warning(
                "Octopus webhook from %s: invalid HMAC — rejected. Received sig: %s",
                remote,
                sig,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    else:
        log.debug(
            "Octopus webhook from %s: no API key configured — accepting unsigned",
            remote,
        )

    try:
        det = json.loads(body)
    except Exception:
        _log_webhook_call(
            remote=remote, status="error", detail="Invalid JSON body", payload=None
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON")

    # Accept event type from any common field name Octopus might use
    event_val = next((det[k] for k in _EVENT_ALIASES if k in det), None)
    if event_val != "detection":
        payload_keys = list(det.keys())
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
            remote,
            _EVENT_ALIASES,
            payload_keys,
            payload_preview,
        )
        return {"ok": True, "skipped": True, "detail": detail}

    event_id = det.get("id") or str(_uuid.uuid4())
    stream_id = (
        det.get("stream_id", "") or det.get("stream", "") or det.get("camera_id", "")
    )
    label = det.get("label", "") or det.get("class", "") or det.get("category", "")
    confidence = float(
        det.get("confidence", 0) or det.get("score", 0) or det.get("prob", 0)
    )
    description = det.get("description", "") or det.get("message", "")
    bbox = json.dumps(
        det.get("bbox", []) or det.get("bounding_box", []) or det.get("box", [])
    )
    # Accept snapshot URL under any common field name
    _SNAP_ALIASES = (
        "snapshot_url",
        "snapshot",
        "image_url",
        "image",
        "frame_url",
        "frame",
        "thumbnail_url",
        "thumbnail",
        "photo_url",
        "photo",
    )
    snapshot = next((det[k] for k in _SNAP_ALIASES if det.get(k)), "")
    ts_raw = (
        det.get("timestamp", "") or det.get("time", "") or det.get("created_at", "")
    )
    try:
        occurred = datetime.fromisoformat(ts_raw).replace(tzinfo=timezone.utc)
    except Exception:
        occurred = datetime.now(timezone.utc)

    db = _db_session()
    try:
        # Deduplicate only when the sender supplied an explicit event_id
        if (
            det.get("id")
            and db.query(OctopusDetection)
            .filter(OctopusDetection.event_id == event_id)
            .first()
        ):
            _log_webhook_call(
                remote=remote,
                status="duplicate",
                detail=f"event_id={event_id} already in DB",
                payload=det,
            )
            return {"ok": True, "duplicate": True}

        row = OctopusDetection(
            event_id=event_id,
            stream_id=stream_id,
            label=label,
            confidence=confidence,
            description=description,
            bbox=bbox,
            snapshot_url=snapshot,
            occurred_at=occurred,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        det_id = row.id
    except Exception as exc:
        _log_webhook_call(
            remote=remote, status="error", detail=f"DB error: {exc}", payload=det
        )
        log.exception("Octopus webhook DB error")
        raise
    finally:
        db.close()

    await broadcaster.broadcast(
        {
            "channel": "octopus-detection",
            "event": "detection",
            "data": {
                "id": det_id,
                "event_id": event_id,
                "stream_id": stream_id,
                "label": label,
                "confidence": confidence,
                "description": description,
                "bbox": det.get("bbox", []),
                "snapshot_url": f"/octopus/detections/{det_id}/snapshot",
                "occurred_at": occurred.isoformat(),
            },
        }
    )
    _log_webhook_call(
        remote=remote,
        status="broadcast",
        detail=f"label={label} conf={confidence:.0%} stream={stream_id}",
        payload=det,
    )
    log.info(
        "Octopus detection: %s (%.0f%%) on stream %s",
        label,
        confidence * 100,
        stream_id,
    )
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
    rows = (
        db.query(OctopusDetection)
        .order_by(OctopusDetection.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "stream_id": r.stream_id,
            "label": r.label,
            "confidence": r.confidence,
            "description": r.description,
            "bbox": json.loads(r.bbox or "[]"),
            "snapshot_url": f"/octopus/detections/{r.id}/snapshot",
            "raw_snapshot_url": r.snapshot_url,  # what Octopus actually sent
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
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
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    base_url, key = _cfg()
    params = {"api_key": key} if key else {}

    log.debug(
        "snapshot: det=%d stored_url=%r stream=%r octopus_base=%r",
        detection_id,
        row.snapshot_url,
        row.stream_id,
        base_url,
    )

    async with _client() as client:
        # 1. Use stored snapshot URL if available
        if row.snapshot_url:
            snap = row.snapshot_url
            if snap.startswith("/"):
                snap = base_url + snap
            try:
                r = await client.get(snap, params=params)
                log.debug("snapshot: stored_url=%r → HTTP %d", snap, r.status_code)
                if r.status_code == 200 and r.content:
                    return Response(
                        content=r.content,
                        media_type=r.headers.get("content-type", "image/jpeg"),
                    )
            except Exception as exc:
                log.warning("snapshot: stored_url=%r failed: %s", snap, exc)

        # 2. Fall back: grab a live frame from the Octopus stream
        if row.stream_id and base_url:
            for frame_path in (
                f"/api/client/streams/{row.stream_id}/snapshot",
                f"/api/client/streams/{row.stream_id}/frame",
                f"/static/snapshots/{row.stream_id}/latest.jpg",
                f"/static/snapshots/{row.stream_id}.jpg",
            ):
                full = base_url + frame_path
                try:
                    r = await client.get(full, params=params)
                    log.debug(
                        "snapshot: fallback %r → HTTP %d content=%d bytes",
                        full,
                        r.status_code,
                        len(r.content),
                    )
                    if r.status_code == 200 and r.content:
                        return Response(
                            content=r.content,
                            media_type=r.headers.get("content-type", "image/jpeg"),
                        )
                except Exception as exc:
                    log.warning("snapshot: fallback %r failed: %s", full, exc)

    log.warning(
        "snapshot: det=%d — no image found. stored_url=%r stream=%r base=%r",
        detection_id,
        row.snapshot_url,
        row.stream_id,
        base_url,
    )
    raise HTTPException(status.HTTP_404_NOT_FOUND, "No snapshot available")
