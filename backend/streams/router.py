"""Live video stream relay + auto-saved recordings.

Android producers push MJPEG frames (compressed JPEG bytes) over WebSocket.
The backend relays each frame to all connected web consumers AND persists
every frame to disk so the stream is replayable from `/streams/recordings/...`
after the producer disconnects.

Flow:
  1. Android  → WS /streams/{id}/produce?token=...  (binary frames)
  2. Backend  → broadcasts JSON {channel:"stream", event:"started"} to all /ws clients
                AND opens a recording file at data/streams/{id}.bin
  3. Browser  → WS /streams/{id}/consume?token=...  (receives binary frames)
  4. Android disconnects → file is sealed with end timestamp + frame count;
                            broadcasts {channel:"stream", event:"ended"}.

On-disk recording format (one file per stream):
    repeated:  <u32-be ts_ms_offset><u32-be jpeg_size><jpeg_bytes>
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from pydantic import BaseModel

from backend.auth.infrastructure import (
    token_service as _token_service,
)  # JWT config read at call-time
from backend.auth.jwt_auth import get_current_operator, require_role
from backend.storage import database as _db  # SessionLocal accessed at call-time
from backend.storage.database import get_db
from backend.storage.models import ExternalStream, Operator, StreamRecording
from backend.websocket.manager import broadcaster

log = logging.getLogger(__name__)
router = APIRouter(prefix="/streams", tags=["streams"])

REC_DIR = Path("data/streams")
REC_DIR.mkdir(parents=True, exist_ok=True)


# ── In-memory stream registry ─────────────────────────────────────────────────


@dataclass
class ActiveStream:
    stream_id: str
    callsign: str
    operator_id: int
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consumers: list[WebSocket] = field(default_factory=list)
    rec_id: int | None = None
    rec_file: IO[bytes] | None = None
    rec_path: Path | None = None
    rec_t0: float | None = None  # monotonic start, for ts_ms offsets
    rec_frames: int = 0
    rec_bytes: int = 0


_registry: dict[str, ActiveStream] = {}  # stream_id → ActiveStream


def list_streams() -> list[dict]:
    return [
        {
            "id": s.stream_id,
            "callsign": s.callsign,
            "operator_id": s.operator_id,
            "started_at": s.started_at.isoformat(),
            "viewers": len(s.consumers),
        }
        for s in _registry.values()
    ]


# ── Auth helper ───────────────────────────────────────────────────────────────


def _verify_token(token: str) -> dict | None:
    """Return JWT payload or None.

    Reads `_token_service._cfg` at call-time — the FastAPI lifespan rebinds it
    after resolving the real (auto-generated or env-provided) JWT secret, and a
    stale captured reference would silently keep verifying against the default.
    """
    from jose import JWTError, jwt

    cfg = _token_service._cfg
    try:
        return jwt.decode(token, cfg.secret, algorithms=[cfg.algorithm])
    except JWTError as exc:
        log.debug("stream token rejected (%s)", exc)
        return None


# ── REST: list active streams ─────────────────────────────────────────────────


@router.get("")
def get_streams(_: Operator = Depends(get_current_operator)) -> list[dict]:
    return list_streams()


# ── Recording helpers ────────────────────────────────────────────────────────


def _safe_filename(stream_id: str) -> str:
    """Reduce to ASCII alphanumerics + a few separators to keep paths sane."""
    out = []
    for ch in stream_id:
        out.append(ch if (ch.isalnum() or ch in "-_") else "_")
    return "".join(out)[:120]


def _open_recording(stream: ActiveStream) -> None:
    """Open the disk file + register a StreamRecording row."""
    fname = f"{int(time.time())}-{_safe_filename(stream.stream_id)}.bin"
    path = REC_DIR / fname
    stream.rec_path = path
    stream.rec_file = path.open("wb")
    stream.rec_t0 = time.monotonic()
    stream.rec_frames = 0
    stream.rec_bytes = 0

    db = _db.SessionLocal()
    try:
        rec = StreamRecording(
            stream_id=stream.stream_id,
            callsign=stream.callsign,
            operator_id=stream.operator_id or None,
            started_at=stream.started_at,
            file_path=str(path),
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        stream.rec_id = rec.id
    finally:
        db.close()


def _append_frame(stream: ActiveStream, frame: bytes) -> None:
    if not stream.rec_file or stream.rec_t0 is None:
        return
    ts_ms = int((time.monotonic() - stream.rec_t0) * 1000)
    try:
        stream.rec_file.write(struct.pack(">II", ts_ms, len(frame)))
        stream.rec_file.write(frame)
        stream.rec_frames += 1
        stream.rec_bytes += 8 + len(frame)
    except Exception as exc:
        log.warning("recording write failed: %s", exc)


def _close_recording(stream: ActiveStream) -> None:
    """Flush the file and finalise the DB row with end timestamp + counts."""
    if stream.rec_file:
        try:
            stream.rec_file.flush()
            stream.rec_file.close()
        except Exception:
            pass
    if stream.rec_id is None:
        return
    db = _db.SessionLocal()
    try:
        rec = db.get(StreamRecording, stream.rec_id)
        if rec:
            rec.ended_at = datetime.now(timezone.utc)
            rec.frame_count = stream.rec_frames
            rec.byte_size = stream.rec_bytes
            db.commit()
    finally:
        db.close()


def _iter_frames(path: Path):
    """Generator over (ts_ms, jpeg_bytes) tuples from a recording file."""
    with path.open("rb") as f:
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                return
            ts_ms, size = struct.unpack(">II", hdr)
            buf = f.read(size)
            if len(buf) < size:
                return
            yield ts_ms, buf


# ── REST: list / delete recordings ──────────────────────────────────────────


@router.get("/recordings")
def list_recordings(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[dict]:
    rows = db.query(StreamRecording).order_by(StreamRecording.started_at.desc()).all()
    return [
        {
            "id": r.id,
            "stream_id": r.stream_id,
            "callsign": r.callsign,
            "operator_id": r.operator_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "frame_count": r.frame_count,
            "byte_size": r.byte_size,
            "duration_ms": (
                int(
                    ((r.ended_at or r.started_at) - r.started_at).total_seconds() * 1000
                )
                if r.ended_at and r.started_at
                else 0
            ),
            "live": r.ended_at is None,
        }
        for r in rows
    ]


@router.get("/recordings/{rec_id}/thumbnail")
def recording_thumbnail(
    rec_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> Response:
    rec = db.get(StreamRecording, rec_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    path = Path(rec.file_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording file missing")
    for _ts, frame in _iter_frames(path):
        return Response(content=frame, media_type="image/jpeg")
    raise HTTPException(status.HTTP_404_NOT_FOUND, "No frames in recording")


@router.get("/recordings/{rec_id}/playback")
def recording_playback(
    rec_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    """Re-stream the recording as motion-JPEG (browser plays it directly).

    Encodes as `multipart/x-mixed-replace` — the same format used by webcam
    feeds; <img src="..."/> renders it as live video without any JS. Frames
    are emitted at their original cadence using the captured ts_ms offsets.
    """
    rec = db.get(StreamRecording, rec_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    path = Path(rec.file_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording file missing")

    boundary = "--arrow-frame"

    async def gen():
        last_ts = 0
        for ts_ms, jpeg in _iter_frames(path):
            delay = max(0, (ts_ms - last_ts) / 1000.0)
            if delay:
                await asyncio.sleep(delay)
            last_ts = ts_ms
            chunk = (
                (
                    f"{boundary}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode()
                + jpeg
                + b"\r\n"
            )
            yield chunk

    return StreamingResponse(
        gen(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary[2:]}",
    )


@router.get("/recordings/{rec_id}/download")
def recording_download(
    rec_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> FileResponse:
    """Raw recording file — same on-disk format used by /playback."""
    rec = db.get(StreamRecording, rec_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    path = Path(rec.file_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording file missing")
    fname = (
        f"arrow-{rec.callsign}-{rec.started_at.strftime('%Y%m%d-%H%M%S')}.arrowmjpeg"
    )
    return FileResponse(path, filename=fname, media_type="application/octet-stream")


@router.delete("/recordings/{rec_id}", status_code=status.HTTP_204_NO_CONTENT)
def recording_delete(
    rec_id: int,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN", "BATTLE_CAPTAIN")),
) -> None:
    rec = db.get(StreamRecording, rec_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    try:
        Path(rec.file_path).unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(rec)
    db.commit()


# ── External streams ────────────────────────────────────────────────────────

_VALID_TYPES = {"mjpeg", "hls", "video"}


class _ExtStreamIn(BaseModel):
    name: str
    url: str
    stream_type: str
    description: str = ""


@router.get("/external")
def list_external_streams(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
) -> list[dict]:
    rows = db.query(ExternalStream).order_by(ExternalStream.added_at.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "url": r.url,
            "stream_type": r.stream_type,
            "description": r.description,
            "added_by": r.added_by,
            "added_at": r.added_at.isoformat() if r.added_at else None,
        }
        for r in rows
    ]


@router.post("/external", status_code=status.HTTP_201_CREATED)
def add_external_stream(
    body: _ExtStreamIn,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> dict:
    if body.stream_type not in _VALID_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"stream_type must be one of: {', '.join(sorted(_VALID_TYPES))}",
        )
    row = ExternalStream(
        name=body.name.strip(),
        url=body.url.strip(),
        stream_type=body.stream_type,
        description=body.description.strip(),
        added_by=current.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "stream_type": row.stream_type,
        "description": row.description,
    }


@router.delete("/external/{ext_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_external_stream(
    ext_id: int,
    db: Session = Depends(get_db),
    current: Operator = Depends(get_current_operator),
) -> None:
    row = db.get(ExternalStream, ext_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if row.added_by != current.id and current.role not in ("ADMIN", "BATTLE_CAPTAIN"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your stream")
    db.delete(row)
    db.commit()


# ── WebSocket: Android producer ───────────────────────────────────────────────


@router.websocket("/{stream_id}/produce")
async def produce(websocket: WebSocket, stream_id: str, token: str = Query(...)):
    payload = _verify_token(token)
    if not payload:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    callsign = payload.get("sub", "unknown")
    operator_id = payload.get("id", 0)

    stream = ActiveStream(
        stream_id=stream_id, callsign=callsign, operator_id=operator_id
    )
    _registry[stream_id] = stream
    _open_recording(stream)
    log.info(
        "Stream started: %s by %s (recording id=%s)", stream_id, callsign, stream.rec_id
    )

    await broadcaster.broadcast(
        {
            "channel": "stream",
            "event": "started",
            "data": {
                "id": stream_id,
                "callsign": callsign,
                "operator_id": operator_id,
                "recording_id": stream.rec_id,
            },
        }
    )

    try:
        while True:
            # Receive a JPEG frame (binary)
            frame = await websocket.receive_bytes()
            if not frame:
                continue
            _append_frame(stream, frame)
            # Relay to all connected consumers in parallel
            if stream.consumers:
                dead: list[WebSocket] = []
                results = await asyncio.gather(
                    *[c.send_bytes(frame) for c in stream.consumers],
                    return_exceptions=True,
                )
                for ws, exc in zip(stream.consumers, results):
                    if isinstance(exc, Exception):
                        dead.append(ws)
                for ws in dead:
                    stream.consumers.remove(ws)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("Producer error: %s", exc)
    finally:
        _registry.pop(stream_id, None)
        _close_recording(stream)
        log.info(
            "Stream ended: %s — %d frames, %d bytes",
            stream_id,
            stream.rec_frames,
            stream.rec_bytes,
        )
        await broadcaster.broadcast(
            {
                "channel": "stream",
                "event": "ended",
                "data": {
                    "id": stream_id,
                    "callsign": callsign,
                    "recording_id": stream.rec_id,
                    "frame_count": stream.rec_frames,
                },
            }
        )
        # Notify all consumers the stream is over
        for c in stream.consumers:
            try:
                await c.send_json({"event": "ended"})
                await c.close()
            except Exception:
                pass


# ── WebSocket: web consumer ───────────────────────────────────────────────────


@router.websocket("/{stream_id}/consume")
async def consume(websocket: WebSocket, stream_id: str, token: str = Query(...)):
    payload = _verify_token(token)
    if not payload:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    stream = _registry.get(stream_id)
    if not stream:
        await websocket.close(code=4404, reason="Stream not found")
        return

    await websocket.accept()
    stream.consumers.append(websocket)
    log.info("Consumer joined: %s for stream %s", payload.get("sub"), stream_id)

    try:
        # Keep alive — consumer is passive (only receives frames)
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in stream.consumers:
            stream.consumers.remove(websocket)
