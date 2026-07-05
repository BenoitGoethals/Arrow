"""Enforced classification + mandatory-mission tests (backend Phase 1).

Covers the pure helper module, the WebSocket broadcast filter, list filtering by
clearance, the non-admin mission lock, create/ceiling caps, ADMIN-only mission
creation, and the mission-clearance gate.
"""

from __future__ import annotations

import asyncio

import pytest

import backend.storage.database as _db
from backend import classification as C
from backend.storage.models import CotTrack
from backend.websocket.manager import ConnectionManager
from tests.conftest import admin_token, auth, register

# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_names_and_levels():
    assert C.name_for(0) == "UNCLASSIFIED"
    assert C.name_for(4) == "TOP SECRET"
    assert C.name_for(99) == "TOP SECRET"  # clamped
    assert C.level_for("secret") == 3
    assert C.clamp(None) == 0 and C.clamp(9) == 4 and C.clamp(-1) == 0


def test_jdss_mapping():
    assert C.jdss_inbound(3) == 3
    assert C.jdss_outbound(4) == 3  # JDSS has no TOP SECRET
    assert C.jdss_outbound(2) == 2


def test_resolve_default_and_cap():
    class M:
        classification = 2

    class Op:
        clearance = 4

    assert C.resolve_default_and_cap(M(), Op(), None) == 2  # default = mission ceiling
    assert C.resolve_default_and_cap(M(), Op(), 1) == 1
    with pytest.raises(Exception):  # noqa: B017 — HTTPException 403
        C.resolve_default_and_cap(M(), Op(), 3)  # above mission ceiling
    # No mission → ceiling UNCLASSIFIED.
    assert C.resolve_default_and_cap(None, Op(), None) == 0


# ── WebSocket broadcast filter ────────────────────────────────────────────────


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def accept(self):
        pass

    async def send_json(self, msg):
        self.sent.append(msg)


def test_ws_broadcast_filters_by_clearance():
    mgr = ConnectionManager()
    low, high = _FakeWS(), _FakeWS()

    async def scenario():
        await mgr.connect(low, clearance=1)
        await mgr.connect(high, clearance=3)
        # A SECRET(3) element reaches only the cleared socket.
        await mgr.broadcast(
            {"channel": "tactical-object", "data": {"classification": 3}}
        )
        # A system event without a classification reaches everyone.
        await mgr.broadcast({"channel": "presence", "data": {"callsign": "X"}})

    asyncio.run(scenario())
    assert len(high.sent) == 2
    assert len(low.sent) == 1  # only the presence event
    assert low.sent[0]["channel"] == "presence"


# ── List filtering by clearance (global CoT tracks) ───────────────────────────


def test_list_filters_by_clearance(client):
    _, admin_tok, _ = register(client, "ADMIN")  # clearance 4
    cs, op_tok, op_id = register(client, "OPERATOR")  # clearance 0
    client.patch(f"/operators/{op_id}", headers=auth(admin_tok), json={"clearance": 1})

    with _db.SessionLocal() as db:
        db.add(
            CotTrack(
                cot_uid="U0",
                cot_type="a-f-G",
                latitude=1,
                longitude=1,
                classification=0,
            )
        )
        db.add(
            CotTrack(
                cot_uid="S3",
                cot_type="a-h-G",
                latitude=2,
                longitude=2,
                classification=3,
            )
        )
        db.commit()

    seen_op = {
        t["cot_uid"] for t in client.get("/cot/tracks", headers=auth(op_tok)).json()
    }
    seen_admin = {
        t["cot_uid"] for t in client.get("/cot/tracks", headers=auth(admin_tok)).json()
    }
    assert seen_op == {"U0"}  # clearance 1 hides the SECRET track
    assert {"U0", "S3"}.issubset(seen_admin)


# ── Create caps + default = mission ceiling ───────────────────────────────────


def test_create_cap_and_default(client):
    _, admin_tok, _ = register(client, "ADMIN")
    mid = client.post(
        "/missions", headers=auth(admin_tok), json={"name": "OP", "classification": 3}
    ).json()["id"]
    h = auth(admin_tok)
    h["X-Mission-ID"] = str(mid)

    # Above the mission ceiling → 403.
    over = client.post(
        "/tactical-objects",
        headers=h,
        json={"type": "POI", "latitude": 1, "longitude": 1, "classification": 4},
    )
    assert over.status_code == 403, over.text

    # At/below ceiling → ok.
    ok = client.post(
        "/tactical-objects",
        headers=h,
        json={"type": "POI", "latitude": 1, "longitude": 1, "classification": 2},
    )
    assert ok.status_code == 201 and ok.json()["classification"] == 2

    # Omitted → defaults to the mission ceiling.
    dflt = client.post(
        "/tactical-objects",
        headers=h,
        json={"type": "POI", "latitude": 1, "longitude": 1},
    )
    assert dflt.status_code == 201 and dflt.json()["classification"] == 3


# ── Non-admin mission lock ────────────────────────────────────────────────────


def test_non_admin_mission_lock(client):
    _, admin_tok, _ = register(client, "ADMIN")
    a = client.post("/missions", headers=auth(admin_tok), json={"name": "A"}).json()[
        "id"
    ]
    b = client.post("/missions", headers=auth(admin_tok), json={"name": "B"}).json()[
        "id"
    ]
    _, op_tok, op_id = register(client, "OPERATOR")
    client.post(
        f"/missions/{a}/operators",
        headers=auth(admin_tok),
        json={"operator_ids": [op_id]},
    )

    # Operator creates an alert in their locked mission A.
    h = auth(op_tok)
    h["X-Mission-ID"] = str(a)
    assert client.post("/alerts", headers=h, json={"type": "TIC"}).status_code == 201

    # Even asking for mission B, the operator still sees only mission A's data.
    h["X-Mission-ID"] = str(b)
    alerts = client.get("/alerts", headers=h).json()
    assert len(alerts) == 1  # the A alert; the B header was ignored


# ── Mission role + clearance gates ────────────────────────────────────────────


def test_only_admin_creates_missions(client):
    _, bc_tok, _ = register(client, "BATTLE_CAPTAIN")
    assert (
        client.post("/missions", headers=auth(bc_tok), json={"name": "X"}).status_code
        == 403
    )
    tok = admin_token(client)
    assert (
        client.post("/missions", headers=auth(tok), json={"name": "Y"}).status_code
        == 201
    )


def test_reports_and_overlays_inherit_mission_ceiling(client):
    _, admin_tok, _ = register(client, "ADMIN")
    mid = client.post(
        "/missions", headers=auth(admin_tok), json={"name": "OP", "classification": 2}
    ).json()["id"]
    h = auth(admin_tok)
    h["X-Mission-ID"] = str(mid)

    rep = client.post("/reports", headers=h, json={"type": "SPOT", "payload": {}})
    assert rep.status_code == 201 and rep.json()["classification"] == 2

    ov = client.post("/overlays", headers=h, json={"name": "layer", "object_ids": []})
    assert ov.status_code == 201
    assert ov.json()["classification"] == 2 and ov.json()["mission_id"] == mid


def test_mission_clearance_gate_and_assignment(client):
    _, admin_tok, _ = register(client, "ADMIN")
    secret = client.post(
        "/missions",
        headers=auth(admin_tok),
        json={"name": "SECRET OP", "classification": 3},
    ).json()["id"]
    _, op_tok, op_id = register(client, "OPERATOR")
    client.patch(f"/operators/{op_id}", headers=auth(admin_tok), json={"clearance": 1})

    # An under-cleared operator cannot even read the mission…
    assert client.get(f"/missions/{secret}", headers=auth(op_tok)).status_code == 403
    # …and cannot be assigned to it (409 conflict).
    r = client.post(
        f"/missions/{secret}/operators",
        headers=auth(admin_tok),
        json={"operator_ids": [op_id]},
    )
    assert r.status_code == 409, r.text
