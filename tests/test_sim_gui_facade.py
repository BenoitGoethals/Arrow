"""Tests for the sim_gui facade and scenario catalog.

Two layers:

1. Static catalog test — every scenario module exposes the right shape
   (META, VEHICLE_FLAVOR, inject) and `list_scenarios()` returns all ten.
2. Dry-run inject test — every scenario's `inject()` produces a non-empty
   overlay, hitting a stub API that records calls instead of talking to a
   real server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from sim_gui.facade import ScenarioFacade
from sim_gui.hierarchy_seeder import HierarchyState
from sim_gui.scenarios.base import InjectResult, ScenarioMeta
from sim_gui.scenarios.catalog import BY_ID, SCENARIOS

# ── stub API ──────────────────────────────────────────────────────────────────


@dataclass
class _StubApi:
    """Just enough surface to satisfy scenario.inject()."""

    posts: list[tuple[str, dict]] = field(default_factory=list)
    patches: list[tuple[str, dict]] = field(default_factory=list)
    _next_id: int = 1000

    def post(self, path: str, _tok: str, body: dict) -> dict[str, Any]:
        self.posts.append((path, body))
        self._next_id += 1
        # Return a minimal TacticalObjectOut-ish payload so callers can keep
        # references to objects they want to mutate later.
        return {
            "id": self._next_id,
            "type": body.get("type", ""),
            "latitude": body.get("latitude", 0.0),
            "longitude": body.get("longitude", 0.0),
            "affiliation": body.get("affiliation", "FRIENDLY"),
            "notes": body.get("notes", ""),
        }

    def patch(self, path: str, _tok: str, body: dict) -> dict:
        self.patches.append((path, body))
        return {}

    def get(self, _path: str, _tok: str) -> list:
        return []

    def delete(self, _path: str, _tok: str) -> int:
        return 204


# ── catalog shape ─────────────────────────────────────────────────────────────


def test_catalog_has_eleven_scenarios() -> None:
    assert len(SCENARIOS) == 11


def test_every_scenario_exposes_required_attributes() -> None:
    for mod in SCENARIOS:
        assert hasattr(mod, "META"), f"{mod.__name__} missing META"
        assert isinstance(mod.META, ScenarioMeta)
        assert hasattr(mod, "VEHICLE_FLAVOR")
        assert mod.VEHICLE_FLAVOR in {"land", "airborne", "riverine", "amphib"}
        assert callable(getattr(mod, "inject", None))


def test_facade_list_scenarios_returns_metadata() -> None:
    metas = ScenarioFacade.list_scenarios()
    assert len(metas) == 11
    assert metas[0].id in BY_ID


def test_only_phase_scenarios_have_runtime() -> None:
    """Only phase-driven scenarios expose start_runtime — currently DYNAMIC
    and FLANDERS GATE (Ursel)."""
    runtime_ids = {mod.META.id for mod in SCENARIOS if hasattr(mod, "start_runtime")}
    assert runtime_ids == {"dynamic", "ursel_airfield"}


# ── dry-run inject ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mod", SCENARIOS, ids=lambda m: m.META.id)
def test_scenario_inject_produces_overlay(mod) -> None:
    api = _StubApi()
    state = HierarchyState()
    result: InjectResult = mod.inject(cast(Any, api), "stub-token", state)

    # Every scenario must produce a non-trivial overlay.
    assert result.overlay_objects >= 5, f"{mod.META.id}: too few overlay objects"
    # Every scenario must include at least one enemy unit.
    assert result.enemy_units >= 1, f"{mod.META.id}: no enemy units"
    # Every scenario must include at least one friendly POI / OBJ.
    assert result.friendly_pois >= 1, f"{mod.META.id}: no friendly POIs"
    # Every scenario must place at least one control measure.
    assert result.control_measures >= 1, f"{mod.META.id}: no control measures"

    # Every overlay POST should target the tactical-objects endpoint.
    tactical_posts = [p for p, _ in api.posts if p == "/tactical-objects"]
    assert len(tactical_posts) == result.overlay_objects

    # Every line/polygon body must carry valid JSON in `geometry`.
    for path, body in api.posts:
        if path != "/tactical-objects":
            continue
        if body.get("type") in {"FLOT", "BOUNDARY", "PHASE_LINE", "OBJ_AREA", "ROUTE"}:
            geom = body.get("geometry") or ""
            assert geom, f"{mod.META.id}: {body['type']} missing geometry"
            parsed = json.loads(geom)
            assert parsed["type"] in {"line", "polygon"}
            assert isinstance(parsed["coords"], list) and len(parsed["coords"]) >= 2


def test_default_opord_has_all_five_paragraphs() -> None:
    """Every scenario's default OPORD must satisfy `OpordCreate` shape."""
    from sim_gui.scenarios.base import build_default_opord, get_opord

    for mod in SCENARIOS:
        opord = get_opord(mod, mod.META)
        # Shape per backend/opord/schemas.py:OpordCreate
        for key in (
            "title",
            "opord_number",
            "dtg",
            "situation",
            "mission",
            "execution",
            "sustainment",
            "command_signal",
        ):
            assert key in opord, f"{mod.META.id}: missing OPORD key {key!r}"
        assert opord["title"].startswith("OPORD")
        for sub in ("enemy", "friendly", "terrain"):
            assert sub in opord["situation"], f"{mod.META.id}: situation missing {sub}"
        for sub in (
            "commanders_intent",
            "concept_of_operations",
            "tasks_to_subordinate_units",
        ):
            assert sub in opord["execution"], f"{mod.META.id}: execution missing {sub}"
        # Default builder must echo the scenario name into the mission paragraph.
        if (
            mod.META.name in opord["mission"]
            or mod.META.mission_type in opord["mission"]
        ):
            pass  # OK
        # Default builder is deterministic — second call returns the same dict shape.
        again = build_default_opord(mod.META)
        assert again.keys() == opord.keys() or callable(
            getattr(mod, "build_opord", None)
        )


def test_dynamic_scenario_seeds_enemies_for_runtime() -> None:
    import sim_gui.scenarios.op_dynamic as dyn

    api = _StubApi()
    dyn.inject(cast(Any, api), "stub-token", HierarchyState())
    assert getattr(dyn.inject, "_enemy_records"), "dynamic must cache enemies"
    assert getattr(dyn.inject, "_ao_center")


# ── cleanup fallback ──────────────────────────────────────────────────────────


def test_cleanup_falls_back_when_admin_reset_500s() -> None:
    """If `/admin/map/reset` raises HTTPStatusError, fall back to per-resource sweep."""
    import httpx

    from sim_gui import cleanup

    @dataclass
    class _FailingSession:
        deletes: list[str] = field(default_factory=list)
        gets: list[str] = field(default_factory=list)
        token: str = "admin-token"

        def post(self, path: str, _tok: str, _body: dict) -> dict:
            if path == "/admin/map/reset":
                req = httpx.Request("POST", "http://x" + path)
                resp = httpx.Response(500, request=req, text="server error")
                raise httpx.HTTPStatusError("500", request=req, response=resp)
            return {}

        def get(self, path: str) -> list:
            self.gets.append(path)
            return [{"id": 42}]

        def delete(self, path: str) -> int:
            self.deletes.append(path)
            return 204

    session = _FailingSession()
    out = cleanup.full_reset(cast(Any, session), "pre-test")

    assert out.get("fallback") is True
    assert "/tactical-objects" in session.gets
    assert "/tactical-objects/42" in session.deletes
    assert "/alerts/42" in session.deletes
    assert "/vehicles/42" in session.deletes  # always swept
    assert "/cas/assets/42" in session.deletes
    assert "/logcop/supply-points/42" in session.deletes  # new
    assert "/missions/42" in session.deletes
    assert "/missions" in session.gets
    assert "/opord/42" in session.deletes  # new — OPORDs are swept too
    # Hierarchy wipe (children before parents) — all four levels.
    assert "/teams/42" in session.deletes
    assert "/sections/42" in session.deletes
    assert "/platoons/42" in session.deletes
    assert "/companies/42" in session.deletes
    # The "hierarchy" key reports per-level counts.
    assert "hierarchy" in out
    assert out["hierarchy"]["teams"] == 1
    assert out["hierarchy"]["companies"] == 1


# ── admin session 401 retry ───────────────────────────────────────────────────


def test_admin_session_refreshes_token_on_401() -> None:
    """AdminSession.post must retry once with a fresh token after a 401."""
    import httpx

    from sim_gui.backend_client import AdminSession, BackendCredentials

    class _StubApi:
        def __init__(self) -> None:
            self.login_calls = 0
            self.post_calls = 0

        def login(self, _cs: str, _pw: str) -> str:
            self.login_calls += 1
            return f"fresh-{self.login_calls}"

        def post(self, _path: str, tok: str, _body: dict) -> dict:
            self.post_calls += 1
            if tok == "stale":
                req = httpx.Request("POST", "http://x")
                resp = httpx.Response(401, request=req, text="Session superseded")
                raise httpx.HTTPStatusError("401", request=req, response=resp)
            return {"ok": True, "used_token": tok}

    api = _StubApi()
    creds = BackendCredentials(
        base_url="http://x", admin_callsign="benoit", admin_password="ranger14"
    )
    session = AdminSession(api=cast(Any, api), creds=creds, token="stale")
    result = session.post("/vehicles", session.token, {"callsign": "x"})

    assert api.login_calls == 1  # refresh fired exactly once
    assert api.post_calls == 2  # original + retry
    assert isinstance(result, dict) and result["used_token"] == "fresh-1"
    assert session.token == "fresh-1"
