"""KML layer import + listing endpoints.

Layers are parsed server-side once at upload time and stored as a JSON feature
collection (see :mod:`backend.kml.parser`). The same JSON is served to the web
map and the Android client so neither needs an XML parser.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_operator
from backend.auth.jwt_auth import require_role
from backend.kml.parser import KmlParseError, parse_kml
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import KmlLayer, Mission, Operator
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/kml-layers", tags=["kml"])

# 20 MB cap — keeps a single rogue upload from blowing through the per-request
# memory budget. A tactical AO worth of
# placemarks is typically a few hundred kilobytes; 20 MB covers everything
# short of nation-scale gazetteers.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class KmlLayerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    visible: bool
    uploaded_by: int
    uploaded_at: datetime
    feature_count: int
    bbox: list[float] | None = None
    classification: int = 0
    mission_id: int | None = None


class KmlLayerOut(KmlLayerSummary):
    features: list[dict]


class KmlLayerPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    visible: bool | None = None
    classification: int | None = None


def _to_summary(row: KmlLayer) -> KmlLayerSummary:
    bbox_list: list[float] | None = None
    if row.bbox:
        try:
            bbox_list = [float(x) for x in row.bbox.split(",")]
            if len(bbox_list) != 4:
                bbox_list = None
        except ValueError:
            bbox_list = None
    return KmlLayerSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        visible=row.visible,
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
        feature_count=row.feature_count,
        bbox=bbox_list,
        classification=row.classification,
        mission_id=row.mission_id,
    )


@router.get("", response_model=list[KmlLayerSummary])
def list_layers(
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> list[KmlLayerSummary]:
    rows = (
        db.query(KmlLayer)
        .filter(KmlLayer.classification <= current.clearance)
        .order_by(KmlLayer.uploaded_at.desc())
        .all()
    )
    return [_to_summary(r) for r in rows]


@router.get("/{layer_id}", response_model=KmlLayerOut)
def get_layer(
    layer_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> KmlLayerOut:
    from backend.classification import can_see

    row = db.get(KmlLayer, layer_id)
    if row is None or not can_see(row.classification, current.clearance):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown layer")
    summary = _to_summary(row)
    try:
        features = json.loads(row.features) if row.features else []
    except json.JSONDecodeError:
        features = []
    return KmlLayerOut(**summary.model_dump(), features=features)


@router.get("/{layer_id}/kml")
def download_kml(
    layer_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Response:
    """Return the original KML XML so an operator can re-import it elsewhere."""
    row = db.get(KmlLayer, layer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown layer")
    return Response(
        content=row.raw_kml,
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": f'attachment; filename="{row.name}.kml"'},
    )


@router.post("", response_model=KmlLayerOut, status_code=status.HTTP_201_CREATED)
async def upload_layer(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> KmlLayerOut:
    filename = (file.filename or "layer.kml").strip() or "layer.kml"
    lower = filename.lower()
    if not (lower.endswith(".kml") or lower.endswith(".kmz")):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Filename must end in .kml or .kmz"
        )

    # Stream-read with a hard cap so a multi-GB upload can't OOM the worker.
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"File exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty upload body")
    data = b"".join(chunks)

    try:
        features, bbox = parse_kml(data)
    except KmlParseError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if not features:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "KML contains no recognisable Placemarks"
        )

    # Derive a human name from the filename stem. Operators can rename it
    # afterwards via PATCH if the auto-name is ugly.
    stem = filename.rsplit(".", 1)[0] or "layer"

    # Keep raw_kml only for genuine .kml uploads — a KMZ ships its own assets
    # so re-serving the raw bytes wouldn't round-trip cleanly anyway. Storing
    # the decompressed XML in that case keeps the download endpoint useful.
    raw_xml = data
    if lower.endswith(".kmz"):
        from backend.kml.parser import _read_kml_bytes  # noqa: PLC0415

        try:
            raw_xml = _read_kml_bytes(data)
        except KmlParseError:
            raw_xml = b""

    from backend.classification import resolve_default_and_cap

    layer = KmlLayer(
        name=stem,
        uploaded_by=current.id,
        feature_count=len(features),
        features=json.dumps(features, separators=(",", ":")),
        bbox=",".join(f"{v:.6f}" for v in bbox) if bbox else "",
        raw_kml=raw_xml.decode("utf-8", errors="replace"),
        mission_id=mission.id if mission else None,
        classification=resolve_default_and_cap(mission, current, None),
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)

    summary = _to_summary(layer)
    await broadcaster.broadcast(
        {
            "channel": "kml-layer",
            "event": "created",
            "data": summary.model_dump(mode="json"),
        }
    )
    return KmlLayerOut(**summary.model_dump(), features=features)


@router.patch("/{layer_id}", response_model=KmlLayerSummary)
async def patch_layer(
    layer_id: int,
    patch: KmlLayerPatch,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> KmlLayerSummary:
    row = db.get(KmlLayer, layer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown layer")
    if patch.name is not None:
        row.name = patch.name.strip() or row.name
    if patch.description is not None:
        row.description = patch.description
    if patch.visible is not None:
        row.visible = patch.visible
    db.commit()
    db.refresh(row)
    summary = _to_summary(row)
    await broadcaster.broadcast(
        {
            "channel": "kml-layer",
            "event": "updated",
            "data": summary.model_dump(mode="json"),
        }
    )
    return summary


@router.delete("/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layer(
    layer_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> Response:
    row = db.get(KmlLayer, layer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown layer")
    db.delete(row)
    db.commit()
    await broadcaster.broadcast(
        {
            "channel": "kml-layer",
            "event": "deleted",
            "data": {"id": layer_id},
        }
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
