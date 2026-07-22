"""Arrow Front (Kivy) — entry point."""

import multiprocessing

from front_kivy.utils.log_setup import setup_logging


def main():
    # The map runs in a child process (see front_kivy/map/map_process.py) —
    # required on macOS with the 'spawn' start method so it re-imports this
    # module cleanly without re-running main().
    multiprocessing.freeze_support()

    setup_logging()

    from front_kivy.app.shell import ArrowFrontKivyApp

    ArrowFrontKivyApp().run()


if __name__ == "__main__":
    main()
