from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Track:
    id: str
    callsign: str
    lat: float
    lon: float
    heading: Optional[float] = None
    speed: Optional[float] = None
    altitude: Optional[float] = None
    sidc: str = "10031000000000000000"
    unit: str = ""
    echelon: str = ""
    online: bool = True
    last_seen: str = ""
    trail: list = field(default_factory=list)
