"""Saved overlays — named bundles of TacticalObject ids."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_operator
from backend.auth.jwt_auth import require_role
from backend.storage.database import get_db
from backend.storage.models import Operator, Overlay, TacticalObject
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/overlays", tags=["overlays"])


class OverlayIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    description: str = ""
    object_ids: list[int] = Field(default_factory=list)


class OverlayPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    object_ids: list[int] | None = None


class OverlayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    created_by: int
    created_at: datetime
    updated_at: datetime
    object_ids: list[int]


def _to_out(row: Overlay) -> OverlayOut:
    try:
        ids = json.loads(row.object_ids) if row.object_ids else []
        if not isinstance(ids, list):
            ids = []
        ids = [int(x) for x in ids]
    except json.JSONDecodeError, ValueError, TypeError:
        ids = []
    return OverlayOut(
        id=row.id,
        name=row.name,
        description=row.description,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        object_ids=ids,
    )


def _validate_ids(db: Session, ids: list[int]) -> list[int]:
    """Drop ids that don't match a real TacticalObject.

    Done permissively rather than 400-ing the whole request: operators can save
    an overlay that includes objects they don't have visibility for at the time
    of save, but stale ids accumulate as the BC reshapes the map. Filtering on
    save keeps the persisted set clean without making the UI brittle.
    """
    if not ids:
        return []
    rows = db.query(TacticalObject.id).filter(TacticalObject.id.in_(ids)).all()
    found = {r[0] for r in rows}
    return [i for i in ids if i in found]


@router.get("", response_model=list[OverlayOut])
def list_overlays(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[OverlayOut]:
    rows = db.query(Overlay).order_by(Overlay.updated_at.desc()).all()
    return [_to_out(r) for r in rows]


@router.get("/{overlay_id}", response_model=OverlayOut)
def get_overlay(
    overlay_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> OverlayOut:
    row = db.get(Overlay, overlay_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown overlay")
    return _to_out(row)


@router.post("", response_model=OverlayOut, status_code=status.HTTP_201_CREATED)
async def create_overlay(
    payload: OverlayIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> OverlayOut:
    ids = _validate_ids(db, payload.object_ids)
    row = Overlay(
        name=payload.name.strip(),
        description=payload.description,
        created_by=current.id,
        object_ids=json.dumps(ids, separators=(",", ":")),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = _to_out(row)
    await broadcaster.broadcast(
        {
            "channel": "overlay",
            "event": "created",
            "data": out.model_dump(mode="json"),
        }
    )
    return out


@router.patch("/{overlay_id}", response_model=OverlayOut)
async def patch_overlay(
    overlay_id: int,
    patch: OverlayPatch,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> OverlayOut:
    row = db.get(Overlay, overlay_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown overlay")
    if patch.name is not None:
        name = patch.name.strip()
        if name:
            row.name = name
    if patch.description is not None:
        row.description = patch.description
    if patch.object_ids is not None:
        ids = _validate_ids(db, patch.object_ids)
        row.object_ids = json.dumps(ids, separators=(",", ":"))
    db.commit()
    db.refresh(row)
    out = _to_out(row)
    await broadcaster.broadcast(
        {
            "channel": "overlay",
            "event": "updated",
            "data": out.model_dump(mode="json"),
        }
    )
    return out


@router.delete("/{overlay_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_overlay(
    overlay_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Response:
    row = db.get(Overlay, overlay_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown overlay")
    db.delete(row)
    db.commit()
    await broadcaster.broadcast(
        {
            "channel": "overlay",
            "event": "deleted",
            "data": {"id": overlay_id},
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
