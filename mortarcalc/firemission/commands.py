"""NATO-style call-out text generation: MTO and per-gun fire commands.

These are *display strings* — what the FDC chief calls out over comms, or what
appears on a printed fire-mission card. Format roughly follows FM 3-09 and
related NATO field manuals (simplified for an 81 mm mortar section).
"""
from __future__ import annotations

from .mission import FireMission, MethodOfFire
from .solution import PieceSolution


def format_mto(fm: FireMission, solutions: list[PieceSolution]) -> str:
    """Build the Message To Observer that the FDC sends back to the FO.

    Standard MTO elements:
      - Unit firing (section name + adjusting piece)
      - Number of rounds, shell, fuze
      - Target number (= our FM id)
      - Time of flight (used for the adjusting round)
    """
    if not solutions:
        return f"MTO {fm.id} — NO SOLUTION (no pieces in section '{fm.group_name}')"
    adj = solutions[0]                       # adjusting piece = first in section
    n_guns = len(solutions)
    rnd_text = "1 round" if fm.method_of_fire == MethodOfFire.AF else f"{fm.rounds_per_piece} rounds"
    return (
        f"MTO — TARGET {fm.id}\n"
        f"SECTION {fm.group_name.upper()} ({n_guns} pc) WILL FIRE\n"
        f"ADJ PIECE {adj.piece}\n"
        f"{rnd_text.upper()}, SHELL {fm.shell.upper()}, FUZE {fm.fuze.value.upper()}\n"
        f"TOF {adj.tof_s:.1f} SEC\n"
        f"OVER"
    )


def format_fire_command(s: PieceSolution, fm: FireMission, *, rounds_this_call: int | None = None) -> str:
    """Build the standard fire command for a single gun.

    Order matches doctrine:
      PIECE, FIRE MISSION, CHARGE, DEFLECTION, QUADRANT, SHELL/FUZE, ROUNDS, CONTROL
    """
    if rounds_this_call is None:
        rounds_this_call = 1 if fm.method_of_fire == MethodOfFire.AF else fm.rounds_per_piece
    rd_word = "ROUND" if rounds_this_call == 1 else "ROUNDS"
    ctrl_word = fm.control.value.upper().replace("_", " ")
    return (
        f"PIECE {s.piece}  —  FIRE MISSION {fm.id}\n"
        f"  CHARGE     {s.charge}\n"
        f"  DEFLECTION {s.deflection_mils:7.0f} mils  (azimuth {s.azimuth_mils:.0f})\n"
        f"  QUADRANT   {s.elevation_mils:7.0f} mils  (elevation)\n"
        f"  SHELL      {fm.shell.upper()}, FUZE {fm.fuze.value.upper()}\n"
        f"  {rounds_this_call} {rd_word}, {ctrl_word}\n"
        f"  TOF {s.tof_s:.1f} s, range {s.range_m:.0f} m"
    )


def format_all_fire_commands(fm: FireMission, solutions: list[PieceSolution]) -> str:
    """One block per piece, separated by blank lines."""
    return "\n\n".join(format_fire_command(s, fm) for s in solutions)
