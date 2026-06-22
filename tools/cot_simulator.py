#!/usr/bin/env python3
"""
Arrow CoT Simulator — entry point.

Run
---
  uv run arrow-cot-sim
  uv run python tools/cot_simulator.py [--backend http://host:6001]

Adding extra CoT messages
-------------------------
Register a provider before main() launches the frame::

    from tools.sim import registry, CotMessageProvider, CotEntry

    class MyProvider(CotMessageProvider):
        category = "Custom"
        def get_messages(self) -> list[CotEntry]:
            return [CotEntry(uid="X.1", cot_type="a-f-G-U-C",
                             label="My unit", category="Custom",
                             callsign="X-1", lat=50.0, lon=4.0)]

    registry.register(MyProvider())

Or load from a JSON file::

    from tools.sim import registry, JsonFileCotProvider
    registry.register(JsonFileCotProvider("extra.json", category="Extra"))
"""

from __future__ import annotations

import argparse
from pathlib import Path

import wx

from tools.sim import SimFrame, JsonFileCotProvider, registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Arrow CoT Simulator (wxPython)")
    parser.add_argument(
        "--backend", default="http://localhost:6001", help="Arrow backend base URL"
    )
    args = parser.parse_args()

    # Optional: load extra CoT messages from a JSON file at startup.
    extra = Path("cot_extra.json")
    if extra.exists():
        registry.register(JsonFileCotProvider(extra, category="Extra"))

    wx_app = wx.App(False)
    SimFrame(args.backend)
    wx_app.MainLoop()


if __name__ == "__main__":
    main()
