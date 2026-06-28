"""The portable layer-export envelope shared by every layer kind.

One JSON shape wraps an overlay, a KML layer, or an OSINT board so the same
serialization is used by the standalone ``/layers`` export/import endpoints and
by the OPORD "freeze a self-contained copy" attachment path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

LAYER_EXPORT_VERSION = "1"
VALID_KINDS = {"OVERLAY", "KML", "OSINT"}


class LayerEnvelope(BaseModel):
    """A portable, self-contained export of one layer artifact."""

    arrow_layer_export: str
    kind: str
    name: str
    exported_at: datetime
    exported_by: int
    payload: dict[str, Any] = Field(default_factory=dict)


def make_envelope(
    kind: str, name: str, operator_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    """Build an envelope dict. Run through ``jsonable_encoder`` before persisting
    or returning it, since kind-specific payloads can embed ``datetime`` values."""
    return {
        "arrow_layer_export": LAYER_EXPORT_VERSION,
        "kind": kind,
        "name": name,
        "exported_at": datetime.now(timezone.utc),
        "exported_by": operator_id,
        "payload": payload,
    }
