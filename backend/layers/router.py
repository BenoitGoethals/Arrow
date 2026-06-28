"""Standalone layer export/import — download a layer to a file, or import one
into the active mission. Per-kind CRUD stays in the overlays/kml/osint routers."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.schemas import TacticalObjectOut
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.layers import deserialize, serialize
from backend.layers.envelope import (
    LAYER_EXPORT_VERSION,
    VALID_KINDS,
    LayerEnvelope,
    make_envelope,
)
from backend.missions.dependencies import get_active_mission
from backend.overlays.router import _to_out as _overlay_to_out
from backend.storage.database import get_db
from backend.storage.models import (
    EpicProject,
    KmlLayer,
    Mission,
    Operator,
    Overlay,
    TacticalObject,
)
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/layers", tags=["layers"])


class LayerImportResult(BaseModel):
    kind: str
    id: int
    name: str


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60] or "layer"


def _download(envelope: dict, filename: str) -> JSONResponse:
    return JSONResponse(
        content=jsonable_encoder(envelope),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/overlays/{overlay_id}/export")
def export_overlay(
    overlay_id: int,
    db: Session = Depends(get_db),
    op: Operator = Depends(get_current_operator),
) -> JSONResponse:
    row = db.get(Overlay, overlay_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown overlay")
    env = make_envelope(
        "OVERLAY", row.name, op.id, serialize.serialize_overlay(db, row)
    )
    return _download(env, f"{_slug(row.name)}.overlay.json")


@router.get("/kml/{layer_id}/export")
def export_kml(
    layer_id: int,
    db: Session = Depends(get_db),
    op: Operator = Depends(get_current_operator),
) -> JSONResponse:
    row = db.get(KmlLayer, layer_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown layer")
    env = make_envelope("KML", row.name, op.id, serialize.serialize_kml(row))
    return _download(env, f"{_slug(row.name)}.kml-layer.json")


@router.get("/osint/{project_id}/export")
def export_osint(
    project_id: int,
    db: Session = Depends(get_db),
    op: Operator = Depends(get_current_operator),
) -> JSONResponse:
    row = db.get(EpicProject, project_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    env = make_envelope("OSINT", row.name, op.id, serialize.serialize_osint(db, row))
    return _download(env, f"{_slug(row.name)}.osint.json")


@router.post("/import", response_model=LayerImportResult)
async def import_layer(
    envelope: LayerEnvelope,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
    mission: Mission | None = Depends(get_active_mission),
) -> LayerImportResult:
    if envelope.arrow_layer_export != LAYER_EXPORT_VERSION:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unsupported export version {envelope.arrow_layer_export!r}",
        )
    kind = envelope.kind.upper()
    if kind not in VALID_KINDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown layer kind {kind!r}"
        )

    if kind == "OVERLAY":
        overlay = deserialize.import_overlay(db, envelope, mission, current)
        ids = json.loads(overlay.object_ids or "[]")
        if ids:
            objs = db.query(TacticalObject).filter(TacticalObject.id.in_(ids)).all()
            for obj in objs:
                await broadcaster.broadcast(
                    {
                        "channel": "tactical-object",
                        "event": "created",
                        "mission_id": obj.mission_id,
                        "data": TacticalObjectOut.model_validate(obj).model_dump(
                            mode="json"
                        ),
                    }
                )
        await broadcaster.broadcast(
            {
                "channel": "overlay",
                "event": "created",
                "data": _overlay_to_out(overlay).model_dump(mode="json"),
            }
        )
        return LayerImportResult(kind="OVERLAY", id=overlay.id, name=overlay.name)

    if kind == "KML":
        layer = deserialize.import_kml(db, envelope, current)
        await broadcaster.broadcast(
            {
                "channel": "kml-layer",
                "event": "created",
                "data": {
                    "id": layer.id,
                    "name": layer.name,
                    "description": layer.description,
                    "visible": layer.visible,
                    "uploaded_by": layer.uploaded_by,
                    "feature_count": layer.feature_count,
                },
            }
        )
        return LayerImportResult(kind="KML", id=layer.id, name=layer.name)

    proj = deserialize.import_osint(db, envelope, mission, current)
    return LayerImportResult(kind="OSINT", id=proj.id, name=proj.name)
