"""Seed the database with a standard set of users for development/demo.

- 1 admin: benoit / ranger14
- 1 battle captain: capt / ranger14
- 10 operators with random callsigns, password ranger14

Idempotent — does nothing if any of the named users already exist.
"""

from __future__ import annotations

import random

from sqlalchemy.orm import Session

from backend.auth.jwt_auth import hash_password
from backend.storage.database import SessionLocal
from backend.storage.models import Operator

DEFAULT_PASSWORD = "ranger14"

ADMIN = {"callsign": "benoit", "rank": "OF-3", "role": "ADMIN"}
CAPTAIN = {"callsign": "capt", "rank": "OF-2", "role": "BATTLE_CAPTAIN"}

_PHONETIC = [
    "ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL",
    "INDIA", "JULIET", "KILO", "LIMA", "MIKE", "NOVEMBER", "OSCAR", "PAPA",
    "QUEBEC", "ROMEO", "SIERRA", "TANGO", "UNIFORM", "VICTOR", "WHISKEY",
    "XRAY", "YANKEE", "ZULU",
]
_RANKS = ["OR-1", "OR-2", "OR-3", "OR-4", "OR-5", "OR-6"]


def _ensure(db: Session, callsign: str, password: str, rank: str, role: str) -> Operator:
    existing = db.query(Operator).filter(Operator.callsign == callsign).first()
    if existing:
        return existing
    op = Operator(
        callsign=callsign,
        rank=rank,
        role=role,
        password_hash=hash_password(password),
    )
    db.add(op)
    return op


def _random_callsigns(count: int, taken: set[str], rng: random.Random) -> list[str]:
    out: list[str] = []
    while len(out) < count:
        candidate = f"{rng.choice(_PHONETIC)}-{rng.randint(1, 9)}"
        if candidate in taken or candidate in out:
            continue
        out.append(candidate)
    return out


def seed(force: bool = False) -> dict[str, list[str]]:
    """Run the seed. Returns the callsigns created/already-present.

    Skips entirely when the DB already has operators, unless force=True.
    """
    rng = random.Random(0xA77017)  # deterministic
    created: list[str] = []

    with SessionLocal() as db:
        if not force and db.query(Operator).count() > 0:
            existing = [c for (c,) in db.query(Operator.callsign).all()]
            return {"created": [], "existing": existing}

        admin = _ensure(db, ADMIN["callsign"], DEFAULT_PASSWORD, ADMIN["rank"], ADMIN["role"])
        capt = _ensure(db, CAPTAIN["callsign"], DEFAULT_PASSWORD, CAPTAIN["rank"], CAPTAIN["role"])
        if admin in db.new:
            created.append(ADMIN["callsign"])
        if capt in db.new:
            created.append(CAPTAIN["callsign"])

        taken = {ADMIN["callsign"], CAPTAIN["callsign"]}
        for callsign in _random_callsigns(10, taken, rng):
            op = _ensure(db, callsign, DEFAULT_PASSWORD, rng.choice(_RANKS), "OPERATOR")
            if op in db.new:
                created.append(callsign)

        db.commit()

    return {"created": created, "existing": []}


def main() -> None:
    import argparse

    from backend.storage.database import init_db

    parser = argparse.ArgumentParser(description="Seed Arrow's operator table.")
    parser.add_argument("--force", action="store_true", help="Seed even if operators already exist.")
    args = parser.parse_args()

    init_db()
    result = seed(force=args.force)
    if result["created"]:
        print(f"Created {len(result['created'])} operator(s):")
        for c in result["created"]:
            print(f"  - {c}  (password: {DEFAULT_PASSWORD})")
    else:
        print("DB already populated; nothing to do (use --force to re-seed missing entries).")
        if result["existing"]:
            print(f"Existing operators: {', '.join(result['existing'])}")


if __name__ == "__main__":
    main()
