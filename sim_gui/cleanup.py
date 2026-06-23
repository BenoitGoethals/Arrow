"""Clean the backend's world before a scenario starts.

Preferred path — `POST /admin/map/reset` (backend/admin/router.py:337):
snapshots and then deletes every tactical object, alert, report, fire mission,
message, KML layer, overlay, CoT track and **every non-ADMIN operator** (and
their position history). Unit hierarchy, ADMIN accounts, photos, audit logs
and prior snapshots are preserved.

Some deployed backends are older and either lack `/admin/map/reset` or 500
when called (FK/schema drift). In that case we fall back to a manual sweep
that deletes each resource individually via its own `DELETE` route. The
fallback can't wipe non-ADMIN operators (no admin delete-all endpoint) — it
clears only the per-mission state every scenario needs cleared.

In every case we follow up with a `/vehicles` sweep because vehicles aren't
in the bulk-reset payload.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from sim_gui.backend_client import AdminSession

log = logging.getLogger("sim.cleanup")


_FALLBACK_PATHS = (
    "/tactical-objects",
    "/alerts",
    "/reports",
    "/fire-missions",
    "/cas/assets",
    "/logcop/supply-points",
)

# Hierarchy DELETE order — children before parents to satisfy FK constraints.
_HIERARCHY_PATHS = ("/teams", "/sections", "/platoons", "/companies")
# Per-mission scoped resources also worth wiping.
_OPORD_PATH = "/opord"


def _sweep(session: AdminSession, path: str) -> int:
    removed = 0
    try:
        items = cast(list[dict[str, Any]], session.get(path) or [])
    except Exception as e:
        log.warning("GET %s failed: %s", path, e)
        return 0
    for it in items:
        oid = it.get("id")
        if oid is None:
            continue
        try:
            session.delete(f"{path}/{oid}")
            removed += 1
        except Exception:
            pass
    return removed


def _sweep_missions(session: AdminSession) -> int:
    """End any ACTIVE missions then DELETE every mission record.

    `DELETE /missions/{id}` 409s on ACTIVE missions (per
    `backend/missions/router.py:140`), so we POST `.../end` first. The end
    POST may itself 4xx if the mission is already ENDED — that's fine.
    """
    try:
        items = cast(list[dict[str, Any]], session.get("/missions") or [])
    except Exception as e:
        log.warning("GET /missions failed: %s", e)
        return 0
    removed = 0
    for m in items:
        mid = m.get("id")
        if mid is None:
            continue
        if m.get("status") == "ACTIVE":
            try:
                session.post(f"/missions/{mid}/end", session.token, {})
            except Exception:
                pass
        try:
            session.delete(f"/missions/{mid}")
            removed += 1
        except Exception:
            pass
    return removed


def _sweep_hierarchy(session: AdminSession) -> dict[str, int]:
    """Delete every team → section → platoon → company.

    The hierarchy_seeder will recreate the exact ORBAT from `data/3para_sor.json`
    on the next run, so a wipe-and-rebuild gives every scenario a clean tree.
    """
    counts: dict[str, int] = {}
    for path in _HIERARCHY_PATHS:
        counts[path.lstrip("/")] = _sweep(session, path)
    return counts


def _manual_sweep(session: AdminSession) -> dict[str, int]:
    counts = {p.lstrip("/"): _sweep(session, p) for p in _FALLBACK_PATHS}
    counts["missions"] = _sweep_missions(session)
    counts["opord"] = _sweep(session, _OPORD_PATH)
    return counts


def full_reset(session: AdminSession, snapshot_name: str) -> dict:
    """Snapshot + nuke the world. Resilient to backends without `/admin/map/reset`."""
    log.info("POST /admin/map/reset (snapshot=%s)", snapshot_name)
    out: dict[str, Any] = {}
    try:
        result = session.post(
            "/admin/map/reset", session.token, {"name": snapshot_name}
        )
        if isinstance(result, dict):
            out = result
    except httpx.HTTPStatusError as e:
        log.warning(
            "/admin/map/reset returned %d — falling back to manual sweep",
            e.response.status_code,
        )
        out = {"fallback": True, "counts": _manual_sweep(session)}
    except Exception as e:
        log.warning(
            "/admin/map/reset raised %s — falling back to manual sweep",
            type(e).__name__,
        )
        out = {"fallback": True, "counts": _manual_sweep(session)}

    try:
        vehicles = cast(list[dict[str, Any]], session.get("/vehicles") or [])
        for v in vehicles:
            session.delete(f"/vehicles/{v['id']}")
        if vehicles:
            log.info("swept %d residual vehicle(s)", len(vehicles))
    except Exception as e:
        log.warning("vehicle sweep skipped: %s", e)

    # Missions aren't included in `/admin/map/reset`'s deletion list on older
    # backends — sweep them in both branches so re-runs don't accumulate.
    if not out.get("fallback"):
        try:
            n = _sweep_missions(session)
            if n:
                log.info("swept %d residual mission(s)", n)
        except Exception as e:
            log.warning("mission sweep skipped: %s", e)

    # OPORDs aren't in the reset payload either; always sweep.
    try:
        n_op = _sweep(session, _OPORD_PATH)
        if n_op:
            log.info("swept %d OPORD(s)", n_op)
    except Exception as e:
        log.warning("opord sweep skipped: %s", e)

    # Hierarchy wipe — deletes the unit tree so the next scenario starts from
    # the canonical ORBAT in data/3para_sor.json. Children before parents.
    try:
        h_counts = _sweep_hierarchy(session)
        h_total = sum(h_counts.values())
        if h_total:
            log.info("wiped hierarchy: %s", h_counts)
        out["hierarchy"] = h_counts
    except Exception as e:
        log.warning("hierarchy wipe skipped: %s", e)

    return out
