"""Seed the database with the minimum named accounts required to boot.

- 1 admin: benoit / ranger14
- 1 battle captain: capt / ranger14

Deliberately creates NO random operators — the simulator or admin panel
should be used to build the full hierarchy and assign operators to teams.
Idempotent — does nothing if any operators already exist.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.auth.jwt_auth import hash_password
from backend.storage.database import SessionLocal
from backend.storage.models import Operator

DEFAULT_PASSWORD = "ranger14"

ADMIN = {"callsign": "benoit", "rank": "OF-3", "role": "ADMIN"}
CAPTAIN = {"callsign": "capt", "rank": "OF-2", "role": "BATTLE_CAPTAIN"}


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



def seed(force: bool = False) -> dict[str, list[str]]:
    """Run the seed. Returns the callsigns created/already-present.

    Skips entirely when the DB already has operators, unless force=True.
    """
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
