"""EPIC — Intelligence Analysis Workboard API."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import get_current_operator
from backend.missions.dependencies import get_active_mission
from backend.storage.database import get_db
from backend.storage.models import (
    Alert,
    EpicLink,
    EpicNode,
    EpicProject,
    Mission,
    Operator,
    Photo,
    Report,
)

router = APIRouter(prefix="/osint", tags=["osint"])

# ── Pydantic schemas ──────────────────────────────────────────────────────────


class EpicProjectIn(BaseModel):
    name: str
    description: str = ""
    color: str = "#388bfd"


class EpicProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    status: str | None = None  # ACTIVE | ARCHIVED


class EpicProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    color: str
    status: str
    created_by: int
    created_at: datetime
    mission_id: int | None
    classification: int = 0
    node_count: int = 0


class EpicNodeIn(BaseModel):
    node_type: str  # REPORT | PHOTO | ALERT | NOTE | ENTITY
    x: float = 100.0
    y: float = 100.0
    report_id: int | None = None
    photo_id: int | None = None
    alert_id: int | None = None
    title: str | None = None
    content: str | None = None
    entity_type: str | None = None
    color: str | None = None
    tags: list[str] = []


class EpicNodePatch(BaseModel):
    x: float | None = None
    y: float | None = None
    title: str | None = None
    content: str | None = None
    color: str | None = None
    tags: list[str] | None = None


class EpicNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    node_type: str
    x: float
    y: float
    report_id: int | None
    photo_id: int | None
    alert_id: int | None = None
    title: str | None
    content: str | None
    entity_type: str | None
    color: str | None
    tags: list[str]
    created_by: int
    created_at: datetime
    # Denormalized from linked record
    report_type: str | None = None
    report_timestamp: datetime | None = None
    report_status: str | None = None
    report_payload_preview: str | None = None
    report_lat: float | None = None
    report_lon: float | None = None
    report_tic: bool = False
    photo_filename: str | None = None
    photo_original_name: str | None = None
    alert_type: str | None = None
    alert_timestamp: datetime | None = None
    alert_status: str | None = None
    alert_lat: float | None = None
    alert_lon: float | None = None
    alert_callsign: str | None = None


class EpicLinkIn(BaseModel):
    source_node_id: int
    target_node_id: int
    label: str | None = None
    link_type: str = "RELATED"
    # RELATED | CONFIRMS | CONTRADICTS | OBSERVED_AT | ASSOCIATED_WITH | PHOTOGRAPHED_AT


class EpicLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    source_node_id: int
    target_node_id: int
    label: str | None
    link_type: str
    created_by: int
    created_at: datetime


class EpicBoardOut(BaseModel):
    project: EpicProjectOut
    nodes: list[EpicNodeOut]
    links: list[EpicLinkOut]


# ── Helpers ───────────────────────────────────────────────────────────────────

VALID_NODE_TYPES = {"REPORT", "PHOTO", "ALERT", "NOTE", "ENTITY"}
VALID_LINK_TYPES = {
    "RELATED",
    "CONFIRMS",
    "CONTRADICTS",
    "OBSERVED_AT",
    "ASSOCIATED_WITH",
    "PHOTOGRAPHED_AT",
}
VALID_ENTITY_TYPES = {"PERSON", "VEHICLE", "LOCATION", "ORG"}


def _enrich_node(node: EpicNode, db: Session) -> dict[str, Any]:
    """Return EpicNode as a dict with denormalized report/photo/alert fields."""
    d: dict[str, Any] = {
        "id": node.id,
        "project_id": node.project_id,
        "node_type": node.node_type,
        "x": node.x,
        "y": node.y,
        "report_id": node.report_id,
        "photo_id": node.photo_id,
        "alert_id": node.alert_id,
        "title": node.title,
        "content": node.content,
        "entity_type": node.entity_type,
        "color": node.color,
        "tags": json.loads(node.tags) if node.tags else [],
        "created_by": node.created_by,
        "created_at": node.created_at,
        "report_type": None,
        "report_timestamp": None,
        "report_status": None,
        "report_payload_preview": None,
        "report_lat": None,
        "report_lon": None,
        "report_tic": False,
        "photo_filename": None,
        "photo_original_name": None,
        "alert_type": None,
        "alert_timestamp": None,
        "alert_status": None,
        "alert_lat": None,
        "alert_lon": None,
        "alert_callsign": None,
    }
    if node.report_id:
        r = db.get(Report, node.report_id)
        if r:
            d["report_type"] = r.type
            d["report_timestamp"] = r.timestamp
            d["report_status"] = r.status
            d["report_tic"] = bool(r.tic)
            if r.payload:
                try:
                    p = json.loads(r.payload)
                    d["report_lat"] = p.get("latitude") or p.get("lat")
                    d["report_lon"] = p.get("longitude") or p.get("lon")
                    preview = json.dumps(p)[:200]
                except Exception:
                    preview = str(r.payload)[:200]
                d["report_payload_preview"] = preview
    if node.photo_id:
        ph = db.get(Photo, node.photo_id)
        if ph:
            d["photo_filename"] = ph.filename
            d["photo_original_name"] = ph.original_name
    if node.alert_id:
        al = db.get(Alert, node.alert_id)
        if al:
            d["alert_type"] = al.type
            d["alert_timestamp"] = al.timestamp
            d["alert_status"] = al.status
            d["alert_lat"] = al.latitude
            d["alert_lon"] = al.longitude
            d["alert_callsign"] = al.operator.callsign if al.operator else None
    return d


def _project_out(proj: EpicProject) -> EpicProjectOut:
    return EpicProjectOut(
        id=proj.id,
        name=proj.name,
        description=proj.description,
        color=proj.color,
        status=proj.status,
        created_by=proj.created_by,
        created_at=proj.created_at,
        mission_id=proj.mission_id,
        classification=proj.classification,
        node_count=len(proj.nodes),
    )


def _get_project_or_404(project_id: int, db: Session) -> EpicProject:
    proj = db.get(EpicProject, project_id)
    if not proj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return proj


# ── Projects ──────────────────────────────────────────────────────────────────


@router.get("/projects", response_model=list[EpicProjectOut])
def list_projects(
    db: Session = Depends(get_db),
    _op: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> list[EpicProjectOut]:
    q = db.query(EpicProject).filter(EpicProject.status != "DELETED")
    if mission:
        q = q.filter(
            or_(EpicProject.mission_id == mission.id, EpicProject.mission_id.is_(None))
        )
    q = q.filter(EpicProject.classification <= _op.clearance)
    projs = q.order_by(EpicProject.created_at.desc()).all()
    return [_project_out(p) for p in projs]


@router.post(
    "/projects", response_model=EpicProjectOut, status_code=status.HTTP_201_CREATED
)
def create_project(
    body: EpicProjectIn,
    db: Session = Depends(get_db),
    op: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> EpicProjectOut:
    from backend.classification import resolve_default_and_cap

    proj = EpicProject(
        name=body.name.strip(),
        description=body.description,
        color=body.color,
        created_by=op.id,
        mission_id=mission.id if mission else None,
        classification=resolve_default_and_cap(mission, op, None),
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return _project_out(proj)


@router.put("/projects/{project_id}", response_model=EpicProjectOut)
def update_project(
    project_id: int,
    body: EpicProjectUpdate,
    db: Session = Depends(get_db),
    _op: Operator = Depends(get_current_operator),
) -> EpicProjectOut:
    proj = _get_project_or_404(project_id, db)
    if body.name is not None:
        proj.name = body.name.strip()
    if body.description is not None:
        proj.description = body.description
    if body.color is not None:
        proj.color = body.color
    if body.status is not None:
        if body.status not in {"ACTIVE", "ARCHIVED"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid status")
        proj.status = body.status
    db.commit()
    db.refresh(proj)
    return _project_out(proj)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    _op: Operator = Depends(get_current_operator),
) -> None:
    proj = _get_project_or_404(project_id, db)
    db.delete(proj)
    db.commit()


@router.get("/projects/{project_id}", response_model=EpicBoardOut)
def get_board(
    project_id: int,
    db: Session = Depends(get_db),
    _op: Operator = Depends(get_current_operator),
) -> EpicBoardOut:
    proj = _get_project_or_404(project_id, db)
    nodes_out = [EpicNodeOut(**_enrich_node(n, db)) for n in proj.nodes]
    links_out = [EpicLinkOut.model_validate(lk) for lk in proj.links]
    return EpicBoardOut(
        project=_project_out(proj),
        nodes=nodes_out,
        links=links_out,
    )


# ── Nodes ─────────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/nodes",
    response_model=EpicNodeOut,
    status_code=status.HTTP_201_CREATED,
)
def add_node(
    project_id: int,
    body: EpicNodeIn,
    db: Session = Depends(get_db),
    op: Operator = Depends(get_current_operator),
) -> EpicNodeOut:
    _get_project_or_404(project_id, db)
    if body.node_type not in VALID_NODE_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"node_type must be one of {VALID_NODE_TYPES}",
        )
    if body.node_type == "REPORT" and body.report_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "report_id required for REPORT node"
        )
    if body.node_type == "PHOTO" and body.photo_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "photo_id required for PHOTO node"
        )
    if body.node_type == "ALERT" and body.alert_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "alert_id required for ALERT node"
        )
    if body.report_id and not db.get(Report, body.report_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    if body.photo_id and not db.get(Photo, body.photo_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    if body.alert_id and not db.get(Alert, body.alert_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    node = EpicNode(
        project_id=project_id,
        node_type=body.node_type,
        x=body.x,
        y=body.y,
        report_id=body.report_id,
        photo_id=body.photo_id,
        alert_id=body.alert_id,
        title=body.title,
        content=body.content,
        entity_type=body.entity_type,
        color=body.color,
        tags=json.dumps(body.tags) if body.tags else None,
        created_by=op.id,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return EpicNodeOut(**_enrich_node(node, db))


@router.patch("/projects/{project_id}/nodes/{node_id}", response_model=EpicNodeOut)
def patch_node(
    project_id: int,
    node_id: int,
    body: EpicNodePatch,
    db: Session = Depends(get_db),
    _op: Operator = Depends(get_current_operator),
) -> EpicNodeOut:
    node = db.get(EpicNode, node_id)
    if not node or node.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    if body.x is not None:
        node.x = body.x
    if body.y is not None:
        node.y = body.y
    if body.title is not None:
        node.title = body.title
    if body.content is not None:
        node.content = body.content
    if body.color is not None:
        node.color = body.color
    if body.tags is not None:
        node.tags = json.dumps(body.tags)
    db.commit()
    db.refresh(node)
    return EpicNodeOut(**_enrich_node(node, db))


@router.delete(
    "/projects/{project_id}/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_node(
    project_id: int,
    node_id: int,
    db: Session = Depends(get_db),
    _op: Operator = Depends(get_current_operator),
) -> None:
    node = db.get(EpicNode, node_id)
    if not node or node.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    # Delete orphan links manually (SQLite doesn't enforce FK cascades by default)
    db.query(EpicLink).filter(
        or_(
            EpicLink.source_node_id == node_id,
            EpicLink.target_node_id == node_id,
        )
    ).delete(synchronize_session=False)
    db.delete(node)
    db.commit()


# ── Links ─────────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/links",
    response_model=EpicLinkOut,
    status_code=status.HTTP_201_CREATED,
)
def create_link(
    project_id: int,
    body: EpicLinkIn,
    db: Session = Depends(get_db),
    op: Operator = Depends(get_current_operator),
) -> EpicLinkOut:
    _get_project_or_404(project_id, db)
    if body.link_type not in VALID_LINK_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"link_type must be one of {VALID_LINK_TYPES}",
        )
    src = db.get(EpicNode, body.source_node_id)
    tgt = db.get(EpicNode, body.target_node_id)
    if not src or src.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source node not found")
    if not tgt or tgt.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target node not found")
    if body.source_node_id == body.target_node_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Cannot link a node to itself"
        )
    link = EpicLink(
        project_id=project_id,
        source_node_id=body.source_node_id,
        target_node_id=body.target_node_id,
        label=body.label,
        link_type=body.link_type,
        created_by=op.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return EpicLinkOut.model_validate(link)


@router.delete(
    "/projects/{project_id}/links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_link(
    project_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    _op: Operator = Depends(get_current_operator),
) -> None:
    link = db.get(EpicLink, link_id)
    if not link or link.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    db.delete(link)
    db.commit()


# ── Search ────────────────────────────────────────────────────────────────────


class SearchReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    timestamp: datetime
    status: str
    payload_preview: str
    tic: bool = False


class SearchPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    original_name: str
    filename: str
    timestamp: datetime


class SearchAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    timestamp: datetime
    status: str
    callsign: str
    latitude: float | None
    longitude: float | None


class SearchOut(BaseModel):
    reports: list[SearchReportOut]
    photos: list[SearchPhotoOut]
    alerts: list[SearchAlertOut]


@router.get("/search", response_model=SearchOut)
def search(
    q: str = Query("", max_length=120),
    types: str = Query("REPORT,PHOTO,ALERT"),
    db: Session = Depends(get_db),
    _op: Operator = Depends(get_current_operator),
    mission: Mission | None = Depends(get_active_mission),
) -> SearchOut:
    requested = {t.strip().upper() for t in types.split(",")}
    reports_out: list[SearchReportOut] = []
    photos_out: list[SearchPhotoOut] = []
    alerts_out: list[SearchAlertOut] = []

    if "REPORT" in requested:
        rq = db.query(Report)
        if mission:
            rq = rq.filter(Report.mission_id == mission.id)
        if q:
            rq = rq.filter(
                or_(Report.type.ilike(f"%{q}%"), Report.payload.ilike(f"%{q}%"))
            )
        for r in rq.order_by(Report.timestamp.desc()).limit(50).all():
            preview = ""
            if r.payload:
                try:
                    preview = json.dumps(json.loads(r.payload))[:160]
                except Exception:
                    preview = str(r.payload)[:160]
            reports_out.append(
                SearchReportOut(
                    id=r.id,
                    type=r.type,
                    timestamp=r.timestamp,
                    status=r.status,
                    payload_preview=preview,
                    tic=bool(r.tic),
                )
            )

    if "PHOTO" in requested:
        pq = db.query(Photo)
        if q:
            pq = pq.filter(Photo.original_name.ilike(f"%{q}%"))
        for ph in pq.order_by(Photo.timestamp.desc()).limit(50).all():
            photos_out.append(
                SearchPhotoOut(
                    id=ph.id,
                    original_name=ph.original_name or ph.filename,
                    filename=ph.filename,
                    timestamp=ph.timestamp,
                )
            )

    if "ALERT" in requested:
        aq = db.query(Alert)
        if mission:
            aq = aq.filter(Alert.mission_id == mission.id)
        if q:
            aq = aq.filter(Alert.type.ilike(f"%{q}%"))
        from sqlalchemy.orm import selectinload  # noqa: PLC0415

        aq = aq.options(selectinload(Alert.operator))
        for al in aq.order_by(Alert.timestamp.desc()).limit(50).all():
            alerts_out.append(
                SearchAlertOut(
                    id=al.id,
                    type=al.type,
                    timestamp=al.timestamp,
                    status=al.status,
                    callsign=al.operator.callsign if al.operator else "—",
                    latitude=al.latitude,
                    longitude=al.longitude,
                )
            )

    return SearchOut(reports=reports_out, photos=photos_out, alerts=alerts_out)
