"""Photo upload/serve with optional AES-256-GCM encryption.

Set ARROW_PHOTO_KEY to a 32-byte hex string (64 hex chars) to enable
transparent encryption at rest.  Encrypted files get a `.enc` suffix.
Unencrypted files (uploaded before the key was set) are still served
without decryption, maintaining backward compatibility.

Generate a key:
    python -c "import os,sys; sys.stdout.write(os.urandom(32).hex())"
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.api.schemas import PhotoOut
from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import Operator, Photo

PHOTO_DIR = Path("data/photos")
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "video/mp4",
    "video/webm",
    "video/ogg",
    "video/quicktime",
}
MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/heic": "heic",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/ogg": "ogv",
    "video/quicktime": "mov",
}
_MAX_BYTES = {
    "image": 10 * 1024 * 1024,  # 10 MB
    "video": 200 * 1024 * 1024,  # 200 MB
}

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


# ── Shared binary store (used by /photos upload, the Marti sync API and the
#    ATAK CoT bridge) — one place that writes the encrypted file + Photo row. ──


def store_photo_bytes(
    db: Session, raw: bytes, mime: str, uploaded_by: int, original_name: str = "photo"
) -> Photo:
    """Persist binary image/video bytes to disk + a Photo row (with SHA-256).

    Records the plaintext SHA-256 so the file is retrievable by hash via the TAK
    Marti API. Inbound ATAK paths de-dupe via ``find_photo_by_hash`` before
    calling this; the regular upload endpoint always creates a distinct Photo.
    """
    sha = hashlib.sha256(raw).hexdigest()
    ext = MIME_TO_EXT.get(mime, "jpg")
    fname = f"{uuid.uuid4().hex}.{ext}" + (".enc" if _get_aesgcm() is not None else "")
    (PHOTO_DIR / fname).write_bytes(_encrypt(raw))

    photo = Photo(
        filename=fname,
        original_name=original_name or "photo",
        mime_type=mime,
        uploaded_by=uploaded_by,
        sha256=sha,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


def read_photo_bytes(photo: Photo) -> bytes | None:
    """Return the decrypted plaintext bytes for a stored Photo, or None."""
    path = PHOTO_DIR / photo.filename
    if not path.exists():
        return None
    raw = path.read_bytes()
    if photo.filename.endswith(".enc"):
        try:
            raw = _decrypt(raw)
        except Exception:
            return None
    return raw


def find_photo_by_hash(db: Session, sha256: str) -> Photo | None:
    return db.query(Photo).filter(Photo.sha256 == sha256).first()


def ensure_photo_hash(db: Session, photo: Photo) -> str | None:
    """Backfill sha256 for a legacy Photo (computed from its plaintext)."""
    if photo.sha256:
        return photo.sha256
    raw = read_photo_bytes(photo)
    if raw is None:
        return None
    photo.sha256 = hashlib.sha256(raw).hexdigest()
    db.commit()
    return photo.sha256


@router.get("")
def list_photos(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[dict]:
    """Index of every uploaded photo with metadata.

    Includes the originating message / report / tactical-object reference so
    the History → Photos browser can deep-link back into context.
    """
    from backend.storage.models import Message, Report, TacticalObject

    rows = db.query(Photo).order_by(Photo.timestamp.desc()).all()
    photos: list[dict] = []
    for p in rows:
        msg_id = db.query(Message.id).filter(Message.photo_id == p.id).first()
        to_id = (
            db.query(TacticalObject.id).filter(TacticalObject.photo_id == p.id).first()
        )
        # Reports stash photo_id inside their JSON payload — index by id substring
        rep_id = None
        like = f'%"photo_id": {p.id}%'
        rep_row = db.query(Report.id).filter(Report.payload.like(like)).first()
        if rep_row:
            rep_id = rep_row[0]
        photos.append(
            {
                "id": p.id,
                "filename": p.filename,
                "original_name": p.original_name,
                "mime_type": p.mime_type,
                "uploaded_by": p.uploaded_by,
                "timestamp": p.timestamp.isoformat() if p.timestamp else None,
                "url": f"/photos/{p.id}",
                "message_id": msg_id[0] if msg_id else None,
                "tactical_object_id": to_id[0] if to_id else None,
                "report_id": rep_id,
            }
        )
    return photos


@router.post("", response_model=PhotoOut, status_code=status.HTTP_201_CREATED)
async def upload_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> PhotoOut:
    mime = (file.content_type or "").split(";")[0].strip()
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported media type: {mime}"
        )

    raw = await file.read()
    media_cat = mime.split("/")[0]
    limit = _MAX_BYTES.get(media_cat, 10 * 1024 * 1024)
    if len(raw) > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File too large (max {limit // (1024 * 1024)} MB for {media_cat})",
        )

    photo = store_photo_bytes(
        db, raw, mime, uploaded_by=current.id, original_name=file.filename or "photo"
    )
    return PhotoOut(id=photo.id, url=f"/photos/{photo.id}")


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> None:
    photo = db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if photo.uploaded_by != current.id and current.role not in (
        "ADMIN",
        "BATTLE_CAPTAIN",
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your photo")
    path = PHOTO_DIR / photo.filename
    if path.exists():
        path.unlink()
    db.delete(photo)
    db.commit()


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
