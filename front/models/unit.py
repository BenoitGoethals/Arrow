from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class Operator:
    id: int
    callsign: str
    rank: str = ""
    role: str = "OPERATOR"
    online: bool = False
    lat: Optional[float] = None
    lon: Optional[float] = None
    last_seen: Optional[str] = None
    team_name: str = ""
    section_name: str = ""
    platoon_name: str = ""


@dataclass
class Team:
    id: int
    name: str
    operators: List[Operator] = field(default_factory=list)

    @property
    def online_count(self) -> int:
        return sum(1 for o in self.operators if o.online)


@dataclass
class Section:
    id: int
    name: str
    teams: List[Team] = field(default_factory=list)

    @property
    def online_count(self) -> int:
        return sum(t.online_count for t in self.teams)

    @property
    def total_count(self) -> int:
        return sum(len(t.operators) for t in self.teams)


@dataclass
class Platoon:
    id: int
    name: str
    sections: List[Section] = field(default_factory=list)

    @property
    def online_count(self) -> int:
        return sum(s.online_count for s in self.sections)

    @property
    def total_count(self) -> int:
        return sum(s.total_count for s in self.sections)


@dataclass
class Company:
    id: int
    name: str
    platoons: List[Platoon] = field(default_factory=list)

    @property
    def online_count(self) -> int:
        return sum(p.online_count for p in self.platoons)

    @property
    def total_count(self) -> int:
        return sum(p.total_count for p in self.platoons)
