"""Minimal TAK Marti file-sharing (sync) API for binary photo transfer to/from ATAK.

ATAK transfers attachments/files as **binary** over HTTP using the TAK Server
"Marti sync" endpoints (not base64-in-CoT). This router implements the subset
Arrow needs so an ATAK device can:

  • upload a file   → POST /Marti/sync/missionupload   (binary body or multipart)
  • download a file → GET  /Marti/sync/content?hash=…  (raw binary)

Files are stored in the same central photo store as web/front/android uploads
(``backend.photos.router.store_photo_bytes`` → ``data/photos`` + a Photo row),
so every source lands in one place and is served by hash.

⚠️ These endpoints are intentionally **unauthenticated** — ATAK authenticates
over its TAK connection, not with an Arrow JWT, so it cannot send a Bearer token.
Only the file *bytes* are reachable, and only if the caller already knows the
SHA-256. Restrict exposure of this path at the reverse proxy / firewall to the
TAK network. Set ARROW_MARTI_DISABLED=1 to turn the API off entirely.

The exact endpoint paths/params vary slightly across TAK Server / ATAK versions —
validate against the build you field.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.photos.router import (
    find_photo_by_hash,
    read_photo_bytes,
    store_photo_bytes,
)
from backend.storage.database import get_db
from backend.storage.models import Operator

router = APIRouter(prefix="/Marti", tags=["marti"])


def marti_base_url() -> str:
    """Absolute base URL ATAK uses to reach this server's Marti API.

    Set ARROW_MARTI_URL to the device-reachable URL (e.g. http://78.21.255.210:6001).
    """
    return (
        os.environ.get("ARROW_MARTI_URL")
        or os.environ.get("ARROW_PUBLIC_BACKEND_URL")
        or "http://127.0.0.1:6001"
    ).rstrip("/")


def content_url(sha256: str) -> str:
    return f"{marti_base_url()}/Marti/sync/content?hash={sha256}"


def _enabled() -> bool:
    return os.environ.get("ARROW_MARTI_DISABLED", "") not in ("1", "true", "True")


def _fallback_operator_id(db: Session) -> int | None:
    op = db.query(Operator).order_by(Operator.id.asc()).first()
    return op.id if op else None


async def _read_upload_bytes(request: Request) -> tuple[bytes, str]:
    """Return (raw_bytes, mime). Accepts multipart (assetfile/file) or raw body."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        for key in ("assetfile", "file", "resource"):
            f = form.get(key)
            if f is not None and hasattr(f, "read"):
                return await f.read(), (
                    getattr(f, "content_type", None) or "image/jpeg"
                )
    body = await request.body()
    return body, (ctype.split(";")[0].strip() or "application/octet-stream")


@router.post("/sync/missionupload")
@router.post("/sync/upload")
async def sync_upload(
    request: Request,
    db: Session = Depends(get_db),
    hash: str | None = None,
    filename: str | None = None,
    name: str | None = None,
    creatorUid: str | None = None,  # noqa: N803 — TAK param name
):
    """Store an uploaded file; return its content URL (TAK clients expect the URL)."""
    if not _enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    raw, mime = await _read_upload_bytes(request)
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")
    uploader = _fallback_operator_id(db)
    if uploader is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "no operators to attribute upload"
        )
    if mime == "application/octet-stream" and (filename or name or "").lower().endswith(
        (".jpg", ".jpeg")
    ):
        mime = "image/jpeg"
    photo = store_photo_bytes(
        db,
        raw,
        mime,
        uploaded_by=uploader,
        original_name=name or filename or "atak-upload",
    )
    # TAK Server returns the content URL as plain text.
    return Response(content=content_url(photo.sha256 or ""), media_type="text/plain")


@router.get("/sync/content")
@router.head("/sync/content")
def sync_content(
    request: Request,
    db: Session = Depends(get_db),
    hash: str | None = None,
    uid: str | None = None,
):
    """Serve a stored file's raw binary by SHA-256 hash. No auth (TAK channel)."""
    if not _enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    sha = hash or uid
    if not sha:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "hash required")
    photo = find_photo_by_hash(db, sha)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if request.method == "HEAD":
        return Response(status_code=200, media_type=photo.mime_type)
    raw = read_photo_bytes(photo)
    if raw is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file missing on disk")
    return Response(content=raw, media_type=photo.mime_type)


@router.get("/sync/search")
def sync_search(
    db: Session = Depends(get_db),
    keywords: str | None = None,
    tool: str | None = None,
):
    """Minimal search response (ATAK probes this before download)."""
    return {"resultCount": 0, "results": []}
