"""Frozen-app entry point for Arrow Front.

PyInstaller freezes *this* module rather than ``front/main.py`` directly: a
script that lives inside the ``front`` package would be imported twice (once as
``__main__``, once as ``front.main``), which re-runs its module-level Chromium /
DYLD setup. Importing ``main`` from here keeps a single, clean entry point.
"""

from front.main import main

if __name__ == "__main__":
    main()
