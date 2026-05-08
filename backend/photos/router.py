"""Photo upload/serve with optional AES-256-GCM encryption.

Set ARROW_PHOTO_KEY to a 32-byte hex string (64 hex chars) to enable
transparent encryption at rest.  Encrypted files get a `.enc` suffix.
Unencrypted files (uploaded before the key was set) are still served
without decryption, maintaining backward compatibility.

Generate a key:
    python -c "import os,sys; sys.stdout.write(os.urandom(32).hex())"
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from backend.api.schemas import PhotoOut
from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import Operator, Photo

PHOTO_DIR = Path("data/photos")
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/heic"}
MIME_TO_EXT  = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
                "image/webp": "webp", "image/heic": "heic"}

router = APIRouter(prefix="/photos", tags=["photos"])


def _get_aesgcm():
    """Return an AESGCM cipher if ARROW_PHOTO_KEY is configured, else None."""
    raw = os.environ.get("ARROW_PHOTO_KEY", "")
    if len(raw) != 64:
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(bytes.fromhex(raw))


def _encrypt(data: bytes) -> bytes:
    """Encrypt with AES-256-GCM. Format: 12-byte nonce || ciphertext+tag."""
    aesgcm = _get_aesgcm()
    if aesgcm is None:
        return data
    nonce = os.urandom(12)
    return nonce + aesgcm.encrypt(nonce, data, None)


def _decrypt(data: bytes) -> bytes:
    """Decrypt AES-256-GCM blob; return raw bytes if not encrypted."""
    aesgcm = _get_aesgcm()
    if aesgcm is None:
        return data
    nonce, ct = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ct, None)


@router.post("", response_model=PhotoOut, status_code=status.HTTP_201_CREATED)
async def upload_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> PhotoOut:
    mime = (file.content_type or "").split(";")[0].strip()
    if mime not in ALLOWED_MIME:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"Unsupported image type: {mime}")

    raw  = await file.read()
    blob = _encrypt(raw)
    ext  = MIME_TO_EXT.get(mime, "jpg")
    encrypted = _get_aesgcm() is not None
    filename = f"{uuid.uuid4().hex}.{ext}" + (".enc" if encrypted else "")

    (PHOTO_DIR / filename).write_bytes(blob)

    photo = Photo(filename=filename, original_name=file.filename or "photo",
                  mime_type=mime, uploaded_by=current.id)
    db.add(photo); db.commit(); db.refresh(photo)
    return PhotoOut(id=photo.id, url=f"/photos/{photo.id}")


@router.get("/{photo_id}")
def serve_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Response:
    photo = db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    path = PHOTO_DIR / photo.filename
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing on disk")

    raw = path.read_bytes()
    if photo.filename.endswith(".enc"):
        try:
            raw = _decrypt(raw)
        except Exception:
            raise HTTPException(500, "Photo decryption failed — check ARROW_PHOTO_KEY")

    return Response(content=raw, media_type=photo.mime_type)
