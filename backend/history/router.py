"""Unified event history — aggregates alerts, reports, messages, fire missions,
tactical objects, battles and audit logs into a single timeline.

Supports filtering by date range / category and exporting to JSON, CSV or PDF.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import get_current_operator
from backend.storage.database import get_db
from backend.storage.models import (
    Alert,
    AuditLog,
    Battle,
    FireMission,
    Message,
    Operator,
    Report,
    TacticalObject,
)

router = APIRouter(prefix="/history", tags=["history"])

VALID_CATEGORIES = {
    "alert",
    "report",
    "message",
    "fire_mission",
    "tactical_object",
    "battle",
    "audit",
}


def _parse_dt(raw: str | None, default: datetime | None = None) -> datetime | None:
    if not raw:
        return default
    try:
        # Accept "YYYY-MM-DD" or full ISO-8601
        if len(raw) == 10:
            dt = datetime.fromisoformat(raw)
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid datetime: {raw!r}. Use ISO-8601 (e.g. 2026-05-08 or 2026-05-08T13:00:00Z)",
        )


def _callsign_map(db: Session) -> dict[int, str]:
    return {op.id: op.callsign for op in db.query(Operator).all()}


def _collect_events(
    db: Session,
    start: datetime | None,
    end: datetime | None,
    categories: set[str],
) -> list[dict]:
    callsigns = _callsign_map(db)
    out: list[dict] = []

    def _ts_filter(query, column):
        if start is not None:
            query = query.filter(column >= start)
        if end is not None:
            query = query.filter(column <= end)
        return query

    if "alert" in categories:
        for a in _ts_filter(db.query(Alert), Alert.timestamp).all():
            out.append(
                {
                    "timestamp": a.timestamp,
                    "category": "alert",
                    "type": a.type,
                    "actor": callsigns.get(a.operator_id, f"op:{a.operator_id}"),
                    "actor_id": a.operator_id,
                    "summary": f"{a.type} alert ({a.status})",
                    "latitude": a.latitude,
                    "longitude": a.longitude,
                    "ref_id": a.id,
                    "detail": {"status": a.status},
                }
            )

    if "report" in categories:
        for r in _ts_filter(db.query(Report), Report.timestamp).all():
            try:
                payload = json.loads(r.payload) if r.payload else {}
            except json.JSONDecodeError:
                payload = {"raw": r.payload}
            out.append(
                {
                    "timestamp": r.timestamp,
                    "category": "report",
                    "type": r.type,
                    "actor": callsigns.get(r.operator_id, f"op:{r.operator_id}"),
                    "actor_id": r.operator_id,
                    "summary": f"{r.type} report ({r.status})",
                    "latitude": (
                        payload.get("latitude") if isinstance(payload, dict) else None
                    ),
                    "longitude": (
                        payload.get("longitude") if isinstance(payload, dict) else None
                    ),
                    "ref_id": r.id,
                    "detail": {
                        "status": r.status,
                        "reviewer_note": r.reviewer_note,
                        "payload": payload,
                    },
                }
            )

    if "message" in categories:
        for m in _ts_filter(db.query(Message), Message.timestamp).all():
            target = (
                "broadcast"
                if m.message_type == "BROADCAST"
                else (
                    f"group:{m.group_id}"
                    if m.message_type == "GROUP"
                    else callsigns.get(m.receiver_id or 0, f"op:{m.receiver_id}")
                )
            )
            out.append(
                {
                    "timestamp": m.timestamp,
                    "category": "message",
                    "type": m.message_type,
                    "actor": callsigns.get(m.sender_id, f"op:{m.sender_id}"),
                    "actor_id": m.sender_id,
                    "summary": f"{m.message_type} → {target}: {m.content[:80]}",
                    "latitude": None,
                    "longitude": None,
                    "ref_id": m.id,
                    "detail": {"target": target, "content": m.content},
                }
            )

    if "fire_mission" in categories:
        for f in _ts_filter(db.query(FireMission), FireMission.timestamp).all():
            out.append(
                {
                    "timestamp": f.timestamp,
                    "category": "fire_mission",
                    "type": f.mission_type,
                    "actor": callsigns.get(f.operator_id, f"op:{f.operator_id}"),
                    "actor_id": f.operator_id,
                    "summary": f"{f.mission_type} {f.ammunition} x{f.quantity} ({f.status})",
                    "latitude": f.latitude,
                    "longitude": f.longitude,
                    "ref_id": f.id,
                    "detail": {
                        "ammunition": f.ammunition,
                        "quantity": f.quantity,
                        "status": f.status,
                        "description": f.description,
                    },
                }
            )

    if "tactical_object" in categories:
        for t in _ts_filter(db.query(TacticalObject), TacticalObject.timestamp).all():
            out.append(
                {
                    "timestamp": t.timestamp,
                    "category": "tactical_object",
                    "type": t.type,
                    "actor": callsigns.get(t.created_by, f"op:{t.created_by}"),
                    "actor_id": t.created_by,
                    "summary": f"{t.type} placed ({t.visibility})",
                    "latitude": t.latitude,
                    "longitude": t.longitude,
                    "ref_id": t.id,
                    "detail": {"notes": t.notes, "symbol_code": t.symbol_code},
                }
            )

    if "battle" in categories:
        for b in _ts_filter(db.query(Battle), Battle.started_at).all():
            out.append(
                {
                    "timestamp": b.started_at,
                    "category": "battle",
                    "type": "BATTLE_START",
                    "actor": "system",
                    "actor_id": None,
                    "summary": f"Battle started: {b.name}",
                    "latitude": None,
                    "longitude": None,
                    "ref_id": b.id,
                    "detail": {"description": b.description, "status": b.status},
                }
            )
            if (
                b.ended_at
                and (start is None or b.ended_at >= start)
                and (end is None or b.ended_at <= end)
            ):
                out.append(
                    {
                        "timestamp": b.ended_at,
                        "category": "battle",
                        "type": "BATTLE_END",
                        "actor": "system",
                        "actor_id": None,
                        "summary": f"Battle ended: {b.name}",
                        "latitude": None,
                        "longitude": None,
                        "ref_id": b.id,
                        "detail": {"status": b.status},
                    }
                )

    if "audit" in categories:
        for a in _ts_filter(db.query(AuditLog), AuditLog.timestamp).all():
            out.append(
                {
                    "timestamp": a.timestamp,
                    "category": "audit",
                    "type": a.event_type,
                    "actor": (
                        callsigns.get(a.operator_id or 0, "—") if a.operator_id else "—"
                    ),
                    "actor_id": a.operator_id,
                    "summary": f"{a.event_type} {a.outcome} {a.resource or ''}".strip(),
                    "latitude": None,
                    "longitude": None,
                    "ref_id": a.id,
                    "detail": {
                        "outcome": a.outcome,
                        "ip": a.ip_address,
                        "resource": a.resource,
                        "detail": a.detail,
                    },
                }
            )

    out.sort(key=lambda e: e["timestamp"], reverse=True)
    return out


def _serialize_event(e: dict) -> dict:
    return {**e, "timestamp": e["timestamp"].isoformat() if e["timestamp"] else None}


def _csv_response(events: Iterable[dict]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "timestamp",
            "category",
            "type",
            "actor",
            "summary",
            "latitude",
            "longitude",
            "ref_id",
        ]
    )
    for e in events:
        w.writerow(
            [
                e["timestamp"].isoformat() if e["timestamp"] else "",
                e["category"],
                e["type"],
                e["actor"],
                e["summary"],
                e.get("latitude") or "",
                e.get("longitude") or "",
                e["ref_id"],
            ]
        )
    fname = f"arrow-history-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _pdf_response(
    events: list[dict], start: datetime | None, end: datetime | None
) -> Response:
    """Render a minimal text-only PDF without external dependencies."""
    lines: list[str] = []
    title = "ARROW — Event History"
    rng = (
        f"{start.isoformat() if start else 'beginning'}  →  "
        f"{end.isoformat() if end else 'now'}"
    )
    lines.append(title)
    lines.append(rng)
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Total events: {len(events)}")
    lines.append("")
    for e in events:
        ts = e["timestamp"].strftime("%Y-%m-%d %H:%M:%SZ") if e["timestamp"] else "—"
        line = (
            f"{ts}  [{e['category'].upper()}/{e['type']}]  {e['actor']}: {e['summary']}"
        )
        # Wrap long lines (max ~95 chars at 9pt courier on A4)
        while len(line) > 95:
            lines.append(line[:95])
            line = "    " + line[95:]
        lines.append(line)

    pdf = _build_pdf(lines)
    fname = f"arrow-history-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _build_pdf(lines: list[str]) -> bytes:
    """Build a minimal multi-page PDF with Courier 9pt text — no deps."""
    page_w, page_h = 595, 842  # A4 in points
    margin_x, margin_top = 40, 800
    line_h, font_size = 11, 9
    lines_per_page = (margin_top - 40) // line_h

    pages: list[list[str]] = []
    for i in range(0, len(lines), lines_per_page):
        pages.append(lines[i : i + lines_per_page])
    if not pages:
        pages = [["(no events)"]]

    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")

    objects: list[bytes] = []

    def _add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)  # 1-based

    # Reserve slots: 1=catalog, 2=pages root, 3=font
    # We'll build page + content objects after.
    page_obj_ids: list[int] = []
    content_obj_ids: list[int] = []

    # Catalog & Pages placeholders — we patch refs after we know counts.
    # Simpler: build content + page objs first, then pages root + catalog.

    for pg in pages:
        stream_lines = ["BT", "/F1 %d Tf" % font_size, f"{margin_x} {margin_top} Td"]
        first = True
        for ln in pg:
            if first:
                stream_lines.append(f"({_esc(ln)}) Tj")
                first = False
            else:
                stream_lines.append(f"0 -{line_h} Td ({_esc(ln)}) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
        content = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"\nendstream"
        )
        content_obj_ids.append(_add(content))

    # Font object
    font_id = _add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    # Page objects (need parent ref — we know it'll be the next id after all pages)
    pages_root_id = len(objects) + len(pages) + 1
    for cid in content_obj_ids:
        page_obj = (
            f"<< /Type /Page /Parent {pages_root_id} 0 R "
            f"/MediaBox [0 0 {page_w} {page_h}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {cid} 0 R >>"
        ).encode("latin-1")
        page_obj_ids.append(_add(page_obj))

    kids = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    pages_root = (
        f"<< /Type /Pages /Count {len(page_obj_ids)} /Kids [ {kids} ] >>"
    ).encode("latin-1")
    actual_pages_root_id = _add(pages_root)
    assert actual_pages_root_id == pages_root_id

    catalog_id = _add(
        f"<< /Type /Catalog /Pages {pages_root_id} 0 R >>".encode("latin-1")
    )

    # Assemble file
    out = bytearray()
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets: list[int] = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1")
        out += body
        out += b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)


@router.get("")
def get_history(
    start: str | None = Query(
        None, description="ISO-8601 start (inclusive). Omit for all-time."
    ),
    end: str | None = Query(
        None, description="ISO-8601 end (inclusive). Omit for now."
    ),
    categories: str | None = Query(
        None,
        description="Comma-separated subset of: " + ",".join(sorted(VALID_CATEGORIES)),
    ),
    format: str = Query("json", pattern="^(json|csv|pdf)$"),
    limit: int = Query(5000, ge=1, le=50000),
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    """Return a unified, time-ordered event history.

    `format=json` (default) returns a JSON list. `format=csv` and `format=pdf`
    return a downloadable file.
    """
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    if start_dt and end_dt and start_dt > end_dt:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "start must be <= end"
        )

    if categories:
        cats = {c.strip().lower() for c in categories.split(",") if c.strip()}
        unknown = cats - VALID_CATEGORIES
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown categories: {sorted(unknown)}. Valid: {sorted(VALID_CATEGORIES)}",
            )
    else:
        cats = set(VALID_CATEGORIES)

    events = _collect_events(db, start_dt, end_dt, cats)[:limit]

    if format == "csv":
        return _csv_response(events)
    if format == "pdf":
        return _pdf_response(events, start_dt, end_dt)

    return {
        "start": start_dt.isoformat() if start_dt else None,
        "end": end_dt.isoformat() if end_dt else None,
        "count": len(events),
        "events": [_serialize_event(e) for e in events],
    }
