"""Mirror MortarCalc FDC pieces / FOs / targets onto the Arrow Front COP map.

While a MortarCalc window is open, its platoon (mortar pieces), forward
observers and active/planned targets are drawn as tactical objects on the
Front tactical map. When the FDC window closes, every mirrored marker is
removed again — the COP map is left exactly as it was.

Forward Observers are *linked to Arrow operators*: when an FO's call sign
matches a live operator's call sign, the FO marker is pinned to that
operator's live GPS position (so the FDC FO and the tracked operator are the
same point on the map) and the link is shown in the marker popup.

This bridge lives entirely on the Front side; MortarCalc only exposes two
generic Qt signals (`state_changed`, `closing`) and stays standalone.
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


class MortarcalcMapBridge:
    """Keeps the Front COP map in sync with one MortarCalc window's state."""

    def __init__(
        self,
        window,
        map_view,
        operators_provider: Callable[[], list] | None = None,
    ) -> None:
        """
        window            -- mortarcalc.gui.main_window.MainWindow
        map_view          -- front.map.view.MapView (add/remove_tactical_object)
        operators_provider-- callable returning the current list of live
                             operator dicts (callsign + latitude/longitude),
                             used to link FOs to operators. May be None.
        """
        self._window = window
        self._map = map_view
        self._operators_provider = operators_provider
        # id -> last pushed object dict (so we only re-push on change)
        self._objs: dict[str, dict] = {}
        self._torn_down = False

        window.state_changed.connect(self.sync)
        window.closing.connect(self.teardown)
        # Initial mirror.
        self.sync()

    # ------------------------------------------------------------------
    def sync(self) -> None:
        """Re-mirror the FDC state; add/update/remove COP markers by diff."""
        if self._torn_down:
            return
        try:
            new_objs = self._build_objects()
        except Exception:
            log.exception("MortarCalc bridge: failed to build objects")
            return

        # Add or update changed objects.
        for oid, obj in new_objs.items():
            if self._objs.get(oid) != obj:
                try:
                    self._map.add_tactical_object(obj)
                except Exception:
                    log.exception("MortarCalc bridge: add %s failed", oid)
        # Remove objects that disappeared.
        for oid in list(self._objs):
            if oid not in new_objs:
                self._remove(oid)
        self._objs = new_objs

    def teardown(self) -> None:
        """Remove every mirrored marker; safe to call more than once."""
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

    # ------------------------------------------------------------------
    def _remove(self, oid: str) -> None:
        try:
            self._map.remove_tactical_object(oid)
        except Exception:
            log.exception("MortarCalc bridge: remove %s failed", oid)

    def _operators_by_callsign(self) -> dict[str, dict]:
        if self._operators_provider is None:
            return {}
        try:
            ops = self._operators_provider() or []
        except Exception:
            log.exception("MortarCalc bridge: operator lookup failed")
            return {}
        out: dict[str, dict] = {}
        for op in ops:
            cs = str(op.get("callsign", "")).strip().lower()
            if cs:
                out[cs] = op
        return out

    def _build_objects(self) -> dict[str, dict]:
        from mortarcalc.geo import utm_to_latlon

        peloton = getattr(self._window, "peloton", None)
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
        ops = self._operators_by_callsign()
        for o in getattr(peloton, "observers", []):
            objs.update(self._fo_object(o.call_sign, o.position, ops, utm_to_latlon))

        # ---- Targets: active fire missions + planned fire-plan targets -----
        mp = getattr(self._window, "mission_panel", None)
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
            # Also mirror the FO that owns this mission (in case it is not a
            # persistent platoon observer).
            obs = getattr(fm, "observer", None)
            if obs is not None:
                objs.update(
                    self._fo_object(obs.call_sign, obs.position, ops, utm_to_latlon)
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

    def _fo_object(self, call_sign, position, ops, utm_to_latlon) -> dict[str, dict]:
        """Build the {id: obj} for one FO, linking to an operator if matched."""
        op = ops.get(str(call_sign).strip().lower())
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
        obj = {
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
