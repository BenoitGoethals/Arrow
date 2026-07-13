#!/usr/bin/env python3
"""
Arrow Simulator — 1st Battalion, 75th Ranger Regiment
======================================================
Bootstraps a full-strength Ranger battalion via the Arrow REST API:

  • 5 companies  : HHC + Alpha, Bravo, Charlie, Delta
  • 22 platoons, 54 sections, 120 teams
  • ~422 operators, all assigned to their correct team
  • All operators created with password: ranger14

Arrow roles assigned:
  ADMIN          → BN CO (HENDERSON), BN CSM (WHITFIELD)
  BATTLE_CAPTAIN → Company COs, BN XO, staff officers (S1–S6, FSO, PA,
                   platoon leaders, weapons PLT leaders)
  OPERATOR       → everyone else

Idempotent: re-running skips already-existing companies / operators.

Usage:
  uv run python simulate_ranger_bn.py
  uv run python simulate_ranger_bn.py --backend http://192.168.1.10:6001
  uv run python simulate_ranger_bn.py --reset   # delete BN companies & operators, rebuild
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
from typing import Any

import httpx
import sim_utils

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Ranger Bn hierarchy simulator")
parser.add_argument(
    "--backend",
    default=sim_utils.load_saved_backend() or "https://78.21.255.210:6200/api",
)
parser.add_argument("--seed-admin", default="benoit")
parser.add_argument(
    "--seed-admin-password", default="ranger14")
parser.add_argument("--mission-name", default="Operation Bastogne")
parser.add_argument(
    "--reset",
    action="store_true",
    help="Delete existing 1-75 RGR companies and operators, then rebuild",
)
ARGS = parser.parse_args()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rbn")

BASE = ARGS.backend.rstrip("/")
PASSWORD = "ranger14"

# ── Name pools ────────────────────────────────────────────────────────────────

_FIRST = [
    "James",
    "Robert",
    "Michael",
    "William",
    "David",
    "Joseph",
    "Thomas",
    "Charles",
    "Christopher",
    "Daniel",
    "Ryan",
    "Eric",
    "Kevin",
    "Brian",
    "Jason",
    "Marcus",
    "Kyle",
    "Tyler",
    "Adam",
    "Nathan",
    "Justin",
    "Joshua",
    "Cody",
    "Travis",
    "Garrett",
    "Shane",
    "Derek",
    "Caleb",
    "Luke",
    "Cameron",
    "Dylan",
    "Hunter",
    "Logan",
    "Brandon",
    "Austin",
    "Aaron",
    "Connor",
    "Mason",
    "Ethan",
    "Samuel",
    "Andrew",
    "Jonathan",
    "Nicholas",
    "Timothy",
    "Patrick",
    "Scott",
    "Benjamin",
    "Matthew",
    "Stephen",
    "Bradley",
    "Raymond",
    "Gregory",
    "Donald",
    "Richard",
    "Anthony",
    "Frank",
    "Steven",
    "Mark",
    "Paul",
    "Larry",
    "Jerry",
    "Dennis",
    "Gerald",
    "Carl",
    "Harold",
    "Walter",
    "Jose",
    "Henry",
    "Douglas",
    "Peter",
    "Keith",
    "Roger",
    "Terry",
    "Sean",
    "Jesse",
    "Randy",
    "Lawrence",
    "Bobby",
    "Dean",
    "Eddie",
    "Fernando",
    "Juan",
    "Carlos",
    "Miguel",
    "Alejandro",
    "Rafael",
    "Diego",
    "Antonio",
    "Luis",
    "Roberto",
    "Manuel",
    "Sarah",
    "Jennifer",
    "Melissa",
    "Amanda",
    "Ashley",
    "Nicole",
    "Rachel",
    "Lauren",
    "Emily",
    "Angela",
    "Rebecca",
    "Katherine",
    "Michelle",
    "Christine",
]
_LAST = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
    "Lee",
    "Perez",
    "Thompson",
    "White",
    "Harris",
    "Sanchez",
    "Clark",
    "Ramirez",
    "Lewis",
    "Robinson",
    "Walker",
    "Young",
    "Allen",
    "King",
    "Wright",
    "Scott",
    "Torres",
    "Nguyen",
    "Hill",
    "Flores",
    "Green",
    "Adams",
    "Nelson",
    "Baker",
    "Hall",
    "Rivera",
    "Campbell",
    "Mitchell",
    "Carter",
    "Roberts",
    "Gomez",
    "Phillips",
    "Evans",
    "Turner",
    "Diaz",
    "Parker",
    "Cruz",
    "Edwards",
    "Collins",
    "Reyes",
    "Stewart",
    "Morris",
    "Morgan",
    "Reed",
    "Cook",
    "Bell",
    "Murphy",
    "Bailey",
    "Cooper",
    "Richardson",
    "Cox",
    "Howard",
    "Ward",
    "Patterson",
    "Gray",
    "Watson",
    "Brooks",
    "Kelly",
    "Sanders",
    "Price",
    "Bennett",
    "Wood",
    "Barnes",
    "Ross",
    "Henderson",
    "Coleman",
    "Jenkins",
    "Perry",
    "Powell",
    "Long",
    "Hughes",
    "Washington",
    "Butler",
    "Simmons",
    "Foster",
    "Bryant",
    "Alexander",
    "Russell",
    "Griffin",
    "Hayes",
    "Myers",
    "Ford",
    "Hamilton",
    "Graham",
    "Sullivan",
    "Wallace",
    "Woods",
    "Cole",
    "West",
    "Jordan",
    "Owens",
    "Reynolds",
    "Fisher",
    "Ellis",
    "Harrison",
    "Gibson",
    "Marshall",
    "Kennedy",
    "Warren",
    "Dixon",
    "Ramos",
    "Burns",
    "Gordon",
    "Shaw",
    "Holmes",
    "Rice",
    "Robertson",
    "Hunt",
    "Black",
    "Daniels",
    "Palmer",
    "Mills",
    "Spencer",
    "Pierce",
    "Hawkins",
    "Grant",
    "Webb",
    "Stone",
    "Cross",
    "Flint",
    "Blackwood",
    "Whitfield",
    "Holt",
    "Walsh",
    "Chen",
]

_used_names: set[str] = set()
_used_callsigns: set[str] = set()
_name_gen = itertools.product(_FIRST, _LAST)
_sn = itertools.count(1001)


def _next_name() -> tuple[str, str]:
    while True:
        first, last = next(_name_gen)
        key = f"{first}|{last}"
        if key not in _used_names:
            _used_names.add(key)
            return first, last


def _cs(base: str) -> str:
    cs = base.upper()
    if cs not in _used_callsigns:
        _used_callsigns.add(cs)
        return cs
    n = 2
    while f"{cs}{n}" in _used_callsigns:
        n += 1
    result = f"{cs}{n}"
    _used_callsigns.add(result)
    return result


def _op(
    rank: str,
    role: str = "OPERATOR",
    team_role: str = "OPERATOR",
    callsign: str | None = None,
    first: str | None = None,
    last: str | None = None,
) -> dict[str, Any]:
    if first is None or last is None:
        first, last = _next_name()
    else:
        _used_names.add(f"{first}|{last}")
    cs = _cs(callsign or f"{last.upper()}{next(_sn):04d}")
    return dict(callsign=cs, rank=rank, role=role, team_role=team_role)


# ── Small structural helpers ──────────────────────────────────────────────────


def _fire_team(name: str) -> dict:
    return {
        "name": name,
        "members": [
            _op("SGT", team_role="TL"),
            _op("SPC", team_role="AR"),
            _op("SPC", team_role="GL"),
            _op("PFC", team_role="RFM"),
        ],
    }


def _fire_team_sl(name: str) -> dict:
    return {
        "name": name,
        "members": [
            _op("SSG", team_role="SL"),
            _op("SGT", team_role="TL"),
            _op("SPC", team_role="AR"),
            _op("SPC", team_role="GL"),
            _op("PFC", team_role="RFM"),
        ],
    }


def _rifle_section(prefix: str) -> dict:
    return {
        "name": f"{prefix} Section",
        "teams": [
            _fire_team_sl(f"{prefix} Alpha"),
            _fire_team(f"{prefix} Bravo"),
        ],
    }


def _plt_hq_section(
    prefix: str, pl_rank: str = "1LT", pl_role: str = "BATTLE_CAPTAIN"
) -> dict:
    return {
        "name": f"{prefix} PLT HQ Sec",
        "teams": [
            {
                "name": f"{prefix} HQ Team",
                "members": [
                    _op(pl_rank, role=pl_role, team_role="PLT_LEADER"),
                    _op("SFC", team_role="PSG"),
                    _op("SPC", team_role="RTO"),
                    _op("SPC", team_role="MEDIC"),
                ],
            },
        ],
    }


def _rifle_platoon(prefix: str, pl_rank: str = "1LT") -> dict:
    return {
        "name": prefix,
        "sections": [
            _plt_hq_section(prefix, pl_rank),
            _rifle_section(f"{prefix}-1"),
            _rifle_section(f"{prefix}-2"),
        ],
    }


def _weapons_platoon(coy: str) -> dict:
    return {
        "name": f"{coy} WPNS PLT",
        "sections": [
            {
                "name": f"{coy} MORT Section",
                "teams": [
                    {
                        "name": f"{coy} MORT HQ",
                        "members": [
                            _op("1LT", "BATTLE_CAPTAIN", "PLT_LEADER"),
                            _op("SFC", team_role="PSG"),
                        ],
                    },
                    {
                        "name": f"{coy} MORT Team 1",
                        "members": [
                            _op("SGT", team_role="TL"),
                            _op("SPC", team_role="GUNNER"),
                            _op("SPC", team_role="AG"),
                            _op("PFC", team_role="AMO"),
                        ],
                    },
                    {
                        "name": f"{coy} MORT Team 2",
                        "members": [
                            _op("SGT", team_role="TL"),
                            _op("SPC", team_role="GUNNER"),
                            _op("SPC", team_role="AG"),
                            _op("PFC", team_role="AMO"),
                        ],
                    },
                ],
            },
            {
                "name": f"{coy} HW Section",
                "teams": [
                    {
                        "name": f"{coy} HW Team 1",
                        "members": [
                            _op("SSG", team_role="SL"),
                            _op("SGT", team_role="TL"),
                            _op("SPC", team_role="GUNNER"),
                            _op("SPC", team_role="AG"),
                        ],
                    },
                    {
                        "name": f"{coy} HW Team 2",
                        "members": [
                            _op("SGT", team_role="TL"),
                            _op("SPC", team_role="GUNNER"),
                            _op("SPC", team_role="AG"),
                            _op("PFC", team_role="AMO"),
                        ],
                    },
                ],
            },
        ],
    }


def _coy_hq_plt(
    coy: str,
    co_cs: str,
    co_fn: str,
    co_ln: str,
    xo_cs: str,
    xo_fn: str,
    xo_ln: str,
    sg_cs: str,
    sg_fn: str,
    sg_ln: str,
) -> dict:
    return {
        "name": f"{coy} HQ PLT",
        "sections": [
            {
                "name": f"{coy} HQ Section",
                "teams": [
                    {
                        "name": f"{coy} CMD Team",
                        "members": [
                            _op(
                                "CPT",
                                "BATTLE_CAPTAIN",
                                "COMMANDER",
                                callsign=co_cs,
                                first=co_fn,
                                last=co_ln,
                            ),
                            _op(
                                "1LT",
                                "BATTLE_CAPTAIN",
                                "XO",
                                callsign=xo_cs,
                                first=xo_fn,
                                last=xo_ln,
                            ),
                            _op(
                                "1SG",
                                team_role="1SG",
                                callsign=sg_cs,
                                first=sg_fn,
                                last=sg_ln,
                            ),
                        ],
                    },
                    {
                        "name": f"{coy} SPT Team",
                        "members": [
                            _op("SSG", team_role="ADMIN"),
                            _op("SGT", team_role="SUPPLY"),
                            _op("SPC", team_role="MEDIC"),
                        ],
                    },
                ],
            },
        ],
    }


def _rifle_company(
    coy_name: str,
    prefix: str,
    co_cs: str,
    co_fn: str,
    co_ln: str,
    xo_cs: str,
    xo_fn: str,
    xo_ln: str,
    sg_cs: str,
    sg_fn: str,
    sg_ln: str,
) -> dict:
    return {
        "name": coy_name,
        "platoons": [
            _coy_hq_plt(
                coy_name, co_cs, co_fn, co_ln, xo_cs, xo_fn, xo_ln, sg_cs, sg_fn, sg_ln
            ),
            _rifle_platoon(f"{prefix} 1st PLT", "1LT"),
            _rifle_platoon(f"{prefix} 2nd PLT", "2LT"),
            _rifle_platoon(f"{prefix} 3rd PLT", "2LT"),
            _weapons_platoon(prefix),
        ],
    }


# ── Full battalion data ───────────────────────────────────────────────────────


def build_battalion() -> list[dict]:
    return [
        # ── HHC ─────────────────────────────────────────────────────────────
        {
            "name": "HHC 1-75 RGR",
            "platoons": [
                {
                    "name": "BN CMD PLT",
                    "sections": [
                        {
                            "name": "BN CMD Section",
                            "teams": [
                                {
                                    "name": "BN HQ",
                                    "members": [
                                        _op(
                                            "LTC",
                                            "ADMIN",
                                            "COMMANDER",
                                            "HENDERSON",
                                            "Michael",
                                            "Henderson",
                                        ),
                                        _op(
                                            "MAJ",
                                            "BATTLE_CAPTAIN",
                                            "XO",
                                            "BLACKWOOD",
                                            "James",
                                            "Blackwood",
                                        ),
                                        _op(
                                            "CSM",
                                            "ADMIN",
                                            "CSM",
                                            "WHITFIELD",
                                            "Gerald",
                                            "Whitfield",
                                        ),
                                        _op(
                                            "SSG",
                                            team_role="AIDE",
                                            callsign="HOLT",
                                            first="Christopher",
                                            last="Holt",
                                        ),
                                    ],
                                },
                                {
                                    "name": "S-Shops",
                                    "members": [
                                        _op(
                                            "CPT",
                                            "BATTLE_CAPTAIN",
                                            "S1",
                                            "COLLINS",
                                            "Sarah",
                                            "Collins",
                                        ),
                                        _op("SSG", team_role="S1_NCOIC"),
                                        _op(
                                            "CPT",
                                            "BATTLE_CAPTAIN",
                                            "S2",
                                            "WARD",
                                            "Jason",
                                            "Ward",
                                        ),
                                        _op("SSG", team_role="S2_NCOIC"),
                                        _op(
                                            "MAJ",
                                            "BATTLE_CAPTAIN",
                                            "S3",
                                            "WALSH",
                                            "Brian",
                                            "Walsh",
                                        ),
                                        _op("MSG", team_role="S3_NCOIC"),
                                        _op(
                                            "CPT",
                                            "BATTLE_CAPTAIN",
                                            "S4",
                                            "CHEN",
                                            "Ryan",
                                            "Chen",
                                        ),
                                        _op("SSG", team_role="S4_NCOIC"),
                                        _op(
                                            "CPT",
                                            team_role="CHAPLAIN",
                                            callsign="WAVERLY",
                                            first="Thomas",
                                            last="Waverly",
                                        ),
                                        _op(
                                            "MAJ",
                                            team_role="SURGEON",
                                            callsign="ROSS",
                                            first="Jennifer",
                                            last="Ross",
                                        ),
                                    ],
                                },
                                {
                                    "name": "FSO Team",
                                    "members": [
                                        _op(
                                            "CPT",
                                            "BATTLE_CAPTAIN",
                                            "FSO",
                                            "CROSS",
                                            "Daniel",
                                            "Cross",
                                        ),
                                        _op("SFC", team_role="FSNCO"),
                                        _op("SGT", team_role="FO"),
                                        _op("SGT", team_role="FO"),
                                    ],
                                },
                            ],
                        },
                        {
                            "name": "COMMS Section",
                            "teams": [
                                {
                                    "name": "S6 Team",
                                    "members": [
                                        _op(
                                            "CW3",
                                            "BATTLE_CAPTAIN",
                                            "S6",
                                            "FLINT",
                                            "Robert",
                                            "Flint",
                                        ),
                                        _op("SSG", team_role="COMMS_NCOIC"),
                                        _op("SPC", team_role="COMMS"),
                                        _op("SPC", team_role="COMMS"),
                                    ],
                                },
                                {
                                    "name": "RTO Team",
                                    "members": [
                                        _op("SGT", team_role="RTO"),
                                        _op("SPC", team_role="RTO"),
                                        _op("SPC", team_role="RTO"),
                                        _op("PFC", team_role="RTO"),
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "SPT PLT",
                    "sections": [
                        {
                            "name": "MORT Section",
                            "teams": [
                                {
                                    "name": "BN MORT HQ",
                                    "members": [
                                        _op(
                                            "1LT",
                                            "BATTLE_CAPTAIN",
                                            "PLT_LEADER",
                                            "STONE",
                                            "Caleb",
                                            "Stone",
                                        ),
                                        _op("SFC", team_role="PSG"),
                                    ],
                                },
                                {
                                    "name": "60mm Team 1",
                                    "members": [
                                        _op("SGT", team_role="TL"),
                                        _op("SPC", team_role="GUNNER"),
                                        _op("SPC", team_role="AG"),
                                        _op("PFC", team_role="AMO"),
                                    ],
                                },
                                {
                                    "name": "60mm Team 2",
                                    "members": [
                                        _op("SGT", team_role="TL"),
                                        _op("SPC", team_role="GUNNER"),
                                        _op("SPC", team_role="AG"),
                                        _op("PFC", team_role="AMO"),
                                    ],
                                },
                                {
                                    "name": "81mm Team 1",
                                    "members": [
                                        _op("SGT", team_role="TL"),
                                        _op("SPC", team_role="GUNNER"),
                                        _op("SPC", team_role="AG"),
                                        _op("PFC", team_role="AMO"),
                                    ],
                                },
                                {
                                    "name": "81mm Team 2",
                                    "members": [
                                        _op("SGT", team_role="TL"),
                                        _op("SPC", team_role="GUNNER"),
                                        _op("SPC", team_role="AG"),
                                        _op("PFC", team_role="AMO"),
                                    ],
                                },
                            ],
                        },
                        {
                            "name": "MED Section",
                            "teams": [
                                {
                                    "name": "Aid Station",
                                    "members": [
                                        _op(
                                            "CPT",
                                            "BATTLE_CAPTAIN",
                                            "PA",
                                            callsign="TORRES-PA",
                                            first="Jennifer",
                                            last="Torres",
                                        ),
                                        _op("SSG", team_role="SENIOR_MEDIC"),
                                        _op("SPC", team_role="MEDIC"),
                                        _op("SPC", team_role="MEDIC"),
                                    ],
                                },
                                {
                                    "name": "Combat Medic Team",
                                    "members": [
                                        _op("SGT", team_role="MEDIC"),
                                        _op("SPC", team_role="MEDIC"),
                                        _op("SPC", team_role="MEDIC"),
                                        _op("PFC", team_role="MEDIC"),
                                    ],
                                },
                            ],
                        },
                        {
                            "name": "RRD Section",
                            "teams": [
                                {
                                    "name": "RRD Alpha",
                                    "members": [
                                        _op(
                                            "SFC",
                                            team_role="SL",
                                            callsign="HAYES",
                                            first="Derek",
                                            last="Hayes",
                                        ),
                                        _op("SSG", team_role="TL"),
                                        _op("SGT", team_role="RECON"),
                                        _op("SGT", team_role="RECON"),
                                        _op("SPC", team_role="RECON"),
                                    ],
                                },
                                {
                                    "name": "RRD Bravo",
                                    "members": [
                                        _op("SSG", team_role="TL"),
                                        _op("SGT", team_role="RECON"),
                                        _op("SGT", team_role="RECON"),
                                        _op("SPC", team_role="RECON"),
                                        _op("SPC", team_role="RECON"),
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        # ── Rifle Companies ──────────────────────────────────────────────────
        _rifle_company(
            "ALPHA CO 1-75 RGR",
            "ALPHA",
            "COLE",
            "Ryan",
            "Cole",
            "HUNT",
            "Derek",
            "Hunt",
            "RODRIGUEZ",
            "James",
            "Rodriguez",
        ),
        _rifle_company(
            "BRAVO CO 1-75 RGR",
            "BRAVO",
            "PIERCE",
            "Marcus",
            "Pierce",
            "WEBB",
            "Nathan",
            "Webb",
            "SIMMONS",
            "Kevin",
            "Simmons",
        ),
        _rifle_company(
            "CHARLIE CO 1-75 RGR",
            "CHARLIE",
            "HAWKINS",
            "Eric",
            "Hawkins",
            "GRANT",
            "Cody",
            "Grant",
            "MOORE",
            "Travis",
            "Moore",
        ),
        _rifle_company(
            "DELTA CO 1-75 RGR",
            "DELTA",
            "SHAW",
            "Tyler",
            "Shaw",
            "REED",
            "Justin",
            "Reed",
            "WALKER",
            "Adam",
            "Walker",
        ),
    ]


# ── Session: auto-relogin on 401 ─────────────────────────────────────────────


class Session:
    """Wraps httpx.Client with automatic token refresh on 401 (session superseded)."""

    def __init__(self, client: httpx.Client, callsign: str, password: str) -> None:
        self._client = client
        self._callsign = callsign
        self._password = password
        self.token = ""

    def login(self) -> bool:
        try:
            r = self._client.post(
                f"{BASE}/auth/login",
                data={"username": self._callsign, "password": self._password},
                timeout=10,
            )
            if r.status_code == 200:
                self.token = r.json()["access_token"]
                log.info("(re)authenticated as %s", self._callsign)
                return True
        except Exception as exc:
            log.warning("login failed: %s", exc)
        return False

    def _hdr(self, mission_id: int | None = None) -> dict:
        h = {"Authorization": f"Bearer {self.token}"}
        if mission_id:
            h["X-Mission-ID"] = str(mission_id)
        return h

    def get(self, path: str) -> list | dict | None:
        for attempt in range(2):
            try:
                r = self._client.get(f"{BASE}{path}", headers=self._hdr(), timeout=15)
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 401 and attempt == 0:
                    self.login()
                    continue
                log.warning("GET %-30s → %d", path, r.status_code)
            except Exception as exc:
                log.warning("GET %s → %s", path, exc)
            return None
        return None

    def post(self, path: str, body: dict, mission_id: int | None = None) -> dict | None:
        for attempt in range(2):
            try:
                r = self._client.post(
                    f"{BASE}{path}",
                    headers=self._hdr(mission_id),
                    json=body,
                    timeout=15,
                )
                if r.status_code in (200, 201):
                    return r.json()
                if r.status_code == 409:
                    return None
                if r.status_code == 401 and attempt == 0:
                    self.login()
                    continue
                log.warning("POST %-30s → %d  %s", path, r.status_code, r.text[:120])
            except Exception as exc:
                log.warning("POST %s → %s", path, exc)
            return None
        return None

    def patch(self, path: str, body: dict) -> bool:
        for attempt in range(2):
            try:
                r = self._client.patch(
                    f"{BASE}{path}", headers=self._hdr(), json=body, timeout=15
                )
                if r.status_code in (200, 204):
                    return True
                if r.status_code == 401 and attempt == 0:
                    self.login()
                    continue
            except Exception:
                pass
            return False
        return False

    def delete(self, path: str) -> bool:
        for attempt in range(2):
            try:
                r = self._client.delete(
                    f"{BASE}{path}", headers=self._hdr(), timeout=15
                )
                if r.status_code in (200, 204):
                    return True
                if r.status_code == 401 and attempt == 0:
                    self.login()
                    continue
            except Exception:
                pass
            return False
        return False


# ── Reset ─────────────────────────────────────────────────────────────────────

BN_COMPANY_NAMES = {
    "HHC 1-75 RGR",
    "ALPHA CO 1-75 RGR",
    "BRAVO CO 1-75 RGR",
    "CHARLIE CO 1-75 RGR",
    "DELTA CO 1-75 RGR",
}


def reset(sess: Session, battalion: list[dict]) -> None:
    log.info("── Reset: removing 1-75 RGR data ───────────────────────")
    companies = sess.get("/companies") or []
    all_ops = sess.get("/operators") or []

    bn_callsigns = {
        m["callsign"]
        for coy in battalion
        for plt in coy["platoons"]
        for sec in plt["sections"]
        for team in sec["teams"]
        for m in team["members"]
    }

    deleted_ops = 0
    for op in all_ops:
        if op["callsign"] in bn_callsigns:
            if sess.delete(f"/operators/{op['id']}"):
                deleted_ops += 1

    deleted_cos = 0
    for c in companies:
        if c["name"] in BN_COMPANY_NAMES:
            if sess.delete(f"/companies/{c['id']}"):
                deleted_cos += 1

    log.info("  Deleted %d operators, %d companies", deleted_ops, deleted_cos)


# ── Bootstrap ─────────────────────────────────────────────────────────────────


def bootstrap(
    sess: Session, battalion: list[dict], mission_id: int | None = None
) -> int:
    """Walk the battalion tree via REST, creating every node. Returns op count."""

    # Snapshot existing state once — skips already-existing nodes cheaply.
    existing_companies = {c["name"]: c["id"] for c in (sess.get("/companies") or [])}
    existing_platoons = {p["name"]: p["id"] for p in (sess.get("/platoons") or [])}
    existing_sections = {s["name"]: s["id"] for s in (sess.get("/sections") or [])}
    existing_teams = {t["name"]: t["id"] for t in (sess.get("/teams") or [])}
    existing_ops = {o["callsign"]: o["id"] for o in (sess.get("/operators") or [])}

    total = created = skipped = 0

    for coy in battalion:
        coy_name = coy["name"]
        if coy_name in existing_companies:
            coy_id = existing_companies[coy_name]
        else:
            r = sess.post("/companies", {"name": coy_name})
            if not r:
                log.error("Failed to create company %s", coy_name)
                continue
            coy_id = r["id"]
            log.info("Company  %s  (id=%d)", coy_name, coy_id)

        for plt in coy["platoons"]:
            plt_name = plt["name"]
            if plt_name in existing_platoons:
                plt_id = existing_platoons[plt_name]
            else:
                r = sess.post("/platoons", {"name": plt_name, "company_id": coy_id})
                if not r:
                    continue
                plt_id = r["id"]

            for sec in plt["sections"]:
                sec_name = sec["name"]
                if sec_name in existing_sections:
                    sec_id = existing_sections[sec_name]
                else:
                    r = sess.post("/sections", {"name": sec_name, "platoon_id": plt_id})
                    if not r:
                        continue
                    sec_id = r["id"]

                for team in sec["teams"]:
                    team_name = team["name"]
                    if team_name in existing_teams:
                        team_id = existing_teams[team_name]
                    else:
                        r = sess.post(
                            "/teams", {"name": team_name, "section_id": sec_id}
                        )
                        if not r:
                            continue
                        team_id = r["id"]

                    for member in team["members"]:
                        cs = member["callsign"]
                        patch_body: dict = {
                            "team_id": team_id,
                            "team_role": member["team_role"],
                        }
                        if mission_id:
                            patch_body["mission_id"] = mission_id

                        if cs in existing_ops:
                            # Operator exists — ensure team, role, and mission are correct.
                            sess.patch(f"/operators/{existing_ops[cs]}", patch_body)
                            skipped += 1
                            total += 1
                            continue

                        # New operator — register via elevated endpoint.
                        reg = sess.post(
                            "/auth/register/admin",
                            {
                                "callsign": cs,
                                "password": PASSWORD,
                                "rank": member["rank"],
                                "role": member["role"],
                                "team_id": team_id,
                            },
                        )
                        if not reg:
                            log.warning("      Failed to register %s", cs)
                            continue

                        # Use the new operator's own token + /auth/me to get
                        # their id — avoids a full GET /operators scan (O(n²)).
                        new_token = reg.get("access_token", "")
                        op_id = None
                        if new_token:
                            try:
                                me = sess._client.get(
                                    f"{BASE}/auth/me",
                                    headers={"Authorization": f"Bearer {new_token}"},
                                    timeout=10,
                                )
                                if me.status_code == 200:
                                    op_id = me.json().get("id")
                            except Exception:
                                pass
                        if op_id:
                            sess.patch(f"/operators/{op_id}", patch_body)

                        existing_ops[cs] = op_id or 0
                        created += 1
                        total += 1

    log.info(
        "Operators: %d created, %d already existed, %d total", created, skipped, total
    )
    return total


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    sim_utils.save_backend(BASE)

    with httpx.Client(verify=False) as client:
        sess = Session(client, ARGS.seed_admin, ARGS.seed_admin_password)

        # 1. Login as seed admin
        log.info("Logging in as seed admin '%s' …", ARGS.seed_admin)
        if not sess.login():
            log.error(
                "Cannot log in as '%s'. Ensure the backend is running and "
                "seeded (uv run arrow-backend).",
                ARGS.seed_admin,
            )
            sys.exit(1)

        # 2. Build battalion data first — name pool is stateful, call only once
        log.info("── Building 1st Bn, 75th Ranger Regiment ────────────")
        battalion = build_battalion()

        # 3. Optionally wipe existing BN data
        if ARGS.reset:
            reset(sess, battalion)

        # 4. Create / adopt mission
        mission_id = sim_utils.create_mission_sync(
            client,
            BASE,
            sess.token,
            name=ARGS.mission_name,
            description="1st Bn, 75th Ranger Regiment — training exercise",
            map_center_lat=50.0028,
            map_center_lng=5.7300,
            map_zoom=12,
        )
        if mission_id:
            log.info("Mission id=%d", mission_id)

        # 5. Bootstrap hierarchy + operators (assigns mission_id on every operator)
        total = bootstrap(sess, battalion, mission_id=mission_id)

    log.info("")
    log.info("══════════════════════════════════════════════════════")
    log.info("  ✅  %d Rangers registered  |  password: %s", total, PASSWORD)
    log.info("  Key leaders:")
    log.info("    HENDERSON  LTC — Battalion Commander (ADMIN)")
    log.info("    BLACKWOOD  MAJ — Battalion XO        (BATTLE_CAPTAIN)")
    log.info("    WHITFIELD  CSM — Battalion CSM       (ADMIN)")
    log.info("    COLE       CPT — Alpha CO            (BATTLE_CAPTAIN)")
    log.info("    PIERCE     CPT — Bravo CO            (BATTLE_CAPTAIN)")
    log.info("    HAWKINS    CPT — Charlie CO          (BATTLE_CAPTAIN)")
    log.info("    SHAW       CPT — Delta CO            (BATTLE_CAPTAIN)")
    log.info("══════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
