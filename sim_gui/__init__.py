"""Arrow Scenario Simulator — PyQt6 facade GUI.

Launches scripted SOF scenarios against a running Arrow backend. Each scenario
wipes the server clean, seeds the 3 PARA / SOR battalion, populates vehicles,
opens a mission, and injects tactical overlays. See `sim_gui.facade` for the
orchestrator and `sim_gui.scenarios.catalog` for the ten available scenarios.
"""

__all__ = ["facade", "scenarios"]
