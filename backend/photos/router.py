from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
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

    ext      = MIME_TO_EXT.get(mime, "jpg")
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest     = PHOTO_DIR / filename
    dest.write_bytes(await file.read())

    photo = Photo(
        filename=filename,
        original_name=file.filename or "photo",
        mime_type=mime,
        uploaded_by=current.id,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return PhotoOut(id=photo.id, url=f"/photos/{photo.id}")


@router.get("/{photo_id}")
def serve_photo(
    photo_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> FileResponse:
    photo = db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    path = PHOTO_DIR / photo.filename
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing on disk")
    return FileResponse(path, media_type=photo.mime_type)
