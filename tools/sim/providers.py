"""Built-in CoT message providers.

All four built-in providers are auto-registered via ``@register_provider`` the
moment this module is imported.  ``sim/__init__.py`` imports it so registration
happens before ``SimFrame`` is created.

Adding a new built-in provider
-------------------------------
1. Subclass ``CotMessageProvider``, set ``category``, implement ``get_messages``.
2. Decorate with ``@register_provider``.
That's it — the category filter in the UI picks it up automatically.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .domain import CotEntry
from .registry import CotMessageProvider, register_provider


# ── shorthand constructor used inside provider lists ─────────────────────────

def _e(**kw: object) -> CotEntry:
    return CotEntry(**kw)  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Friendly
# ─────────────────────────────────────────────────────────────────────────────

@register_provider
class FriendlyProvider(CotMessageProvider):
    category = "Friendly"

    def get_messages(self) -> list[CotEntry]:
        return [
            _e(category="Friendly", label="Infantry — ALPHA-1",
               uid="SIM.ALPHA-1",  cot_type="a-f-G-U-C-I",  callsign="ALPHA-1",
               lat=50.8503, lon=4.3517, hae=80.0,  speed=1.4,   course=90.0,
               team="Alpha",  role="Team Member"),
            _e(category="Friendly", label="Infantry — BRAVO-2",
               uid="SIM.BRAVO-2",  cot_type="a-f-G-U-C-I",  callsign="BRAVO-2",
               lat=50.8520, lon=4.3490, hae=75.0,  speed=0.0,   course=180.0,
               team="Bravo",  role="Team Member"),
            _e(category="Friendly", label="Infantry — CHARLIE-3",
               uid="SIM.CHARLIE-3",cot_type="a-f-G-U-C-I",  callsign="CHARLIE-3",
               lat=50.8508, lon=4.3475, hae=77.0,  speed=2.1,   course=45.0,
               team="Charlie", role="Team Member"),
            _e(category="Friendly", label="Battle Captain — CP EAGLE",
               uid="SIM.CP-EAGLE", cot_type="a-f-G-U-C-O",  callsign="CP-EAGLE",
               lat=50.8480, lon=4.3550, hae=85.0,  speed=0.0,   course=0.0,
               team="HQ",     role="Battle Captain"),
            _e(category="Friendly", label="Armour — TITAN-1",
               uid="SIM.TITAN-1",  cot_type="a-f-G-U-C-A",  callsign="TITAN-1",
               lat=50.8490, lon=4.3460, hae=70.0,  speed=5.6,   course=45.0,
               team="Armour", role="Team Member"),
            _e(category="Friendly", label="Recon — GHOST-3",
               uid="SIM.GHOST-3",  cot_type="a-f-G-U-C-R",  callsign="GHOST-3",
               lat=50.8540, lon=4.3600, hae=90.0,  speed=3.0,   course=270.0,
               team="Recon",  role="Team Member"),
            _e(category="Friendly", label="Combat Officer — ACTUAL",
               uid="SIM.ACTUAL",   cot_type="a-f-G-U-C-O",  callsign="ACTUAL",
               lat=50.8498, lon=4.3533, hae=83.0,  speed=0.0,   course=0.0,
               team="HQ",     role="Commander"),
            _e(category="Friendly", label="Helicopter — VIPER-1",
               uid="SIM.VIPER-1",  cot_type="a-f-A-M-H",    callsign="VIPER-1",
               lat=50.8600, lon=4.3400, hae=300.0, speed=55.0,  course=135.0,
               team="Air",    role="Pilot"),
            _e(category="Friendly", label="Fixed-Wing — EAGLE-11",
               uid="SIM.EAGLE-11", cot_type="a-f-A-M-F",    callsign="EAGLE-11",
               lat=50.8700, lon=4.3200, hae=1500.0,speed=200.0, course=220.0,
               team="Air",    role="Pilot"),
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Hostile
# ─────────────────────────────────────────────────────────────────────────────

@register_provider
class HostileProvider(CotMessageProvider):
    category = "Hostile"

    def get_messages(self) -> list[CotEntry]:
        def _h(**kw: object) -> CotEntry:
            return _e(category="Hostile", team="", role="", **kw)

        return [
            _h(label="Infantry — HOT-INF-1",
               uid="SIM.HOT-INF-1",  cot_type="a-h-G-U-C-I",
               lat=50.8450, lon=4.3480, hae=75.0, speed=0.0, course=0.0),
            _h(label="Armour T-72 — HOT-ARM-1",
               uid="SIM.HOT-ARM-1",  cot_type="a-h-G-U-C-A",
               lat=50.8430, lon=4.3510, hae=70.0, speed=4.2, course=315.0),
            _h(label="Mech Infantry — HOT-MECH-1",
               uid="SIM.HOT-MECH-1", cot_type="a-h-G-U-C-I-Z",
               lat=50.8420, lon=4.3530, hae=72.0, speed=6.0, course=350.0),
            _h(label="Artillery — HOT-ARTY-1",
               uid="SIM.HOT-ARTY-1", cot_type="a-h-G-U-C-F",
               lat=50.8400, lon=4.3600, hae=80.0, speed=0.0, course=0.0),
            _h(label="Air Defence — HOT-AD-1",
               uid="SIM.HOT-AD-1",   cot_type="a-h-G-U-C-D",
               lat=50.8410, lon=4.3580, hae=78.0, speed=0.0, course=0.0),
            _h(label="Sniper — HOT-SNI-1",
               uid="SIM.HOT-SNI-1",  cot_type="a-h-G-U-C-I-S",
               lat=50.8460, lon=4.3470, hae=82.0, speed=0.0, course=0.0),
            _h(label="Vehicle — HOT-VEH-1",
               uid="SIM.HOT-VEH-1",  cot_type="a-h-G-E-V",
               lat=50.8440, lon=4.3495, hae=68.0, speed=8.3, course=260.0),
            _h(label="Recon — HOT-REC-1",
               uid="SIM.HOT-REC-1",  cot_type="a-h-G-U-C-R",
               lat=50.8455, lon=4.3510, hae=73.0, speed=3.5, course=200.0),
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Unknown
# ─────────────────────────────────────────────────────────────────────────────

@register_provider
class UnknownProvider(CotMessageProvider):
    category = "Unknown"

    def get_messages(self) -> list[CotEntry]:
        return [
            _e(category="Unknown", label="Unknown Ground — UNK-1",
               uid="SIM.UNK-1", cot_type="a-u-G", callsign="UNK-1",
               lat=50.8465, lon=4.3525, hae=74.0, speed=2.0, course=120.0),
            _e(category="Unknown", label="Unknown Ground — UNK-2",
               uid="SIM.UNK-2", cot_type="a-u-G", callsign="UNK-2",
               lat=50.8472, lon=4.3512, hae=76.0, speed=1.1, course=230.0),
        ]


# ─────────────────────────────────────────────────────────────────────────────
# POI / Neutral
# ─────────────────────────────────────────────────────────────────────────────

@register_provider
class PoiProvider(CotMessageProvider):
    category = "POI"

    def get_messages(self) -> list[CotEntry]:
        def _p(**kw: object) -> CotEntry:
            return _e(category="POI", cot_type="a-n-G-I-N",
                      speed=0.0, course=0.0, **kw)

        return [
            _p(label="Checkpoint — CP-1",
               uid="SIM.POI-CP-1",   callsign="CP-1",
               lat=50.8470, lon=4.3540, hae=76.0,
               team="Control",   role="CP"),
            _p(label="Medical Aid Station — BAS-1",
               uid="SIM.POI-MED-1",  callsign="BAS-1",
               lat=50.8490, lon=4.3500, hae=77.0,
               team="Medical",   role="Medic"),
            _p(label="Landing Zone — LZ-ALPHA",
               uid="SIM.POI-LZ-1",   callsign="LZ-ALPHA",
               lat=50.8550, lon=4.3560, hae=85.0,
               team="Aviation",  role="LZ"),
            _p(label="Ammo Point — AMMO-1",
               uid="SIM.POI-AMMO-1", callsign="AMMO-1",
               lat=50.8530, lon=4.3480, hae=81.0,
               team="Logistics", role="Supply"),
        ]


# ─────────────────────────────────────────────────────────────────────────────
# File-based provider (manual registration)
# ─────────────────────────────────────────────────────────────────────────────

class JsonFileCotProvider(CotMessageProvider):
    """Load CoT entries from a JSON file (array of ``CotEntry``-compatible dicts).

    Example ``extra.json``::

        [{"uid":"X.1","cot_type":"a-f-G-U-C","label":"My unit",
          "category":"Custom","callsign":"X-1","lat":50.0,"lon":4.0}]

    Register before ``SimFrame`` is created::

        from tools.sim import registry, JsonFileCotProvider
        registry.register(JsonFileCotProvider("extra.json", category="Extra"))
    """

    def __init__(self, path: str | Path, category: str = "Custom") -> None:
        self._path    = Path(path)
        self.category = category  # type: ignore[assignment]

    def get_messages(self) -> list[CotEntry]:
        _fields = {f.name for f in dataclasses.fields(CotEntry)}
        try:
            items: list[dict] = json.loads(self._path.read_text())
        except Exception:
            return []
        entries: list[CotEntry] = []
        for item in items:
            try:
                entries.append(CotEntry(**{k: v for k, v in item.items()
                                           if k in _fields}))
            except (TypeError, ValueError):
                pass
        return entries
