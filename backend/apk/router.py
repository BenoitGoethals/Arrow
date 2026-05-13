"""Android APK distribution.

Admin configures one location — either a locally-mounted filesystem path
(which covers any OS-mounted NFS or SMB share) or a direct SMB target.
Any authenticated operator can download the APK from ``GET /apk/download``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.jwt_auth import get_current_operator, require_role
from backend.storage.database import get_db
from backend.storage.models import ApkDistConfig, Operator

router = APIRouter(tags=["apk"])

_VALID_KINDS = {"LOCAL", "SMB"}
_CHUNK = 64 * 1024


# ── Schemas ──────────────────────────────────────────────────────────────
class ApkConfigIn(BaseModel):
    kind:     str = Field("LOCAL", description="LOCAL or SMB")
    host:     str = ""
    share:    str = ""
    path:     str = ""
    filename: str = "arrow.apk"
    username: str = ""
    password: str = ""


class ApkConfigOut(BaseModel):
    kind:     str
    host:     str
    share:    str
    path:     str
    filename: str
    username: str
    has_password: bool = False     # never echo the password back
    configured:   bool = False
    updated_at:   str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────
def _get_or_create(db: Session) -> ApkDistConfig:
    row = db.get(ApkDistConfig, 1)
    if row is None:
        row = ApkDistConfig(id=1)
        db.add(row); db.commit(); db.refresh(row)
    return row


def _to_out(row: ApkDistConfig) -> ApkConfigOut:
    return ApkConfigOut(
        kind=row.kind, host=row.host, share=row.share, path=row.path,
        filename=row.filename, username=row.username,
        has_password=bool(row.password),
        configured=bool(row.path),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _resolve_local(row: ApkDistConfig) -> Path:
    """Local mode: ``path`` is either the APK file itself, or a directory
    that contains ``filename``. Mounted NFS / SMB shares fall under this
    branch — the admin mounts them at the OS level."""
    raw = row.path
    # Catch the common mistake of entering an NFS/SMB URI instead of a mount point.
    for scheme in ("nfs://", "smb://", "cifs://"):
        if raw.lower().startswith(scheme):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"LOCAL mode requires a mounted filesystem path, not a URI. "
                f"Mount the share on the server first (e.g. 'mount -t nfs {raw.split('://', 1)[1]} /mnt/apks') "
                f"then set the path to the mount point (e.g. '/mnt/apks').",
            )
    p = Path(raw).expanduser()
    if p.is_dir():
        p = p / (row.filename or "arrow.apk")
    if not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"APK file not found at {p}")
    return p


def _stream_local(p: Path) -> Iterator[bytes]:
    with p.open("rb") as fh:
        while True:
            buf = fh.read(_CHUNK)
            if not buf:
                break
            yield buf


def _stream_smb(row: ApkDistConfig) -> tuple[Iterator[bytes], int]:
    """Open and stream a file from an SMB server. Requires ``smbprotocol``.

    Returns (iterator, total-size). The connection is closed when the
    generator is exhausted. All failure paths raise an HTTPException with a
    descriptive ``detail`` so the operator can fix the misconfiguration.
    """
    import logging
    log = logging.getLogger(__name__)

    try:
        import smbclient                                          # type: ignore
    except ImportError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SMB transport requires the 'smbprotocol' package. "
            "Install it on the server (uv add smbprotocol) or mount the share locally and use LOCAL mode.",
        ) from exc

    if not row.host or not row.share:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "SMB mode requires host and share to be set.")

    # Build the UNC path. `path` may be a directory inside the share or the
    # full file path; if it doesn't already end in `.apk`, treat it as a
    # directory and append ``filename``.
    rel = (row.path or "").strip().replace("/", "\\").lstrip("\\")
    if rel and not rel.lower().endswith(".apk") and row.filename:
        rel = rel.rstrip("\\") + "\\" + row.filename
    if not rel:
        rel = row.filename or "arrow.apk"
    unc = f"\\\\{row.host}\\{row.share}\\{rel}"

    # Always register a session so smbclient doesn't fall through to its
    # default Kerberos / ccache path (which fails on workgroup shares and is
    # the source of the "No username or password was specified" SpnegoError).
    # If the admin left credentials blank, attempt anonymous / Guest auth.
    try:
        smbclient.register_session(
            row.host,
            username=row.username or "Guest",
            password=row.password or "",
            connection_timeout=10,
        )
    except Exception as exc:
        log.exception("SMB register_session failed for %s", row.host)
        msg = str(exc)
        # If creds are blank AND auth fails, point the admin at the config.
        if not row.username and "auth" in msg.lower():
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                f"SMB share at {row.host} requires authentication. Set the SMB "
                f"username and password in Admin → APK Distribution. ({exc})",
            ) from exc
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"SMB authentication / connection to {row.host} failed: {exc}",
        ) from exc

    # Stat the file to validate the path AND report Content-Length.
    try:
        size = smbclient.stat(unc).st_size
    except Exception as exc:
        log.exception("SMB stat failed for %s", unc)
        # Common case: stat() can re-trigger auth on first real access; if
        # the error mentions authentication, return 401 instead of 404 so
        # the admin gets pointed at the credentials.
        msg = str(exc)
        is_auth = "SMBAuthenticationError" in type(exc).__name__ \
                  or "auth" in msg.lower() or "credential" in msg.lower() \
                  or "Spnego" in msg
        if is_auth:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                f"SMB share {row.host}\\{row.share} rejected the credentials. "
                f"Check the SMB username / password in Admin → APK Distribution. "
                f"({type(exc).__name__}: {exc})",
            ) from exc
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"SMB file not found or inaccessible: {unc} ({type(exc).__name__}: {exc})",
        ) from exc

    # Open the file UP FRONT so connection errors surface as HTTPException
    # (not a 500 mid-response after headers have been sent).
    try:
        fh = smbclient.open_file(unc, mode="rb")
    except Exception as exc:
        log.exception("SMB open_file failed for %s", unc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Cannot open SMB file {unc}: {type(exc).__name__}: {exc}",
        ) from exc

    def _gen() -> Iterator[bytes]:
        try:
            while True:
                buf = fh.read(_CHUNK)
                if not buf:
                    break
                yield buf
        finally:
            try:
                fh.close()
            except Exception:
                pass

    return _gen(), size


# ── Admin config endpoints ───────────────────────────────────────────────
@router.get("/admin/apk-config", response_model=ApkConfigOut)
def get_apk_config(
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> ApkConfigOut:
    return _to_out(_get_or_create(db))


@router.put("/admin/apk-config", response_model=ApkConfigOut)
def put_apk_config(
    payload: ApkConfigIn,
    db: Session = Depends(get_db),
    _: Operator = Depends(require_role("ADMIN")),
) -> ApkConfigOut:
    kind = (payload.kind or "LOCAL").upper()
    if kind not in _VALID_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"kind must be one of {sorted(_VALID_KINDS)}")
    row = _get_or_create(db)
    row.kind     = kind
    row.host     = payload.host.strip()
    row.share    = payload.share.strip()
    row.path     = payload.path.strip()
    row.filename = (payload.filename or "arrow.apk").strip() or "arrow.apk"
    row.username = payload.username.strip()
    # Empty password means "leave unchanged" so admins don't have to retype it
    if payload.password:
        row.password = payload.password
    db.commit(); db.refresh(row)
    return _to_out(row)


# ── Download endpoint ────────────────────────────────────────────────────
@router.get("/apk/download")
def download_apk(
    db: Session = Depends(get_db),
    _: Operator = Depends(get_current_operator),
):
    """Stream the configured APK to the caller.

    Any authenticated operator may download. The download name is taken
    from the configured ``filename``.
    """
    import logging
    log = logging.getLogger(__name__)

    row = _get_or_create(db)
    if not row.path:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "APK distribution is not configured. An admin must set the source path in Admin → Configuration.",
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{row.filename or "arrow.apk"}"',
    }
    try:
        if row.kind == "SMB":
            gen, size = _stream_smb(row)
            headers["Content-Length"] = str(size)
            return StreamingResponse(
                gen, media_type="application/vnd.android.package-archive", headers=headers,
            )

        # LOCAL (includes OS-mounted NFS / SMB shares)
        p = _resolve_local(row)
        headers["Content-Length"] = str(os.path.getsize(p))
        return StreamingResponse(
            _stream_local(p),
            media_type="application/vnd.android.package-archive",
            headers=headers,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Unexpected APK download error (kind=%s path=%r)",
                      row.kind, row.path)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"APK download failed: {type(exc).__name__}: {exc}",
        ) from exc
