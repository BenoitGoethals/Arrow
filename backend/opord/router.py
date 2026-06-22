"""OPORD CRUD + snapshot capture + PDF export + send-to-operator."""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.audit import log_event
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.opord.pdf import PHOTO_DIR, render_opord_pdf
from backend.opord.schemas import (
    MapSnapshotIn,
    MapSnapshotRenderIn,
    OpordCreate,
    OpordOut,
    OpordSendIn,
    OpordUpdate,
)
from backend.opord.tiles import render_snapshot_png
from backend.storage.database import get_db
from backend.storage.models import Operator, Opord, Photo
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/opord", tags=["opord"])


def _to_out(o: Opord, db: Session) -> dict[str, Any]:
    snaps = json.loads(o.map_snapshots or "[]")
    return {
        "id": o.id,
        "title": o.title,
        "opord_number": o.opord_number,
        "dtg": o.dtg,
        "time_zone": o.time_zone,
        "classification": o.classification,
        "references": o.references,
        "task_organization": o.task_organization,
        "situation": json.loads(o.situation or "{}"),
        "mission": o.mission,
        "execution": json.loads(o.execution or "{}"),
        "sustainment": json.loads(o.sustainment or "{}"),
        "command_signal": json.loads(o.command_signal or "{}"),
        "map_snapshots": snaps,
        "battle_id": o.battle_id,
        "status": o.status,
        "author_id": o.author_id,
        "recipient_ids": json.loads(o.recipient_ids or "[]"),
        "created_at": o.created_at,
        "updated_at": o.updated_at,
    }


def _apply(o: Opord, payload: OpordCreate | OpordUpdate) -> None:
    o.title = payload.title
    o.opord_number = payload.opord_number
    o.dtg = payload.dtg
    o.time_zone = payload.time_zone
    o.classification = payload.classification
    o.references = payload.references
    o.task_organization = payload.task_organization
    o.situation = json.dumps(payload.situation)
    o.mission = payload.mission
    o.execution = json.dumps(payload.execution)
    o.sustainment = json.dumps(payload.sustainment)
    o.command_signal = json.dumps(payload.command_signal)
    o.battle_id = payload.battle_id


@router.get("", response_model=list[OpordOut])
def list_opords(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    rows = db.query(Opord).order_by(Opord.updated_at.desc()).limit(200).all()
    return [_to_out(o, db) for o in rows]


@router.get("/{opord_id}", response_model=OpordOut)
def get_opord(
    opord_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return _to_out(o, db)


@router.post("", response_model=OpordOut, status_code=status.HTTP_201_CREATED)
def create_opord(
    payload: OpordCreate,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    o = Opord(author_id=current.id, status="DRAFT")
    _apply(o, payload)
    db.add(o)
    db.commit()
    db.refresh(o)
    log_event(
        db,
        "OPORD_CREATE",
        operator_id=current.id,
        resource=f"opord:{o.id}",
        detail=o.title[:80],
    )
    return _to_out(o, db)


@router.put("/{opord_id}", response_model=OpordOut)
def update_opord(
    opord_id: int,
    payload: OpordUpdate,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _apply(o, payload)
    db.commit()
    db.refresh(o)
    return _to_out(o, db)


@router.delete("/{opord_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opord(
    opord_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN")),
):
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.delete(o)
    db.commit()
    log_event(db, "OPORD_DELETE", operator_id=current.id, resource=f"opord:{opord_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{opord_id}/snapshots", response_model=OpordOut)
def add_snapshot(
    opord_id: int,
    payload: MapSnapshotIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    """Decode the base64 PNG, persist it via the photos table, append a snapshot entry."""
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    raw_b64 = payload.image_b64
    if "," in raw_b64:  # tolerate data URL prefix
        raw_b64 = raw_b64.split(",", 1)[1]
    try:
        png = base64.b64decode(raw_b64, validate=False)
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid image_b64")
    if len(png) > 8 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Snapshot too large"
        )

    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"opord_{o.id}_{uuid.uuid4().hex}.png"
    (PHOTO_DIR / filename).write_bytes(png)

    photo = Photo(
        filename=filename,
        original_name=f"{payload.label or 'snapshot'}.png",
        mime_type="image/png",
        uploaded_by=current.id,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    snaps = json.loads(o.map_snapshots or "[]")
    next_id = (max((s.get("id", 0) for s in snaps), default=0)) + 1
    snaps.append(
        {
            "id": next_id,
            "label": payload.label,
            "bbox": payload.bbox,
            "center": payload.center,
            "zoom": payload.zoom,
            "photo_id": photo.id,
            "annotations": payload.annotations,
        }
    )
    o.map_snapshots = json.dumps(snaps)
    db.commit()
    db.refresh(o)
    return _to_out(o, db)


@router.post("/{opord_id}/snapshots/render", response_model=OpordOut)
def render_snapshot(
    opord_id: int,
    payload: MapSnapshotRenderIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    """Server-side snapshot: stitch OSM tiles for ``bbox`` at ``zoom`` and store as PNG."""
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    try:
        png = render_snapshot_png(payload.bbox, payload.zoom, db=db)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Tile render failed: {exc}")

    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"opord_{o.id}_{uuid.uuid4().hex}.png"
    (PHOTO_DIR / filename).write_bytes(png)
    photo = Photo(
        filename=filename,
        original_name=f"{payload.label or 'snapshot'}.png",
        mime_type="image/png",
        uploaded_by=current.id,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    snaps = json.loads(o.map_snapshots or "[]")
    next_id = (max((s.get("id", 0) for s in snaps), default=0)) + 1
    s, w, n, e = payload.bbox
    snaps.append(
        {
            "id": next_id,
            "label": payload.label,
            "bbox": payload.bbox,
            "center": [(s + n) / 2, (w + e) / 2],
            "zoom": payload.zoom,
            "photo_id": photo.id,
            "annotations": payload.annotations,
        }
    )
    o.map_snapshots = json.dumps(snaps)
    db.commit()
    db.refresh(o)
    return _to_out(o, db)


@router.delete("/{opord_id}/snapshots/{snap_id}", response_model=OpordOut)
def delete_snapshot(
    opord_id: int,
    snap_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    snaps = [s for s in json.loads(o.map_snapshots or "[]") if s.get("id") != snap_id]
    o.map_snapshots = json.dumps(snaps)
    db.commit()
    db.refresh(o)
    return _to_out(o, db)


@router.post("/{opord_id}/publish", response_model=OpordOut)
async def publish_opord(
    opord_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    o.status = "PUBLISHED"
    db.commit()
    db.refresh(o)
    await broadcaster.broadcast(
        {
            "channel": "opord",
            "event": "published",
            "data": {
                "id": o.id,
                "title": o.title,
                "author_id": o.author_id,
                "recipient_ids": json.loads(o.recipient_ids or "[]"),
            },
        }
    )
    log_event(db, "OPORD_PUBLISH", operator_id=current.id, resource=f"opord:{o.id}")
    return _to_out(o, db)


@router.post("/{opord_id}/send", response_model=OpordOut)
async def send_opord(
    opord_id: int,
    payload: OpordSendIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
):
    """Distribute an OPORD to specific operators (Android picks it up via WS)."""
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    existing = set(json.loads(o.recipient_ids or "[]"))
    existing.update(payload.operator_ids)
    o.recipient_ids = json.dumps(sorted(existing))
    if o.status != "PUBLISHED":
        o.status = "PUBLISHED"
    db.commit()
    db.refresh(o)
    await broadcaster.broadcast(
        {
            "channel": "opord",
            "event": "sent",
            "data": {
                "id": o.id,
                "title": o.title,
                "author_id": o.author_id,
                "recipient_ids": payload.operator_ids,
                "from": current.callsign,
            },
        }
    )
    log_event(
        db,
        "OPORD_SEND",
        operator_id=current.id,
        resource=f"opord:{o.id}",
        detail=f"to:{payload.operator_ids}",
    )
    return _to_out(o, db)


@router.get("/{opord_id}/pdf")
def export_pdf(
    opord_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    o = db.get(Opord, opord_id)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    snaps = json.loads(o.map_snapshots or "[]")
    photo_ids = [s.get("photo_id") for s in snaps if s.get("photo_id")]
    photos: dict[int, Photo] = {}
    if photo_ids:
        for p in db.query(Photo).filter(Photo.id.in_(photo_ids)).all():
            photos[p.id] = p
    pdf_bytes = render_opord_pdf(o, photos)
    safe_title = (
        "".join(c if c.isalnum() or c in "-_" else "_" for c in o.title)[:60] or "opord"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_title}.pdf"'},
    )
