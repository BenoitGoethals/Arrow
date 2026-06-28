"""Re-create a layer from an envelope, into a target mission.

Pure functions: they create + commit rows and return the new entity, but emit no
realtime events (the router broadcasts after a successful import). Cross-mission
correctness lives here — recreating an overlay's objects, remapping OSINT node
ids, and degrading record-backed nodes so no foreign key dangles.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from backend.layers.envelope import LayerEnvelope
from backend.storage.models import (
    EpicLink,
    EpicNode,
    EpicProject,
    KmlLayer,
    Mission,
    Operator,
    Overlay,
    TacticalObject,
)


def import_overlay(
    db: Session, env: LayerEnvelope, mission: Mission | None, operator: Operator
) -> Overlay:
    """Recreate each embedded object in the target mission, build a fresh overlay."""
    payload = env.payload
    mission_id = mission.id if mission else None
    created: list[TacticalObject] = []
    for o in payload.get("objects") or []:
        obj = TacticalObject(
            created_by=operator.id,
            mission_id=mission_id,
            type=o.get("type") or "MARKER",
            symbol_code=o.get("symbol_code", ""),
            latitude=o.get("latitude", 0.0),
            longitude=o.get("longitude", 0.0),
            notes=o.get("notes", ""),
            visibility=o.get("visibility", "COMPANY"),
            photo_id=None,
            rotation=o.get("rotation", 0.0),
            geometry=o.get("geometry", ""),
            echelon=o.get("echelon", ""),
            affiliation=o.get("affiliation", "FRIENDLY"),
        )
        db.add(obj)
        created.append(obj)
    db.flush()  # assign ids
    new_ids = [o.id for o in created]
    overlay = Overlay(
        name=env.name,
        description=payload.get("description", ""),
        created_by=operator.id,
        object_ids=json.dumps(new_ids, separators=(",", ":")),
    )
    db.add(overlay)
    db.commit()
    db.refresh(overlay)
    return overlay


def import_kml(db: Session, env: LayerEnvelope, operator: Operator) -> KmlLayer:
    """KML layers are global — just recreate the row."""
    payload = env.payload
    features = payload.get("features") or []
    layer = KmlLayer(
        name=env.name,
        description=payload.get("description", ""),
        uploaded_by=operator.id,
        feature_count=payload.get("feature_count") or len(features),
        features=json.dumps(features, separators=(",", ":")),
        bbox=payload.get("bbox", ""),
        raw_kml=payload.get("raw_kml", ""),
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)
    return layer


def _summarize_node(nd: dict[str, Any]) -> tuple[str, str]:
    """Build NOTE title/content from a record-backed node's frozen snapshot."""
    node_type = nd.get("node_type")
    if node_type == "REPORT":
        title = f"Report: {nd.get('report_type') or '—'}"
        bits = []
        if nd.get("report_status"):
            bits.append(f"Status: {nd['report_status']}")
        if nd.get("report_timestamp"):
            bits.append(f"DTG: {nd['report_timestamp']}")
        if nd.get("report_payload_preview"):
            bits.append(str(nd["report_payload_preview"]))
        return title, "\n".join(bits)
    if node_type == "PHOTO":
        title = nd.get("photo_original_name") or nd.get("photo_filename") or "Photo"
        return f"Photo: {title}", ""
    if node_type == "ALERT":
        title = f"Alert: {nd.get('alert_type') or '—'}"
        bits = []
        if nd.get("alert_callsign"):
            bits.append(f"Callsign: {nd['alert_callsign']}")
        if nd.get("alert_status"):
            bits.append(f"Status: {nd['alert_status']}")
        if nd.get("alert_timestamp"):
            bits.append(f"DTG: {nd['alert_timestamp']}")
        return title, "\n".join(bits)
    return nd.get("title") or "Note", nd.get("content") or ""


def _rebuild_node(nd: dict[str, Any], project_id: int, operator_id: int) -> EpicNode:
    node_type = nd.get("node_type", "NOTE")
    tags = nd.get("tags") or []
    tags_json = json.dumps(tags) if tags else None
    common = {
        "project_id": project_id,
        "x": nd.get("x", 100.0),
        "y": nd.get("y", 100.0),
        "color": nd.get("color"),
        "tags": tags_json,
        "created_by": operator_id,
    }
    if node_type in ("REPORT", "PHOTO", "ALERT"):
        # Degrade to a NOTE: the referenced report/photo/alert does not exist in
        # the target mission, so keep the analyst's text and drop the FK.
        title, content = _summarize_node(nd)
        return EpicNode(node_type="NOTE", title=title, content=content, **common)
    # NOTE / ENTITY (anything unexpected falls back to NOTE) is preserved as-is.
    return EpicNode(
        node_type=node_type if node_type in ("NOTE", "ENTITY") else "NOTE",
        title=nd.get("title"),
        content=nd.get("content"),
        entity_type=nd.get("entity_type"),
        **common,
    )


def import_osint(
    db: Session, env: LayerEnvelope, mission: Mission | None, operator: Operator
) -> EpicProject:
    """Clone project + nodes + links into the target mission, remapping node ids."""
    payload = env.payload
    meta = payload.get("project") or {}
    proj = EpicProject(
        name=env.name or meta.get("name") or "Imported board",
        description=meta.get("description", ""),
        color=meta.get("color") or "#388bfd",
        created_by=operator.id,
        mission_id=mission.id if mission else None,
    )
    db.add(proj)
    db.flush()
    index_to_id: dict[int, int] = {}
    for idx, nd in enumerate(payload.get("nodes") or []):
        node = _rebuild_node(nd, proj.id, operator.id)
        db.add(node)
        db.flush()
        index_to_id[idx] = node.id
    for lk in payload.get("links") or []:
        s = index_to_id.get(lk.get("source"))
        t = index_to_id.get(lk.get("target"))
        if s is None or t is None or s == t:
            continue
        db.add(
            EpicLink(
                project_id=proj.id,
                source_node_id=s,
                target_node_id=t,
                label=lk.get("label"),
                link_type=lk.get("link_type") or "RELATED",
                created_by=operator.id,
            )
        )
    db.commit()
    db.refresh(proj)
    return proj
