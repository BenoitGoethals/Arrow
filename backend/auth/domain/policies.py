"""Auth domain constants — pure values, no I/O."""

from __future__ import annotations

VALID_ROLES: frozenset[str] = frozenset(
    {
        "OPERATOR",
        "BATTLE_CAPTAIN",
        "ADMIN",
        "LOG",
        "FO",
        "CAS",
        "INTEL",
        "OPS",
        "MED",
        "CBRN",
        "FBC",
    }
)

MIN_PASSWORD_LEN: int = 8
LOCK_ATTEMPTS: int = 5
LOCK_MINUTES: int = 15
MFA_SESSION_MINUTES: int = 5
