"""Eenheden en constantes.

Hoeken worden intern in streep (NATO mils, 6400 per cirkel) bijgehouden.
Afstanden in meter. Coordinaten in UTM (E, N) of MGRS-string.
"""
from __future__ import annotations

import math

MILS_PER_CIRCLE = 6400.0
DEG_PER_CIRCLE = 360.0


def deg_to_mils(deg: float) -> float:
    return deg * MILS_PER_CIRCLE / DEG_PER_CIRCLE


def mils_to_deg(mils: float) -> float:
    return mils * DEG_PER_CIRCLE / MILS_PER_CIRCLE


def rad_to_mils(rad: float) -> float:
    return rad * MILS_PER_CIRCLE / (2.0 * math.pi)


def mils_to_rad(mils: float) -> float:
    return mils * 2.0 * math.pi / MILS_PER_CIRCLE


def normalize_mils(mils: float) -> float:
    """Wikkel een streep-waarde naar [0, 6400)."""
    return mils % MILS_PER_CIRCLE
