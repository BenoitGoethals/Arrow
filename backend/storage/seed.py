"""Seed the database with the named accounts required to boot.

- 1 admin:          benoit / ranger14
- 1 battle captain: capt   / ranger14
- 3 operators:      ops1 / ops2 / ops3   (all  / ranger14)

Idempotent at the row level: each callsign is upserted via `_ensure`, so re-runs
on an existing database insert any missing accounts without disturbing the rest.
The simulator or admin panel should still be used to build the full hierarchy
and assign operators to teams.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.auth.jwt_auth import hash_password
from backend.storage.database import SessionLocal
from backend.storage.models import Operator

DEFAULT_PASSWORD = "ranger14"

ADMIN   = {"callsign": "benoit", "rank": "OF-3", "role": "ADMIN"}
CAPTAIN = {"callsign": "capt",   "rank": "OF-2", "role": "BATTLE_CAPTAIN"}
OPS = [
    {"callsign": "ops1", "rank": "OR-1", "role": "OPERATOR"},
    {"callsign": "ops2", "rank": "OR-1", "role": "OPERATOR"},
    {"callsign": "ops3", "rank": "OR-1", "role": "OPERATOR"},
]


def _ensure(db: Session, callsign: str, password: str, rank: str, role: str) -> tuple[Operator, bool]:
    """Insert a default account if it isn't there yet. Returns (operator, created)."""
    existing = db.query(Operator).filter(Operator.callsign == callsign).first()
    if existing:
        return existing, False
    op = Operator(
        callsign=callsign,
        rank=rank,
        role=role,
        password_hash=hash_password(password),
    )
    db.add(op)
    return op, True


def seed(force: bool = False) -> dict[str, list[str]]:
    """Run the seed. Returns the callsigns created vs. those already present.

    `force` used to re-check an already-populated DB; that's now the default
    behaviour — `_ensure` is per-row idempotent so calling this on every boot
    is cheap and safe.
    """
    _ = force  # accepted for backwards compatibility with existing CLI scripts
    created: list[str] = []
    skipped: list[str] = []

    with SessionLocal() as db:
        for entry in [ADMIN, CAPTAIN, *OPS]:
            _, was_created = _ensure(
                db,
                entry["callsign"],
                DEFAULT_PASSWORD,
                entry["rank"],
                entry["role"],
            )
            (created if was_created else skipped).append(entry["callsign"])

        db.commit()

    return {"created": created, "existing": skipped}


def main() -> None:
    import argparse

    from backend.storage.database import init_db

    parser = argparse.ArgumentParser(description="Seed Arrow's operator table.")
    parser.add_argument("--force", action="store_true", help="(legacy) re-checks all entries; default behaviour now.")
    args = parser.parse_args()

    init_db()
    result = seed(force=args.force)
    if result["created"]:
        print(f"Created {len(result['created'])} operator(s):")
        for c in result["created"]:
            print(f"  - {c}  (password: {DEFAULT_PASSWORD})")
    if result["existing"]:
        print(f"Already present: {', '.join(result['existing'])}")
    if not result["created"] and not result["existing"]:
        print("Nothing seeded — empty DB but no defaults defined.")


if __name__ == "__main__":
    main()
