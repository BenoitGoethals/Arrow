"""TOTP wrapper — pyotp behind a small surface so tests/services don't import it directly."""

from __future__ import annotations

import pyotp

_ISSUER = "Arrow Tactical"
_VALID_WINDOW = 1


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, callsign: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=callsign, issuer_name=_ISSUER)


def verify(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=_VALID_WINDOW)
