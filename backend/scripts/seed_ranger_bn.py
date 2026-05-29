#!/usr/bin/env python3
"""
1st Battalion, 75th Ranger Regiment — hierarchy seeder
~420 operators, full Company → Platoon → Section → Team tree.

All operators created with password: ranger14

Arrow roles:
  ADMIN          → BN CO, BN CSM
  BATTLE_CAPTAIN → Company COs, BN XO, staff officers (S1–S6, FSO, PA)
  OPERATOR       → everyone else

Usage:
    uv run python -m backend.scripts.seed_ranger_bn
    uv run python -m backend.scripts.seed_ranger_bn --reset
"""
from __future__ import annotations

import argparse
import itertools
import sys
from typing import Any

# ── bootstrap ─────────────────────────────────────────────────────────────────
from backend.auth.jwt_auth import hash_password
from backend.storage.database import SessionLocal, init_db
from backend.storage.models import Company, Operator, Platoon, Section, Team

PASSWORD = "ranger14"
_PW_HASH = hash_password(PASSWORD)

# ── name pools ────────────────────────────────────────────────────────────────

_FIRST = [
    "James","Robert","Michael","William","David","Joseph","Thomas","Charles",
    "Christopher","Daniel","Ryan","Eric","Kevin","Brian","Jason","Marcus",
    "Kyle","Tyler","Adam","Nathan","Justin","Joshua","Cody","Travis","Garrett",
    "Shane","Derek","Caleb","Luke","Cameron","Dylan","Hunter","Logan","Brandon",
    "Austin","Aaron","Connor","Mason","Ethan","Samuel","Andrew","Jonathan",
    "Nicholas","Timothy","Patrick","Scott","Benjamin","Matthew","Stephen",
    "Bradley","Raymond","Gregory","Donald","Richard","Anthony","Frank","Steven",
    "Mark","Paul","Larry","Jerry","Dennis","Gerald","Carl","Harold","Walter",
    "Jose","Henry","Douglas","Peter","Keith","Roger","Terry","Sean","Jesse",
    "Randy","Lawrence","Bobby","Dean","Eddie","Fernando","Juan","Carlos",
    "Miguel","Alejandro","Rafael","Diego","Antonio","Luis","Roberto","Manuel",
    "Sarah","Jennifer","Melissa","Amanda","Ashley","Nicole","Rachel","Lauren",
    "Emily","Brittany","Angela","Rebecca","Katherine","Michelle","Christine",
]

_LAST = [
    "Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis",
    "Rodriguez","Martinez","Hernandez","Lopez","Gonzalez","Wilson","Anderson",
    "Thomas","Taylor","Moore","Jackson","Martin","Lee","Perez","Thompson",
    "White","Harris","Sanchez","Clark","Ramirez","Lewis","Robinson","Walker",
    "Young","Allen","King","Wright","Scott","Torres","Nguyen","Hill","Flores",
    "Green","Adams","Nelson","Baker","Hall","Rivera","Campbell","Mitchell",
    "Carter","Roberts","Gomez","Phillips","Evans","Turner","Diaz","Parker",
    "Cruz","Edwards","Collins","Reyes","Stewart","Morris","Morgan","Reed",
    "Cook","Bell","Murphy","Bailey","Cooper","Richardson","Cox","Howard",
    "Ward","Patterson","Gray","Watson","Brooks","Kelly","Sanders","Price",
    "Bennett","Wood","Barnes","Ross","Henderson","Coleman","Jenkins","Perry",
    "Powell","Long","Hughes","Washington","Butler","Simmons","Foster","Bryant",
    "Alexander","Russell","Griffin","Hayes","Myers","Ford","Hamilton","Graham",
    "Sullivan","Wallace","Woods","Cole","West","Jordan","Owens","Reynolds",
    "Fisher","Ellis","Harrison","Gibson","Mcdonald","Marshall","Ortega",
    "Kennedy","Warren","Dixon","Ramos","Burns","Gordon","Shaw","Holmes",
    "Rice","Robertson","Hunt","Black","Daniels","Palmer","Mills","Warren",
    "Spencer","Pierce","Hawkins","Grant","Webb","Stone","Cross","Flint",
    "Blackwood","Whitfield","Holt","Walsh","Chen","Waverly","Hayes",
]

_used_names:     set[str] = set()
_used_callsigns: set[str] = set()
_sn = itertools.count(1001)           # service-number suffix for auto callsigns
_name_gen = itertools.product(_FIRST, _LAST)


def _next_name() -> tuple[str, str]:
    while True:
        first, last = next(_name_gen)
        key = f"{first}|{last}"
        if key not in _used_names:
            _used_names.add(key)
            return first, last


def _unique_cs(base: str) -> str:
    cs = base.upper()
    if cs not in _used_callsigns:
        _used_callsigns.add(cs)
        return cs
    n = 2
    while f"{cs}{n}" in _used_callsigns:
        n += 1
    cs2 = f"{cs}{n}"
    _used_callsigns.add(cs2)
    return cs2


def _op(
    rank:      str,
    role:      str = "OPERATOR",
    team_role: str = "OPERATOR",
    callsign:  str | None = None,
    first:     str | None = None,
    last:      str | None = None,
) -> dict[str, Any]:
    if first is None or last is None:
        first, last = _next_name()
    else:
        _used_names.add(f"{first}|{last}")
    if callsign is None:
        callsign = f"{last.upper()}{next(_sn):04d}"
    callsign = _unique_cs(callsign)
    return dict(callsign=callsign, rank=rank, role=role,
                team_role=team_role, first=first, last=last)


# ── small builder helpers ─────────────────────────────────────────────────────

def _fire_team(name: str) -> dict:
    return {"name": name, "members": [
        _op("SGT", team_role="TL"),
        _op("SPC", team_role="AR"),
        _op("SPC", team_role="GL"),
        _op("PFC", team_role="RFM"),
    ]}


def _fire_team_sl(name: str) -> dict:
    """Alpha team carries the Section Leader."""
    return {"name": name, "members": [
        _op("SSG", team_role="SL"),
        _op("SGT", team_role="TL"),
        _op("SPC", team_role="AR"),
        _op("SPC", team_role="GL"),
        _op("PFC", team_role="RFM"),
    ]}


def _rifle_section(prefix: str) -> dict:
    return {
        "name": f"{prefix} Section",
        "teams": [
            _fire_team_sl(f"{prefix} Alpha"),
            _fire_team(f"{prefix} Bravo"),
        ],
    }


def _plt_hq_section(prefix: str, pl_rank: str = "1LT",
                    pl_role: str = "BATTLE_CAPTAIN") -> dict:
    return {
        "name": f"{prefix} PLT HQ Sec",
        "teams": [{"name": f"{prefix} HQ Team", "members": [
            _op(pl_rank, role=pl_role, team_role="PLT_LEADER"),
            _op("SFC",              team_role="PSG"),
            _op("SPC",              team_role="RTO"),
            _op("SPC",              team_role="MEDIC"),
        ]}],
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
                    {"name": f"{coy} MORT HQ", "members": [
                        _op("1LT", role="BATTLE_CAPTAIN", team_role="PLT_LEADER"),
                        _op("SFC",                        team_role="PSG"),
                    ]},
                    {"name": f"{coy} MORT Team 1", "members": [
                        _op("SGT", team_role="TL"),
                        _op("SPC", team_role="GUNNER"),
                        _op("SPC", team_role="AG"),
                        _op("PFC", team_role="AMO"),
                    ]},
                    {"name": f"{coy} MORT Team 2", "members": [
                        _op("SGT", team_role="TL"),
                        _op("SPC", team_role="GUNNER"),
                        _op("SPC", team_role="AG"),
                        _op("PFC", team_role="AMO"),
                    ]},
                ],
            },
            {
                "name": f"{coy} HW Section",
                "teams": [
                    {"name": f"{coy} HW Team 1", "members": [
                        _op("SSG", team_role="SL"),
                        _op("SGT", team_role="TL"),
                        _op("SPC", team_role="GUNNER"),
                        _op("SPC", team_role="AG"),
                    ]},
                    {"name": f"{coy} HW Team 2", "members": [
                        _op("SGT", team_role="TL"),
                        _op("SPC", team_role="GUNNER"),
                        _op("SPC", team_role="AG"),
                        _op("PFC", team_role="AMO"),
                    ]},
                ],
            },
        ],
    }


def _coy_hq_plt(
    coy: str,
    co_cs: str, co_fn: str, co_ln: str,
    xo_cs: str, xo_fn: str, xo_ln: str,
    sg_cs: str, sg_fn: str, sg_ln: str,
) -> dict:
    return {
        "name": f"{coy} HQ PLT",
        "sections": [{
            "name": f"{coy} HQ Section",
            "teams": [
                {"name": f"{coy} CMD Team", "members": [
                    _op("CPT", "BATTLE_CAPTAIN", "COMMANDER",
                        callsign=co_cs, first=co_fn, last=co_ln),
                    _op("1LT", "BATTLE_CAPTAIN", "XO",
                        callsign=xo_cs, first=xo_fn, last=xo_ln),
                    _op("1SG",                   "1SG",
                        callsign=sg_cs, first=sg_fn, last=sg_ln),
                ]},
                {"name": f"{coy} SPT Team", "members": [
                    _op("SSG", team_role="ADMIN"),
                    _op("SGT", team_role="SUPPLY"),
                    _op("SPC", team_role="MEDIC"),
                ]},
            ],
        }],
    }


def _rifle_company(
    coy_name: str, prefix: str,
    co_cs: str, co_fn: str, co_ln: str,
    xo_cs: str, xo_fn: str, xo_ln: str,
    sg_cs: str, sg_fn: str, sg_ln: str,
) -> dict:
    return {
        "name": coy_name,
        "platoons": [
            _coy_hq_plt(coy_name,
                        co_cs, co_fn, co_ln,
                        xo_cs, xo_fn, xo_ln,
                        sg_cs, sg_fn, sg_ln),
            _rifle_platoon(f"{prefix} 1st PLT", "1LT"),
            _rifle_platoon(f"{prefix} 2nd PLT", "2LT"),
            _rifle_platoon(f"{prefix} 3rd PLT", "2LT"),
            _weapons_platoon(prefix),
        ],
    }


# ── HHC ───────────────────────────────────────────────────────────────────────

def _build_hhc() -> dict:
    return {
        "name": "HHC 1-75 RGR",
        "platoons": [
            {
                "name": "BN CMD PLT",
                "sections": [
                    {
                        "name": "BN CMD Section",
                        "teams": [
                            {"name": "BN HQ", "members": [
                                _op("LTC", "ADMIN",          "COMMANDER",
                                    "HENDERSON", "Michael",    "Henderson"),
                                _op("MAJ", "BATTLE_CAPTAIN", "XO",
                                    "BLACKWOOD",  "James",     "Blackwood"),
                                _op("CSM", "ADMIN",          "CSM",
                                    "WHITFIELD",  "Gerald",    "Whitfield"),
                                _op("SSG", team_role="AIDE",
                                    callsign="HOLT",  first="Christopher", last="Holt"),
                            ]},
                            {"name": "S-Shops", "members": [
                                _op("CPT", "BATTLE_CAPTAIN", "S1",
                                    "COLLINS",  "Sarah",    "Collins"),
                                _op("SSG", team_role="S1_NCOIC"),
                                _op("CPT", "BATTLE_CAPTAIN", "S2",
                                    "WARD",     "Jason",    "Ward"),
                                _op("SSG", team_role="S2_NCOIC"),
                                _op("MAJ", "BATTLE_CAPTAIN", "S3",
                                    "WALSH",    "Brian",    "Walsh"),
                                _op("MSG", team_role="S3_NCOIC"),
                                _op("CPT", "BATTLE_CAPTAIN", "S4",
                                    "CHEN",     "Ryan",     "Chen"),
                                _op("SSG", team_role="S4_NCOIC"),
                                _op("CPT", team_role="CHAPLAIN",
                                    callsign="WAVERLY", first="Thomas",   last="Waverly"),
                                _op("MAJ", team_role="SURGEON",
                                    callsign="ROSS",    first="Jennifer", last="Ross"),
                            ]},
                            {"name": "FSO Team", "members": [
                                _op("CPT", "BATTLE_CAPTAIN", "FSO",
                                    "CROSS", "Daniel", "Cross"),
                                _op("SFC", team_role="FSNCO"),
                                _op("SGT", team_role="FO"),
                                _op("SGT", team_role="FO"),
                            ]},
                        ],
                    },
                    {
                        "name": "COMMS Section",
                        "teams": [
                            {"name": "S6 Team", "members": [
                                _op("CW3", "BATTLE_CAPTAIN", "S6",
                                    "FLINT", "Robert", "Flint"),
                                _op("SSG", team_role="COMMS_NCOIC"),
                                _op("SPC", team_role="COMMS"),
                                _op("SPC", team_role="COMMS"),
                            ]},
                            {"name": "RTO Team", "members": [
                                _op("SGT", team_role="RTO"),
                                _op("SPC", team_role="RTO"),
                                _op("SPC", team_role="RTO"),
                                _op("PFC", team_role="RTO"),
                            ]},
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
                            {"name": "BN MORT HQ", "members": [
                                _op("1LT", "BATTLE_CAPTAIN", "PLT_LEADER",
                                    "STONE", "Caleb", "Stone"),
                                _op("SFC", team_role="PSG"),
                            ]},
                            {"name": "60mm Team 1", "members": [
                                _op("SGT", team_role="TL"),
                                _op("SPC", team_role="GUNNER"),
                                _op("SPC", team_role="AG"),
                                _op("PFC", team_role="AMO"),
                            ]},
                            {"name": "60mm Team 2", "members": [
                                _op("SGT", team_role="TL"),
                                _op("SPC", team_role="GUNNER"),
                                _op("SPC", team_role="AG"),
                                _op("PFC", team_role="AMO"),
                            ]},
                            {"name": "81mm Team 1", "members": [
                                _op("SGT", team_role="TL"),
                                _op("SPC", team_role="GUNNER"),
                                _op("SPC", team_role="AG"),
                                _op("PFC", team_role="AMO"),
                            ]},
                            {"name": "81mm Team 2", "members": [
                                _op("SGT", team_role="TL"),
                                _op("SPC", team_role="GUNNER"),
                                _op("SPC", team_role="AG"),
                                _op("PFC", team_role="AMO"),
                            ]},
                        ],
                    },
                    {
                        "name": "MED Section",
                        "teams": [
                            {"name": "Aid Station", "members": [
                                _op("CPT", "BATTLE_CAPTAIN", "PA",
                                    "TORRES2", "Jennifer", "Torres"),
                                _op("SSG", team_role="SENIOR_MEDIC"),
                                _op("SPC", team_role="MEDIC"),
                                _op("SPC", team_role="MEDIC"),
                            ]},
                            {"name": "Combat Medic Team", "members": [
                                _op("SGT", team_role="MEDIC"),
                                _op("SPC", team_role="MEDIC"),
                                _op("SPC", team_role="MEDIC"),
                                _op("PFC", team_role="MEDIC"),
                            ]},
                        ],
                    },
                    {
                        "name": "RRD Section",
                        "teams": [
                            {"name": "RRD Alpha", "members": [
                                _op("SFC", team_role="SL",
                                    callsign="HAYES", first="Derek", last="Hayes"),
                                _op("SSG", team_role="TL"),
                                _op("SGT", team_role="RECON"),
                                _op("SGT", team_role="RECON"),
                                _op("SPC", team_role="RECON"),
                            ]},
                            {"name": "RRD Bravo", "members": [
                                _op("SSG", team_role="TL"),
                                _op("SGT", team_role="RECON"),
                                _op("SGT", team_role="RECON"),
                                _op("SPC", team_role="RECON"),
                                _op("SPC", team_role="RECON"),
                            ]},
                        ],
                    },
                ],
            },
        ],
    }


# ── Full battalion ─────────────────────────────────────────────────────────────

def _build_battalion() -> list[dict]:
    return [
        _build_hhc(),
        _rifle_company(
            "ALPHA CO 1-75 RGR", "ALPHA",
            "COLE",       "Ryan",   "Cole",
            "HUNT",       "Derek",  "Hunt",
            "RODRIGUEZ",  "James",  "Rodriguez",
        ),
        _rifle_company(
            "BRAVO CO 1-75 RGR", "BRAVO",
            "PIERCE",     "Marcus",  "Pierce",
            "WEBB",       "Nathan",  "Webb",
            "SIMMONS",    "Kevin",   "Simmons",
        ),
        _rifle_company(
            "CHARLIE CO 1-75 RGR", "CHARLIE",
            "HAWKINS",    "Eric",    "Hawkins",
            "GRANT",      "Cody",    "Grant",
            "MOORE",      "Travis",  "Moore",
        ),
        _rifle_company(
            "DELTA CO 1-75 RGR", "DELTA",
            "SHAW",       "Tyler",   "Shaw",
            "REED",       "Justin",  "Reed",
            "WALKER",     "Adam",    "Walker",
        ),
    ]


# ── DB writer ─────────────────────────────────────────────────────────────────

def _create_operator(db, spec: dict, team_id: int) -> Operator:
    op = Operator(
        callsign      = spec["callsign"],
        password_hash = _PW_HASH,
        rank          = spec["rank"],
        role          = spec["role"],
        team_id       = team_id,
        team_role     = spec["team_role"],
        status        = "OFFLINE",
    )
    db.add(op)
    return op


def _seed(db) -> int:
    total = 0
    for coy_spec in _build_battalion():
        company = Company(name=coy_spec["name"])
        db.add(company)
        db.flush()

        for plt_spec in coy_spec["platoons"]:
            platoon = Platoon(name=plt_spec["name"], company_id=company.id)
            db.add(platoon)
            db.flush()

            for sec_spec in plt_spec["sections"]:
                section = Section(name=sec_spec["name"], platoon_id=platoon.id)
                db.add(section)
                db.flush()

                for team_spec in sec_spec["teams"]:
                    team = Team(name=team_spec["name"], section_id=section.id)
                    db.add(team)
                    db.flush()

                    for member in team_spec["members"]:
                        _create_operator(db, member, team.id)
                        total += 1

    db.commit()
    return total


def _reset(db) -> None:
    db.query(Operator).delete()
    db.query(Team).delete()
    db.query(Section).delete()
    db.query(Platoon).delete()
    db.query(Company).delete()
    db.commit()
    print("  ✓ wiped existing hierarchy and operators")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed 1-75 RGR hierarchy")
    parser.add_argument("--reset", action="store_true",
                        help="Delete all existing data before seeding")
    args = parser.parse_args()

    init_db()

    with SessionLocal() as db:
        # Guard against double-run
        if not args.reset:
            exists = db.query(Company).filter(
                Company.name == "HHC 1-75 RGR"
            ).first()
            if exists:
                print("⚠  HHC 1-75 RGR already exists — use --reset to rebuild.")
                sys.exit(0)
        else:
            _reset(db)

        print("⏳  Building 1st Bn, 75th Ranger Regiment…")
        total = _seed(db)

    print(f"✅  Done — {total} Rangers registered across 5 companies.")
    print(f"    Password for all: {PASSWORD}")
    print()
    print("  Key leaders:")
    print("    HENDERSON  — LTC Michael Henderson   (BN CO / ADMIN)")
    print("    BLACKWOOD  — MAJ James Blackwood      (BN XO / BATTLE_CAPTAIN)")
    print("    WHITFIELD  — CSM Gerald Whitfield     (BN CSM / ADMIN)")
    print("    COLE       — CPT Ryan Cole            (Alpha CO / BATTLE_CAPTAIN)")
    print("    PIERCE     — CPT Marcus Pierce        (Bravo CO / BATTLE_CAPTAIN)")
    print("    HAWKINS    — CPT Eric Hawkins         (Charlie CO / BATTLE_CAPTAIN)")
    print("    SHAW       — CPT Tyler Shaw           (Delta CO / BATTLE_CAPTAIN)")


if __name__ == "__main__":
    main()
