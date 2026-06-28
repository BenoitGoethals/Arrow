"""Serialize a live layer row into a portable envelope payload.

Pure functions (no FastAPI/HTTP coupling) so the trickiest part — embedding the
mission-scoped data an overlay/board references so it survives a move to another
mission — is unit-testable in isolation.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from backend.osint.router import _enrich_node
from backend.storage.models import EpicProject, KmlLayer, Overlay, TacticalObject

# Mirrors TacticalObjectIn (backend/api/schemas.py). photo_id is deliberately
# excluded — a photo id from the source mission is meaningless in the target.
TAC_FIELDS = (
    "type",
    "symbol_code",
    "latitude",
    "longitude",
    "notes",
    "visibility",
    "rotation",
    "geometry",
    "echelon",
    "affiliation",
)


def _load_ids(raw: str | None) -> list[int]:
    try:
        ids = json.loads(raw) if raw else []
        return [int(x) for x in ids] if isinstance(ids, list) else []
    except json.JSONDecodeError, ValueError, TypeError:
        return []


def serialize_overlay(db: Session, overlay: Overlay) -> dict[str, Any]:
    """Embed the full tactical-object data (not just ids) so the overlay is portable."""
    ids = _load_ids(overlay.object_ids)
    objects: list[dict[str, Any]] = []
    if ids:
        rows = db.query(TacticalObject).filter(TacticalObject.id.in_(ids)).all()
        by_id = {r.id: r for r in rows}
        for i in ids:  # preserve overlay order, skip stale ids
            r = by_id.get(i)
            if r is not None:
                objects.append({f: getattr(r, f) for f in TAC_FIELDS})
    return {"description": overlay.description, "objects": objects}


def serialize_kml(layer: KmlLayer) -> dict[str, Any]:
    try:
        features = json.loads(layer.features) if layer.features else []
    except json.JSONDecodeError:
        features = []
    return {
        "description": layer.description,
        "bbox": layer.bbox,
        "feature_count": layer.feature_count,
        "features": features,
        "raw_kml": layer.raw_kml,
    }


def serialize_osint(db: Session, project: EpicProject) -> dict[str, Any]:
    """Renumber nodes 0..N (stable index, not DB id); links reference that index."""
    nodes = list(project.nodes)
    index_by_id = {n.id: idx for idx, n in enumerate(nodes)}
    nodes_out: list[dict[str, Any]] = []
    for n in nodes:
        enriched = _enrich_node(
            n, db
        )  # carries denormalized report/photo/alert snapshot
        enriched.pop("id", None)
        enriched.pop("project_id", None)
        nodes_out.append(enriched)
    links_out: list[dict[str, Any]] = []
    for lk in project.links:
        s = index_by_id.get(lk.source_node_id)
        t = index_by_id.get(lk.target_node_id)
        if s is None or t is None:
            continue
        links_out.append(
            {"source": s, "target": t, "label": lk.label, "link_type": lk.link_type}
        )
    return {
        "project": {
            "name": project.name,
            "description": project.description,
            "color": project.color,
        },
        "nodes": nodes_out,
        "links": links_out,
    }
