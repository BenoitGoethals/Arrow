"""Scenario facade — the single entry point the GUI calls into.

`ScenarioFacade.run(scenario_id, progress)` executes the canonical pipeline:

    1. cleanup the backend (`/admin/map/reset`)
    2. seed the 3 PARA / SOR battalion tree
    3. register every operator from the ORBAT
    4. attach one vehicle per rifle section
    5. create + start a mission named after the scenario
    6. inject the scenario's tactical overlay
    7. (dynamic scenario only) hand the runtime hook + stop event back

It also exposes `list_scenarios()` for the GUI's left-pane list.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType

from sim_gui import cleanup as cleanup_mod
from sim_gui import hierarchy_seeder, vehicle_seeder
from sim_gui.backend_client import AdminSession, BackendCredentials
from sim_gui.hierarchy_seeder import HierarchyState
from sim_gui.scenarios.base import InjectResult, ScenarioMeta, get_opord
from sim_gui.scenarios.catalog import BY_ID, SCENARIOS

log = logging.getLogger("sim.facade")


ProgressCallback = Callable[[str, str], None]
"""progress(step, message) — step is one of the PIPELINE constants below."""


# Pipeline step labels (also used by the Qt progress bar to compute %).
PIPELINE = [
    "cleanup",
    "hierarchy",
    "operators",
    "vehicles",
    "mission",
    "opord",
    "overlay",
    "done",
]


@dataclass(slots=True)
class RunResult:
    scenario_id: str
    scenario_name: str
    mission_id: int | None
    inject: InjectResult
    hierarchy: dict[str, int] = field(default_factory=dict)
    vehicles: int = 0
    opord_id: int | None = None


def _noop(_step: str, _msg: str) -> None: ...


class ScenarioFacade:
    def __init__(self, session: AdminSession) -> None:
        self._session = session
        self._state: HierarchyState | None = None
        self._current_module: ModuleType | None = None
        self._stop_event: threading.Event | None = None

    @classmethod
    def connect(cls, creds: BackendCredentials) -> ScenarioFacade:
        return cls(AdminSession.open(creds))

    @property
    def session(self) -> AdminSession:
        return self._session

    # ── public surface ────────────────────────────────────────────────────

    @staticmethod
    def list_scenarios() -> list[ScenarioMeta]:
        return [s.META for s in SCENARIOS]

    def get_scenario(self, scenario_id: str) -> ModuleType:
        if scenario_id not in BY_ID:
            raise KeyError(f"unknown scenario_id: {scenario_id}")
        return BY_ID[scenario_id]

    def run(
        self,
        scenario_id: str,
        progress: ProgressCallback | None = None,
    ) -> RunResult:
        progress = progress or _noop
        scenario = self.get_scenario(scenario_id)
        meta: ScenarioMeta = scenario.META
        self._current_module = scenario

        progress("cleanup", f"resetting backend (snapshot pre-{meta.id})")
        cleanup_mod.full_reset(self._session, f"pre-{meta.id}")

        progress("hierarchy", "seeding 3 PARA / SOR ORBAT")
        state = hierarchy_seeder.seed_hierarchy(self._session)

        progress("operators", f"registering {state.total_operators} operators")
        hierarchy_seeder.register_operators(self._session, state)

        progress("vehicles", f"attaching vehicles ({scenario.VEHICLE_FLAVOR})")
        vehicles = vehicle_seeder.attach_vehicles(
            self._session,
            state,
            flavor=scenario.VEHICLE_FLAVOR,
        )

        progress("mission", f"creating mission '{meta.name}'")
        mid = self._session.create_mission(
            self._session.token,
            name=meta.name,
            description=meta.summary,
            map_center_lat=meta.aor_center[0],
            map_center_lng=meta.aor_center[1],
            map_zoom=meta.map_zoom,
        )

        progress("opord", f"publishing OPORD for {meta.name}")
        opord_id = self._publish_opord(scenario, meta)

        progress("overlay", "injecting tactical overlay")
        inject_result = scenario.inject(self._session, self._session.token, state)

        progress(
            "done",
            f"{inject_result.overlay_objects} overlay objects, "
            f"{inject_result.enemy_units} enemies, "
            f"{inject_result.alerts} alerts, "
            f"{inject_result.reports} reports",
        )

        self._state = state
        return RunResult(
            scenario_id=meta.id,
            scenario_name=meta.name,
            mission_id=mid,
            inject=inject_result,
            hierarchy={
                "companies": len(state.companies),
                "platoons": len(state.platoons),
                "sections": len(state.sections),
                "teams": len(state.teams),
                "operators": state.total_operators,
            },
            vehicles=len(vehicles),
            opord_id=opord_id,
        )

    # ── OPORD publishing ─────────────────────────────────────────────────

    def _publish_opord(self, scenario, meta: ScenarioMeta) -> int | None:
        """POST the OPORD, then attempt to publish it. Returns the id (or None)."""
        body = get_opord(scenario, meta)
        try:
            resp = self._session.post("/opord", self._session.token, body)
        except Exception as e:
            log.warning("OPORD post failed: %s", e)
            return None
        if not isinstance(resp, dict) or "id" not in resp:
            return None
        opord_id = int(resp["id"])
        # Best-effort publish — non-fatal if the backend rejects it.
        try:
            self._session.post(f"/opord/{opord_id}/publish", self._session.token, {})
        except Exception:
            pass
        return opord_id

    # ── dynamic-scenario runtime ──────────────────────────────────────────

    def has_runtime(self) -> bool:
        return hasattr(self._current_module, "start_runtime")

    def start_runtime(self, log_cb: Callable[[str], None]) -> threading.Event:
        """Spawn the dynamic scenario's runtime loop in a daemon thread.

        Returns a `threading.Event` the caller can set to stop the loop.
        """
        if (
            self._current_module is None
            or not self.has_runtime()
            or self._state is None
        ):
            raise RuntimeError(
                "no runtime available — call run() with a dynamic scenario"
            )
        stop = threading.Event()
        self._stop_event = stop
        mod = self._current_module
        state = self._state
        session = self._session

        def _target() -> None:
            try:
                mod.start_runtime(session, session.token, state, stop, log_cb)
            except Exception as e:
                log.exception("dynamic runtime crashed: %s", e)
                log_cb(f"runtime crashed: {e}")

        t = threading.Thread(target=_target, name="sim-dynamic", daemon=True)
        t.start()
        return stop

    def stop_runtime(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
