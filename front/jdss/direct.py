"""Pure JDSS-gateway protocol core — no Qt, no Arrow backend, no I/O state.

Payload builders (APP-6D compliant, matching ``backend/jdss/bridge.py``), the
inbound-event filter and the event normaliser live here as plain functions so the
Qt client (``front.jdss.client``) is a thin wrapper and the protocol logic is
unit-testable without a display or a running gateway.

Wire facts (JDSSArrow ``/ws/events``): each message frame is FLAT —
``{direction, type, originator_id, callsign, message_id, classification, body}`` —
where ``direction`` is ``"received"`` for coalition traffic and ``"sent"`` for
messages this gateway node originated. ``snapshot`` / ``heartbeat`` frames carry no
message body.
"""

from __future__ import annotations

from typing import Any

# Arrow affiliation → APP-6D StandardIdentity digit (same table as the backend bridge).
AFFILIATION_TO_IDENTITY: dict[str, int] = {
    "FRIENDLY": 3,
    "FRIEND": 3,
    "ASSUMED_FRIEND": 2,
    "NEUTRAL": 4,
    "SUSPECT": 5,
    "HOSTILE": 6,
    "ENEMY": 6,
    "UNKNOWN": 1,
    "PENDING": 0,
}

# Inverse, for labelling inbound contacts.
IDENTITY_TO_AFFILIATION: dict[int, str] = {
    0: "UNKNOWN",
    1: "UNKNOWN",
    2: "FRIENDLY",
    3: "FRIENDLY",
    4: "NEUTRAL",
    5: "HOSTILE",
    6: "HOSTILE",
}

#: StandardIdentity digit for a friendly own-force element.
IDENTITY_FRIEND = 3

#: ``direction`` values that mean "a coalition peer sent this" (ingest these).
INBOUND_DIRECTIONS = frozenset({"received", "in"})


def affiliation_to_identity(affiliation: str | None, type_: str | None = None) -> int:
    """Map an Arrow affiliation (with an ENEMY-type fallback) to an APP-6D identity digit."""
    aff = (affiliation or "").upper()
    if aff in AFFILIATION_TO_IDENTITY:
        return AFFILIATION_TO_IDENTITY[aff]
    if (type_ or "").upper() == "ENEMY":
        return AFFILIATION_TO_IDENTITY["HOSTILE"]
    return AFFILIATION_TO_IDENTITY["UNKNOWN"]


def ws_url(base_url: str) -> str:
    """``http(s)://host:port`` → ``ws(s)://host:port/ws/events``."""
    return base_url.rstrip("/").replace("http", "ws", 1) + "/ws/events"


# ── Outbound payload builders (Front → JDSS ``/api/publish/*``) ────────────────


def presence_payload(
    lat: float,
    lon: float,
    callsign: str,
    *,
    identity: int = IDENTITY_FRIEND,
    battery_pct: int | None = None,
    sidc: str | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "callsign": callsign,
        "battery_pct": battery_pct,
        "identity": identity,
    }
    if sidc:
        payload["sidc"] = sidc
    return payload


def contact_payload(
    lat: float,
    lon: float,
    description: str,
    *,
    identity: int,
    callsign: str | None = None,
    sidc: str | None = None,
    strength: int | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "description": description,
        "identity": identity,
    }
    if callsign:
        payload["callsign"] = callsign
    if sidc:
        payload["sidc"] = sidc
    if strength is not None:
        payload["strength"] = strength
    return payload


def chat_payload(text: str, recipient: str = "all") -> dict:
    return {"text": text, "recipient": recipient}


# ── Inbound handling (JDSS → Front) ───────────────────────────────────────────


def is_inbound(evt: dict, own_node_id: str | None = None) -> bool:
    """True if ``evt`` is a coalition message to render.

    Skips ``sent``/``snapshot``/``heartbeat`` frames and anything this gateway node
    originated (``originator_id == own_node_id``) so Front never echoes its own
    published data back onto its map.
    """
    if evt.get("direction") not in INBOUND_DIRECTIONS:
        return False
    if own_node_id and evt.get("originator_id") == own_node_id:
        return False
    return True


def normalize_event(evt: dict) -> dict | None:
    """Flatten a live ``/ws/events`` message frame into a compact view.

    Returns ``None`` for non-message frames (snapshot / heartbeat / unknown).
    """
    if evt.get("direction") in ("snapshot", "heartbeat", None):
        return None
    body = evt.get("body") or {}
    loc = body.get("location") or {}
    identity = body.get("identity")
    affiliation = (
        IDENTITY_TO_AFFILIATION.get(identity, "UNKNOWN")
        if isinstance(identity, int)
        else "UNKNOWN"
    )
    return {
        "message_id": evt.get("message_id"),
        "type": evt.get("type") or body.get("type"),
        "originator_id": evt.get("originator_id"),
        "callsign": evt.get("callsign") or body.get("callsign"),
        "identity": identity,
        "affiliation": affiliation,
        "lat": loc.get("lat"),
        "lon": loc.get("lon"),
        "text": body.get("text"),
        "description": body.get("description"),
        "sidc": body.get("sidc"),
        "body": body,
    }
