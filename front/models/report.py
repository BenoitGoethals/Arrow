from dataclasses import dataclass, field
from typing import Optional


REPORT_PRIORITY = {
    "DRONE_SPOT": "FLASH",
    "CASEVAC": "IMMEDIATE",
    "MEDEVAC": "IMMEDIATE",
    "CAS": "IMMEDIATE",
    "CONTACT": "PRIORITY",
    "SALUTE": "PRIORITY",
    "SITREP": "ROUTINE",
    "ACE": "ROUTINE",
    "CBRN_1": "FLASH",
    "IED": "IMMEDIATE",
}

PRIORITY_COLORS = {
    "FLASH":     "#f85149",
    "IMMEDIATE": "#ff9e64",
    "PRIORITY":  "#d29922",
    "ROUTINE":   "#3fb950",
}

REPORT_ICON = {
    "DRONE_SPOT":  "🛸",
    "CASEVAC":     "🚁",
    "MEDEVAC":     "🚁",
    "CAS":         "✈",
    "CONTACT":     "⚠",
    "SALUTE":      "📋",
    "SITREP":      "📊",
    "ACE":         "📦",
    "CBRN_1":      "☢",
    "IED":         "💣",
}


@dataclass
class Report:
    id: int
    type: str
    sender: str
    timestamp: str
    payload: dict = field(default_factory=dict)
    read: bool = False

    @property
    def priority(self) -> str:
        return REPORT_PRIORITY.get(self.type, "ROUTINE")

    @property
    def priority_color(self) -> str:
        return PRIORITY_COLORS.get(self.priority, "#8b949e")

    @property
    def icon(self) -> str:
        return REPORT_ICON.get(self.type, "📄")
