"""`python -m sim_gui` / `uv run arrow-sim-gui` entry point."""

from __future__ import annotations

import sys

from sim_gui.app import main

if __name__ == "__main__":
    sys.exit(main())
