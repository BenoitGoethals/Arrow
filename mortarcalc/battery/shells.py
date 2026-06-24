"""Canonical munitie-types voor 81 mm mortieren (BE/NL doctrine).

Het ammo-model van Peloton ondersteunt arbitraire shell-strings; deze module
levert een gestandaardiseerde lijst zodat alle UI-onderdelen dezelfde set
defaults gebruiken (drop-downs, kolommen in de ammo-tabel, initiële voorraad
bij nieuwe stukken).

Een gebruiker kan via de Ammunition-tab nieuwe shell-types toevoegen — die
worden dan bovenop deze defaults bewaard in `Peloton.ammo`.
"""
from __future__ import annotations

# Canonical names — always upper-case (matches Peloton.set_ammo normalisation).
SHELL_HE    = "HE"      # High Explosive — hoofdmunitie
SHELL_SMOKE = "SMOKE"   # Rook (obscuratie / signal)
SHELL_ILLUM = "ILLUM"   # Lichtgranaat (illuminatie)
SHELL_WP    = "WP"      # White Phosphorus (rook + brand)

KNOWN_SHELLS: list[str] = [SHELL_HE, SHELL_SMOKE, SHELL_ILLUM, SHELL_WP]

SHELL_LABELS: dict[str, str] = {
    SHELL_HE:    "HE — High Explosive",
    SHELL_SMOKE: "SMOKE — Obscuration",
    SHELL_ILLUM: "ILLUM — Illumination",
    SHELL_WP:    "WP — White Phosphorus",
}

# Standaard initiële voorraad per stuk bij aanmaak. HE is hoofdmunitie; de
# anderen op 0 tenzij de gebruiker ze zet.
DEFAULT_INITIAL_STOCK: dict[str, int] = {
    SHELL_HE:    30,
    SHELL_SMOKE: 0,
    SHELL_ILLUM: 0,
    SHELL_WP:    0,
}


def normalise(shell: str) -> str:
    """Canoniek formaat: upper-case, gestript. Gebruik voor compare/lookup."""
    return shell.strip().upper()


def label_for(shell: str) -> str:
    """User-friendly label voor combo's; valt terug op de raw naam."""
    return SHELL_LABELS.get(normalise(shell), shell)
