"""Mirror MortarCalc FDC pieces / FOs / targets onto the Arrow Front COP map
and the web map.

MortarcalcMapBridge  — syncs to the Front (PyQt6 Leaflet) map view directly.
MortarcalcWebBridge  — syncs to the Arrow backend (HTTP API) so the web map
                       sees the same markers, and broadcasts a ``mortar-cop``
                       WS event whenever a mission transitions to SHOT or
                       IN_EFFECT so both the web map and Front can show a
                       firing toast.

Both bridges connect to MortarCalc's ``state_changed`` and ``closing`` signals
and are safe to instantiate together.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

# APP-6 / 2525B SIDCs (15 char). milsymbol renders a proper frame for these.
SIDC_PIECE = "SFGPUCFMS-----"  # friendly ground · fire support · mortar
SIDC_FO = "SFGPUUSO------"  # friendly ground · observer (forward observer)
SIDC_TARGET = "SHGPU---------"  # hostile ground unit (target)

# Stable id namespace so we can find & remove only our own markers.
_NS = "mortarcalc"


# ---------------------------------------------------------------------------
# Shared helper: build the canonical {oid: obj} dict from a MortarCalc window
# ---------------------------------------------------------------------------

def _build_mortar_objects(window, operators_by_callsign: dict) -> dict[str, dict]:
    """Return {oid: obj_dict} for all pieces, FOs and targets in *window*."""
    from mortarcalc.geo import utm_to_latlon

    peloton = getattr(window, "peloton", None)
    if peloton is None:
        return {}
    objs: dict[str, dict] = {}

    # ---- Mortar pieces ------------------------------------------------
    for p in getattr(peloton, "pieces", []):
        try:
            lat, lon = utm_to_latlon(p.position)
        except Exception:
            continue
        oid = f"{_NS}:piece:{p.name}"
        base = " (base)" if getattr(p, "is_base", False) else ""
        objs[oid] = {
            "id": oid,
            "type": "MARKER",
            "symbol_code": SIDC_PIECE,
            "affiliation": "FRIENDLY",
            "latitude": lat,
            "longitude": lon,
            "notes": f"Mortar {p.name}{base}\n{p.position.to_mgrs()}",
        }

    # ---- Forward Observers (linked to operators) ----------------------
    for o in getattr(peloton, "observers", []):
        objs.update(
            _fo_object(o.call_sign, o.position, operators_by_callsign, utm_to_latlon)
        )

    # ---- Targets: active fire missions + planned fire-plan targets -----
    mp = getattr(window, "mission_panel", None)
    active = getattr(mp, "active", {}) if mp is not None else {}
    for group_name, fm in (active or {}).items():
        if fm is None or getattr(fm, "target_position", None) is None:
            continue
        try:
            lat, lon = utm_to_latlon(fm.target_position)
        except Exception:
            continue
        oid = f"{_NS}:target:{fm.id}"
        desc = (fm.target_description or "").strip()
        objs[oid] = {
            "id": oid,
            "type": "ENEMY",
            "symbol_code": SIDC_TARGET,
            "affiliation": "HOSTILE",
            "latitude": lat,
            "longitude": lon,
            "notes": f"Target {fm.id} ({group_name})"
            + (f"\n{desc}" if desc else "")
            + f"\n{fm.target_position.to_mgrs()}",
        }
        # Also mirror the FO that owns this mission.
        obs = getattr(fm, "observer", None)
        if obs is not None:
            objs.update(
                _fo_object(obs.call_sign, obs.position, operators_by_callsign, utm_to_latlon)
            )

    for t in getattr(peloton, "fire_plan", []):
        try:
            lat, lon = utm_to_latlon(t.position)
        except Exception:
            continue
        oid = f"{_NS}:planned:{t.name}"
        desc = (getattr(t, "description", "") or "").strip()
        fpf = " · FPF" if getattr(t, "is_fpf", False) else ""
        objs[oid] = {
            "id": oid,
            "type": "ENEMY",
            "symbol_code": SIDC_TARGET,
            "affiliation": "HOSTILE",
            "latitude": lat,
            "longitude": lon,
            "notes": f"Planned target {t.name}{fpf}"
            + (f"\n{desc}" if desc else "")
            + f"\n{t.position.to_mgrs()}",
        }

    return objs


def _fo_object(call_sign, position, ops_by_callsign, utm_to_latlon) -> dict[str, dict]:
    op = ops_by_callsign.get(str(call_sign).strip().lower())
    op_lat = op.get("latitude") if op else None
    op_lon = op.get("longitude") if op else None
    linked = op is not None and op_lat is not None and op_lon is not None
    if linked:
        lat, lon = float(op_lat), float(op_lon)  # type: ignore[arg-type]
    else:
        try:
            lat, lon = utm_to_latlon(position)
        except Exception:
            return {}
    oid = f"{_NS}:fo:{call_sign}"
    notes = f"FO {call_sign}"
    if op:
        op_id = op.get("operator_id") or op.get("id")
        notes += f"\nLinked to operator #{op_id}"
        if linked:
            notes += " (live position)"
    try:
        notes += f"\n{position.to_mgrs()}"
    except Exception:
        pass
    obj: dict = {
        "id": oid,
        "type": "MARKER",
        "symbol_code": SIDC_FO,
        "affiliation": "FRIENDLY",
        "latitude": lat,
        "longitude": lon,
        "notes": notes,
    }
    if op is not None:
        obj["linked_operator_id"] = op.get("operator_id") or op.get("id")
    return {oid: obj}


# ---------------------------------------------------------------------------
# MortarcalcMapBridge — Front (PyQt6 Leaflet) map
# ---------------------------------------------------------------------------

class MortarcalcMapBridge:
    """Keeps the Front COP map in sync with one MortarCalc window's state."""

    def __init__(
        self,
        window,
        map_view,
        operators_provider: Callable[[], list] | None = None,
    ) -> None:
        self._window = window
        self._map = map_view
        self._operators_provider = operators_provider
        self._objs: dict[str, dict] = {}
        self._torn_down = False

        window.state_changed.connect(self.sync)
        window.closing.connect(self.teardown)
        self.sync()

    def sync(self) -> None:
        if self._torn_down:
            return
        try:
            new_objs = _build_mortar_objects(self._window, self._operators_by_callsign())
        except Exception:
            log.exception("MortarCalc map bridge: failed to build objects")
            return

        for oid, obj in new_objs.items():
            if self._objs.get(oid) != obj:
                try:
                    self._map.add_tactical_object(obj)
                except Exception:
                    log.exception("MortarCalc map bridge: add %s failed", oid)
        for oid in list(self._objs):
            if oid not in new_objs:
                self._remove(oid)
        self._objs = new_objs

    def teardown(self) -> None:
        if self._torn_down:
            return
        self._torn_down = True
        for oid in list(self._objs):
            self._remove(oid)
        self._objs = {}
        try:
            self._window.state_changed.disconnect(self.sync)
        except (TypeError, RuntimeError):
            pass

    def _remove(self, oid: str) -> None:
        try:
            self._map.remove_tactical_object(oid)
        except Exception:
            log.exception("MortarCalc map bridge: remove %s failed", oid)

    def _operators_by_callsign(self) -> dict[str, dict]:
        if self._operators_provider is None:
            return {}
        try:
            ops = self._operators_provider() or []
        except Exception:
            log.exception("MortarCalc map bridge: operator lookup failed")
            return {}
        out: dict[str, dict] = {}
        for op in ops:
            cs = str(op.get("callsign", "")).strip().lower()
            if cs:
                out[cs] = op
        return out


# ---------------------------------------------------------------------------
# MortarcalcWebBridge — Arrow backend HTTP/WS (web map)
# ---------------------------------------------------------------------------

class MortarcalcWebBridge:
    """Syncs MortarCalc state to the Arrow backend so the web map mirrors it.

    Creates / patches / deletes TacticalObject records via the backend REST
    API (which broadcasts them on the ``tactical-object`` WS channel).  Also
    detects SHOT / IN_EFFECT mission-state transitions and broadcasts a
    ``mortar-cop`` WS firing event so the web map and Front can show a toast.

    Parameters
    ----------
    window:
        mortarcalc.gui.main_window.MainWindow instance.
    arrow_client:
        front.client.arrow_client.ArrowClient — must already be authenticated.
    toast_callback:
        Optional callable(msg: str) invoked on the Front side when a group
        transitions into SHOT or IN_EFFECT (so Front shows its own toast
        without waiting for the WS round-trip).
    """

    def __init__(self, window, arrow_client, toast_callback=None) -> None:
        self._window = window
        self._client = arrow_client
        self._toast_cb = toast_callback
        # oid -> backend TacticalObject id
        self._backend_ids: dict[str, int] = {}
        # oid -> last pushed obj (for change detection on updates)
        self._last_objs: dict[str, dict] = {}
        # groups currently in a firing state (SHOT / IN_EFFECT)
        self._firing_groups: set[str] = set()
        self._torn_down = False

        window.state_changed.connect(self.sync)
        window.closing.connect(self.teardown)
        self.sync()

    # ------------------------------------------------------------------
    def sync(self) -> None:
        if self._torn_down:
            return
        try:
            new_objs = _build_mortar_objects(self._window, {})
        except Exception:
            log.exception("MortarCalc web bridge: failed to build objects")
            return

        # Add or update changed objects.
        for oid, obj in new_objs.items():
            if oid in self._backend_ids:
                prev = self._last_objs.get(oid)
                if prev and prev["latitude"] == obj["latitude"] and prev["longitude"] == obj["longitude"]:
                    continue
                try:
                    self._client.patch_tactical_object(
                        self._backend_ids[oid], obj["latitude"], obj["longitude"]
                    )
                    self._last_objs[oid] = obj
                except Exception:
                    log.exception("MortarCalc web bridge: patch %s failed", oid)
            else:
                try:
                    resp = self._client.post_tactical_marker(
                        obj_type=obj["type"],
                        lat=obj["latitude"],
                        lon=obj["longitude"],
                        notes=obj.get("notes", ""),
                        affiliation=obj.get("affiliation", "FRIENDLY"),
                        symbol_code=obj.get("symbol_code", ""),
                    )
                    self._backend_ids[oid] = resp["id"]
                    self._last_objs[oid] = obj
                except Exception:
                    log.exception("MortarCalc web bridge: create %s failed", oid)

        # Remove objects that disappeared.
        for oid in list(self._backend_ids):
            if oid not in new_objs:
                self._remove_backend(oid)

        self._check_firing_state()

    def teardown(self) -> None:
        if self._torn_down:
            return
        self._torn_down = True
        for oid in list(self._backend_ids):
            self._remove_backend(oid)
        # Broadcast ceased-fire for any still-active groups so the web clears
        # its toast state.
        for group in list(self._firing_groups):
            self._client.broadcast_mortar_event("ceased", group=group)
        self._firing_groups.clear()
        try:
            self._window.state_changed.disconnect(self.sync)
        except (TypeError, RuntimeError):
            pass

    # ------------------------------------------------------------------
    def _remove_backend(self, oid: str) -> None:
        bid = self._backend_ids.pop(oid, None)
        self._last_objs.pop(oid, None)
        if bid is None:
            return
        try:
            self._client.delete_tactical_object(bid)
        except Exception:
            log.exception("MortarCalc web bridge: delete %s (id=%s) failed", oid, bid)

    def _check_firing_state(self) -> None:
        from mortarcalc.firemission import MissionState

        mp = getattr(self._window, "mission_panel", None)
        if mp is None:
            return
        active = getattr(mp, "active", {}) or {}

        _FIRING = {MissionState.SHOT, MissionState.IN_EFFECT}
        firing_now: set[str] = set()
        for group_name, fm in active.items():
            if fm is not None and fm.state in _FIRING:
                firing_now.add(group_name)

        # Newly firing groups — broadcast + Front toast.
        for group in firing_now - self._firing_groups:
            fm = active.get(group)
            target = (fm.id if fm else "") or ""
            state_val = fm.state.value if fm else ""
            self._client.broadcast_mortar_event(
                "firing", group=group, target=target, state=state_val
            )
            if self._toast_cb:
                try:
                    self._toast_cb(f"{group} · {target}")
                except Exception:
                    pass

        # Groups that ceased firing.
        for group in self._firing_groups - firing_now:
            self._client.broadcast_mortar_event("ceased", group=group)

        self._firing_groups = firing_now
