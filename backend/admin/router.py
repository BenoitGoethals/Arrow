"""Admin-only endpoints: system config, stats, and audit helpers."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.api.schemas import TacticalObjectOut
from backend.auth.jwt_auth import require_role
from backend.config.xml_config import load_config
from backend.storage.database import get_db
from backend.storage.models import (
    Alert, AuditLog, FireMission, MapSnapshot, Message, Operator, Report, TacticalObject,
)
from backend.websocket.manager import broadcaster

router = APIRouter(prefix="/admin", tags=["admin"])

ONLINE_WINDOW = timedelta(seconds=90)


@router.get("/config")
def get_config(
    request: Request,
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Return the current server configuration as JSON.

    The JWT secret is masked; all other values are shown as-is.
    """
    cfg = request.app.state.config
    d = dataclasses.asdict(cfg)
    # Mask the JWT secret
    d["auth"]["secret"] = "***" if d["auth"]["secret"] != "change-me-in-production" else "⚠ DEFAULT — change me!"
    return d


@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Return a live system snapshot for the admin dashboard."""
    now = datetime.now(timezone.utc)

    total_ops      = db.query(Operator).count()
    unassigned_ops = db.query(Operator).filter(Operator.team_id.is_(None)).count()
    online_ops = sum(
        1 for op in db.query(Operator).filter(Operator.status == "ONLINE").all()
        if (now - (op.last_seen if op.last_seen.tzinfo else op.last_seen.replace(tzinfo=timezone.utc))) <= ONLINE_WINDOW
    )
    active_alerts  = db.query(Alert).filter(Alert.status == "ACTIVE").count()
    total_reports  = db.query(Report).count()
    total_objects  = db.query(TacticalObject).count()
    total_messages = db.query(Message).count()

    from sqlalchemy import func
    role_rows = (
        db.query(Operator.role, func.count(Operator.id))
        .group_by(Operator.role)
        .all()
    )

    return {
        "operators": {
            "total":      total_ops,
            "online":     online_ops,
            "unassigned": unassigned_ops,
            "by_role":    {row[0]: row[1] for row in role_rows},
        },
        "alerts":        {"active": active_alerts},
        "reports":       {"total": total_reports},
        "tactical_objects": {"total": total_objects},
        "messages":      {"total": total_messages},
    }


@router.get("/audit")
def get_audit(
    limit: int = 200,
    event_type: str | None = None,
    outcome: str | None = None,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> list[dict]:
    """Return recent security audit log entries — CSF 2.0 DE.CM / GV.OV."""
    q = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if event_type:
        q = q.filter(AuditLog.event_type == event_type.upper())
    if outcome:
        q = q.filter(AuditLog.outcome == outcome.upper())
    return [
        {
            "id":          e.id,
            "event_type":  e.event_type,
            "outcome":     e.outcome,
            "operator_id": e.operator_id,
            "resource":    e.resource,
            "ip_address":  e.ip_address,
            "detail":      e.detail,
            "timestamp":   e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in q.limit(limit).all()
    ]


# ── Map reset / snapshot history ─────────────────────────────────────────────
#
# `POST /admin/map/reset`              capture all TacticalObjects to a snapshot, then delete them
# `GET  /admin/map/snapshots`          list snapshot metadata (no payload)
# `GET  /admin/map/snapshots/{id}`     return the full snapshot payload
# `POST /admin/map/snapshots/{id}/restore`  re-create the objects (with new IDs)
# `DELETE /admin/map/snapshots/{id}`   forget a snapshot

def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _capture_state(db: Session) -> dict:
    """Snapshot every operational record visible on the dashboard / map.

    Excludes operators, hierarchy, photos and audit logs — those are people
    and immutable records, not "operational state".
    """
    return {
        "tactical_objects": [
            {"type": o.type, "symbol_code": o.symbol_code,
             "latitude": o.latitude, "longitude": o.longitude,
             "notes": o.notes, "visibility": o.visibility, "photo_id": o.photo_id,
             "rotation": o.rotation, "geometry": o.geometry, "echelon": o.echelon}
            for o in db.query(TacticalObject).all()
        ],
        "messages": [
            {"sender_id": m.sender_id, "receiver_id": m.receiver_id,
             "group_id": m.group_id, "content": m.content,
             "timestamp": _iso(m.timestamp), "message_type": m.message_type,
             "photo_id": m.photo_id}
            for m in db.query(Message).all()
        ],
        "reports": [
            {"type": r.type, "operator_id": r.operator_id, "payload": r.payload,
             "timestamp": _iso(r.timestamp), "status": r.status,
             "reviewer_note": r.reviewer_note}
            for r in db.query(Report).all()
        ],
        "alerts": [
            {"type": a.type, "operator_id": a.operator_id,
             "latitude": a.latitude, "longitude": a.longitude,
             "timestamp": _iso(a.timestamp), "status": a.status}
            for a in db.query(Alert).all()
        ],
        "fire_missions": [
            {"operator_id": f.operator_id, "latitude": f.latitude,
             "longitude": f.longitude, "altitude": f.altitude,
             "direction": f.direction, "mission_type": f.mission_type,
             "ammunition": f.ammunition, "quantity": f.quantity,
             "description": f.description, "status": f.status,
             "fdc_operator_id": f.fdc_operator_id,
             "timestamp": _iso(f.timestamp), "notes": f.notes}
            for f in db.query(FireMission).all()
        ],
    }


def _state_total(state: dict) -> int:
    return sum(len(v) for v in state.values() if isinstance(v, list))


def _operator_or_fallback(db: Session, op_id: int | None, fallback: int) -> int:
    """Map a stored operator_id back to a current row, or to the restoring admin."""
    if op_id is not None and db.get(Operator, op_id):
        return op_id
    return fallback


def _operator_or_none(db: Session, op_id: int | None) -> int | None:
    if op_id is None:
        return None
    return op_id if db.get(Operator, op_id) else None


@router.post("/map/reset", status_code=status.HTTP_201_CREATED)
async def map_reset(
    request: Request,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Snapshot every operational record, then delete them all.

    Captured: tactical objects, messages, reports, alerts, fire missions.
    Preserved: operators, hierarchy, photos, audit logs, prior snapshots.

    Returns the new snapshot's metadata so the admin UI can refresh its history.
    """
    body = await request.json() if (await request.body()) else {}
    name = (body.get("name") or "").strip() or \
        f"Map reset {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"

    state   = _capture_state(db)
    total   = _state_total(state)
    payload = json.dumps(state)

    snap = MapSnapshot(
        name=name, created_by=current.id, object_count=total, payload=payload,
    )
    db.add(snap)

    # Capture deleted IDs BEFORE deletion so we can broadcast clears
    deleted_to = [o.id for o in db.query(TacticalObject).all()]

    # Bulk delete every snapshotted entity
    db.query(TacticalObject).delete(synchronize_session=False)
    db.query(Message).delete(synchronize_session=False)
    db.query(Report).delete(synchronize_session=False)
    db.query(Alert).delete(synchronize_session=False)
    db.query(FireMission).delete(synchronize_session=False)

    db.commit()
    db.refresh(snap)

    # Live clients pick up the empty map immediately. Tactical-object
    # deletes are the only granular events; chat/reports/alerts/FM consumers
    # already poll, and we send a coarse "presence" tick to nudge them.
    for oid in deleted_to:
        await broadcaster.broadcast(
            {"channel": "tactical-object", "event": "deleted", "data": {"id": oid}}
        )
    await broadcaster.broadcast(
        {"channel": "admin", "event": "map-reset",
         "data": {"snapshot_id": snap.id, "deleted": total}}
    )

    return {
        "id":           snap.id,
        "name":         snap.name,
        "created_by":   snap.created_by,
        "created_at":   snap.created_at.isoformat(),
        "object_count": snap.object_count,
        "counts":       {k: len(v) for k, v in state.items()},
    }


@router.get("/map/snapshots")
def map_snapshots_list(
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> list[dict]:
    rows = (
        db.query(MapSnapshot)
        .order_by(MapSnapshot.created_at.desc())
        .all()
    )
    return [
        {
            "id":           s.id,
            "name":         s.name,
            "created_by":   s.created_by,
            "created_at":   s.created_at.isoformat() if s.created_at else None,
            "object_count": s.object_count,
        }
        for s in rows
    ]


@router.get("/map/snapshots/{snap_id}")
def map_snapshot_detail(
    snap_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    snap = db.get(MapSnapshot, snap_id)
    if not snap:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not found")
    raw = json.loads(snap.payload)
    # Backwards compat: snapshots taken before the multi-entity expansion
    # stored a bare list of tactical-object dicts.
    state = raw if isinstance(raw, dict) else {"tactical_objects": raw}
    return {
        "id":           snap.id,
        "name":         snap.name,
        "created_by":   snap.created_by,
        "created_at":   snap.created_at.isoformat() if snap.created_at else None,
        "object_count": snap.object_count,
        "counts":       {k: len(v) for k, v in state.items() if isinstance(v, list)},
        "state":        state,
    }


@router.delete("/map/snapshots/{snap_id}", status_code=status.HTTP_204_NO_CONTENT)
def map_snapshot_delete(
    snap_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> None:
    snap = db.get(MapSnapshot, snap_id)
    if not snap:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not found")
    db.delete(snap)
    db.commit()


@router.post("/map/snapshots/{snap_id}/restore", status_code=status.HTTP_201_CREATED)
async def map_snapshot_restore(
    snap_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Re-create every snapshotted entity (tactical objects + messages +
    reports + alerts + fire missions) with fresh IDs.

    Restore is additive — existing live data is left in place. Run
    `POST /admin/map/reset` first if you want a clean restore.

    Operator references that no longer exist (e.g. the original sender was
    removed) fall back to the restoring admin so the FK constraint holds.
    """
    snap = db.get(MapSnapshot, snap_id)
    if not snap:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snapshot not found")

    raw = json.loads(snap.payload)
    state = raw if isinstance(raw, dict) else {"tactical_objects": raw}

    counts = {"tactical_objects": 0, "messages": 0, "reports": 0,
              "alerts": 0, "fire_missions": 0}

    # ── Tactical objects ────────────────────────────────────────────
    new_to: list[TacticalObject] = []
    for item in state.get("tactical_objects", []):
        obj = TacticalObject(
            type=item.get("type", "POI"),
            symbol_code=item.get("symbol_code", ""),
            created_by=current.id,
            latitude=float(item.get("latitude", 0.0)),
            longitude=float(item.get("longitude", 0.0)),
            notes=item.get("notes", ""),
            visibility=item.get("visibility", "COMPANY"),
            photo_id=item.get("photo_id"),
            rotation=float(item.get("rotation", 0.0)),
            geometry=item.get("geometry", ""),
            echelon=item.get("echelon", ""),
        )
        db.add(obj); new_to.append(obj); counts["tactical_objects"] += 1

    # ── Messages ────────────────────────────────────────────────────
    for m in state.get("messages", []):
        db.add(Message(
            sender_id=_operator_or_fallback(db, m.get("sender_id"), current.id),
            receiver_id=_operator_or_none(db, m.get("receiver_id")),
            group_id=m.get("group_id"),
            content=m.get("content", ""),
            message_type=m.get("message_type", "DIRECT"),
            photo_id=m.get("photo_id"),
        ))
        counts["messages"] += 1

    # ── Reports ─────────────────────────────────────────────────────
    for r in state.get("reports", []):
        db.add(Report(
            type=r.get("type", "SPOT"),
            operator_id=_operator_or_fallback(db, r.get("operator_id"), current.id),
            payload=r.get("payload", "{}"),
            status=r.get("status", "RECEIVED"),
            reviewer_note=r.get("reviewer_note", ""),
        ))
        counts["reports"] += 1

    # ── Alerts ──────────────────────────────────────────────────────
    for a in state.get("alerts", []):
        db.add(Alert(
            type=a.get("type", "TIC"),
            operator_id=_operator_or_fallback(db, a.get("operator_id"), current.id),
            latitude=a.get("latitude"),
            longitude=a.get("longitude"),
            status=a.get("status", "ACTIVE"),
        ))
        counts["alerts"] += 1

    # ── Fire missions ───────────────────────────────────────────────
    for f in state.get("fire_missions", []):
        db.add(FireMission(
            operator_id=_operator_or_fallback(db, f.get("operator_id"), current.id),
            latitude=float(f.get("latitude", 0.0)),
            longitude=float(f.get("longitude", 0.0)),
            altitude=float(f.get("altitude", 0.0)),
            direction=float(f.get("direction", 0.0)),
            mission_type=f.get("mission_type", "ADJUST_FIRE"),
            ammunition=f.get("ammunition", "HE"),
            quantity=int(f.get("quantity", 1)),
            description=f.get("description", ""),
            status=f.get("status", "PENDING"),
            fdc_operator_id=_operator_or_none(db, f.get("fdc_operator_id")),
            notes=f.get("notes", ""),
        ))
        counts["fire_missions"] += 1

    db.commit()
    for obj in new_to:
        db.refresh(obj)

    # Live clients update without a manual refresh. Tactical-object events
    # are sent granularly; the rest are coarse "channel created" pings —
    # consumers already poll those endpoints.
    for obj in new_to:
        data = TacticalObjectOut.model_validate(obj).model_dump(mode="json")
        await broadcaster.broadcast(
            {"channel": "tactical-object", "event": "created", "data": data}
        )
    await broadcaster.broadcast(
        {"channel": "admin", "event": "snapshot-restored",
         "data": {"snapshot_id": snap.id, "counts": counts}}
    )

    return {
        "snapshot_id": snap.id,
        "restored":    sum(counts.values()),
        "counts":      counts,
    }
