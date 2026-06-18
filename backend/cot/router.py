"""CoT endpoint — accepts Cursor-on-Target XML position updates from ATAK/Arrow clients.

POST /cot            application/xml body  →  dual-path:
  • uid == ARROW.{callsign} (own position)  →  update Operator row, broadcast "tracking"
  • any other uid (foreign / simulator entity)  →  upsert CotTrack, broadcast "cot-track"
GET  /cot/tracks     return all live CotTrack rows (for map page-load)
GET  /cot/{uid}      return the latest CoT snapshot for one operator as XML
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.api.schemas import CotTrackOut
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.cot.cot import CotEvent, cot_type_to_sidc, parse_cot, role_to_cot_type
from backend.storage.database import get_db
from backend.storage.models import CotTrack, Operator
from backend.websocket.manager import broadcaster

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/cot", tags=["cot"])


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
async def receive_cot(
    request: Request,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> Response:
    """Accept a CoT XML position event.

    * **Own-position CoT** (uid == ``ARROW.{callsign}``): updates the operator
      row and broadcasts on the ``tracking`` channel — existing ATAK behaviour.
    * **Foreign CoT** (any other uid, e.g. simulator enemy/unknown units):
      upserts a ``CotTrack`` row keyed by uid and broadcasts on the
      ``cot-track`` channel so the tactical map can display it with the correct
      NATO mil-symbol without overwriting the operator's own position.

    Always returns an acknowledgement CoT for the authenticated operator.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty body")

    try:
        evt = parse_cot(body)
    except Exception as exc:
        log.warning("CoT parse error: %s", exc)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Invalid CoT XML") from exc

    own_uid = f"ARROW.{current.callsign}"
    is_own  = evt.uid == own_uid

    # ── Path A: operator's own position ──────────────────────────────────────
    if is_own:
        current.latitude  = evt.lat
        current.longitude = evt.lon
        current.altitude  = evt.hae
        current.last_seen = datetime.now(timezone.utc)
        current.status    = "ONLINE"
        db.commit()
        db.refresh(current)

        cot_type = role_to_cot_type(current.role)
        ack = CotEvent(
            uid      = own_uid,
            cot_type = cot_type,
            lat      = current.latitude,
            lon      = current.longitude,
            hae      = current.altitude or 0.0,
            callsign = current.callsign,
            role     = current.role,
            speed    = evt.speed,
            course   = evt.course,
            team     = evt.team,
        )
        await broadcaster.broadcast({
            "channel": "tracking",
            "event":   "position",
            "cot_xml": ack.to_xml_str(),
            "data": {
                "operator_id": current.id,
                "callsign":    current.callsign,
                "latitude":    current.latitude,
                "longitude":   current.longitude,
                "altitude":    current.altitude,
                "team_id":     current.team_id,
                "cot_type":    cot_type,
            },
        })

    # ── Path B: foreign entity (enemy, simulator unit, ATAK peer) ────────────
    else:
        track = db.query(CotTrack).filter(CotTrack.cot_uid == evt.uid).first()
        if track is None:
            track = CotTrack(cot_uid=evt.uid)
            db.add(track)
        track.cot_type  = evt.cot_type
        track.callsign  = evt.callsign or evt.uid
        track.latitude  = evt.lat
        track.longitude = evt.lon
        track.hae       = evt.hae
        track.speed     = evt.speed
        track.course    = evt.course
        track.team      = evt.team
        track.remarks   = getattr(evt, "remarks", None) or None
        track.last_seen = datetime.now(timezone.utc)
        db.commit()
        db.refresh(track)

        await broadcaster.broadcast({
            "channel": "cot-track",
            "event":   "update",
            "data": {
                "id":        track.id,
                "cot_uid":   track.cot_uid,
                "cot_type":  track.cot_type,
                "sidc":      cot_type_to_sidc(track.cot_type),
                "callsign":  track.callsign,
                "latitude":  track.latitude,
                "longitude": track.longitude,
                "hae":       track.hae,
                "speed":     track.speed,
                "course":    track.course,
                "team":      track.team,
                "remarks":   track.remarks or "",
                "last_seen": track.last_seen.isoformat(),
            },
        })

    # Always ack with the operator's current snapshot
    ack_type = role_to_cot_type(current.role)
    ack = CotEvent(
        uid      = own_uid,
        cot_type = ack_type,
        lat      = current.latitude or evt.lat,
        lon      = current.longitude or evt.lon,
        hae      = current.altitude  or evt.hae,
        callsign = current.callsign,
        role     = current.role,
    )
    return Response(content=ack.to_xml(), media_type="application/xml")


@router.get("/clients")
def list_cot_clients(
    _: Operator = Depends(get_current_operator),
) -> list[dict]:
    """Return list of currently connected ATAK TCP clients."""
    from backend.cot.tcp_server import _Pool
    return _Pool.client_list()


@router.get("/tracks", response_model=list[CotTrackOut])
def list_cot_tracks(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[CotTrack]:
    """Return all live CoT track entities for the tactical map to load on startup."""
    return db.query(CotTrack).all()


@router.get("/shapes")
def list_atak_shapes(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[dict]:
    """Return all persisted ATAK drawn shapes."""
    from backend.storage.models import AtakShape
    shapes = db.query(AtakShape).all()
    return [
        {
            "id": s.id, "uid": s.uid, "cot_type": s.cot_type,
            "shape_type": s.shape_type, "title": s.title,
            "callsign": s.callsign, "geometry_json": s.geometry_json,
            "last_seen": s.last_seen.isoformat() if s.last_seen else None,
        }
        for s in shapes
    ]


@router.get(
    "/{uid}",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
def get_cot_snapshot(
    uid: str,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Response:
    """Return the latest CoT position snapshot for an operator by ARROW.{callsign} uid."""
    callsign = uid.removeprefix("ARROW.")
    op = db.query(Operator).filter(Operator.callsign == callsign).first()
    if not op or op.latitude is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    evt = CotEvent(
        uid      = uid,
        cot_type = role_to_cot_type(op.role),
        lat      = op.latitude,
        lon      = op.longitude,
        hae      = op.altitude or 0.0,
        callsign = op.callsign,
        role     = op.role,
    )
    return Response(content=evt.to_xml(), media_type="application/xml")


# ── TAK / CoT TCP server admin endpoints ─────────────────────────────────────

@router.get("/tcp/status")
def tcp_status(
    _: Operator = Depends(get_current_operator),
) -> dict:
    """Return CoT TCP server status + list of connected ATAK devices."""
    from backend.cot.tcp_server import get_status
    return get_status()


@router.get("/tcp/config")
def tcp_get_config(
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> dict:
    """Return current CoT TCP server configuration."""
    from backend.cot.tcp_server import get_config
    return get_config()


@router.put("/tcp/config")
async def tcp_update_config(
    patch: dict,
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Update CoT TCP server configuration (persisted to data/tak_cot_config.json).

    Changes to ``enabled``, ``host``, or ``port`` require a server restart to
    take effect — use POST /cot/tcp/restart after updating.
    """
    from backend.cot.tcp_server import update_config
    return update_config(patch)


@router.post("/tcp/restart")
async def tcp_restart(
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Stop and restart the CoT TCP server (picks up new host/port config)."""
    from backend.cot import tcp_server
    await tcp_server.stop()
    await tcp_server.start()
    return {"status": "restarted", **tcp_server.get_status()}


# ── TLS / SSL certificate management (for ATAK SSL connections) ───────────────

@router.get("/tcp/tls/info")
def tcp_tls_info(
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> dict:
    """Report which TLS artifacts exist, the truststore password, and cert SANs."""
    from backend.cot.tls_cert import info
    return info()


@router.post("/tcp/tls/generate")
async def tcp_tls_generate(
    force: bool = False,
    _: Operator = Depends(require_role("ADMIN")),
) -> dict:
    """Generate the CoT TLS PKI (CA + server cert + ATAK truststore), then
    restart the listener so it serves the cert. ``force=true`` regenerates from
    scratch (new CA — existing ATAK truststores must be re-imported)."""
    from backend.cot import tcp_server
    from backend.cot.tls_cert import ensure_cot_tls, info, regenerate
    if force:
        regenerate()
    else:
        ensure_cot_tls()
    await tcp_server.stop()
    await tcp_server.start()
    return {"status": "ok", "tls": info(), **tcp_server.get_status()}


@router.get("/tcp/tls/download/{name}")
def tcp_tls_download(
    name: str,
    _: Operator = Depends(require_role("ADMIN")),
) -> Response:
    """Download a generated TLS artifact (truststore / client / ca / server-cert)."""
    from backend.cot.tls_cert import artifact
    got = artifact(name)
    if not got:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Unknown or not-yet-generated TLS artifact")
    data, fname, mime = got
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.delete("/tracks/{track_id}", status_code=204)
async def delete_cot_track(
    track_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    """Remove a foreign CoT track from the DB and map."""
    track = db.get(CotTrack, track_id)
    if track:
        db.delete(track)
        db.commit()
        await broadcaster.broadcast({
            "channel": "cot-track", "event": "deleted",
            "data": {"id": track_id},
        })
