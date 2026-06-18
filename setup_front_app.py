"""py2app build script — packages Arrow Front as a macOS ``.app`` bundle.

Why this exists
---------------
macOS Core Location only presents the permission prompt and delivers fixes to a
real ``.app`` bundle that has a bundle identifier and an Info.plist
``NSLocationWhenInUseUsageDescription`` key (see
``front/utils/location_provider.py``). Launched via ``uv run arrow-front`` the
host is a bare Python interpreter with no bundle identity, so authorisation
stays ``NotDetermined`` and no own-position fix is ever delivered. Wrapping the
app in a proper bundle is what unlocks native GPS / Wi-Fi positioning.

Build
-----
Recommended for running on your own machine (fast, and reliable with
PyQt6-WebEngine because Qt is referenced in place rather than relocated):

    uv run --extra front-bundle python setup_front_app.py py2app -A
    open "dist/Arrow Front.app"

Alias mode (``-A``) is not redistributable — it points back at this checkout and
its virtualenv — but it produces a genuine bundle id + Info.plist, which is all
Core Location needs locally.

Full standalone bundle (distributable, heavier, may need extra Qt tuning):

    uv run --extra front-bundle python setup_front_app.py py2app

The map JS libraries must already be present in ``front/map/html/lib/`` (they are
committed; otherwise run the app once or call ``front.map.setup_libs.download_libs``)
so they are bundled rather than written into the read-only app at runtime.
"""
from setuptools import setup

# py2app refuses to build when the distribution carries `install_requires`, but
# setuptools auto-populates it from this repo's pyproject.toml `[project]`
# dependencies. Clear it on the command before py2app inspects it.
try:
    from py2app.build_app import py2app as _py2app_cmd

    class py2app(_py2app_cmd):  # noqa: N801 (matches the command name)
        def finalize_options(self):
            self.distribution.install_requires = None
            super().finalize_options()

    CMDCLASS = {"py2app": py2app}
except ImportError:  # py2app only present with the `front-bundle` extra
    CMDCLASS = {}

APP = ["front/main.py"]

OPTIONS = {
    # PyQt apps must not use Carbon argv emulation.
    "argv_emulation": False,
    "iconfile": "front/resources/arrow_icon.icns",
    # Copy the whole front package so its data files come along: map/html/
    # (map.html + lib/), resources/ (icon, sounds). (No-op in alias mode, where
    # the package is referenced from this checkout.)
    "packages": ["front"],
    # pyobjc frameworks for native location are imported lazily, so name them
    # explicitly for the dependency graph.
    "includes": [
        "CoreLocation",
        "Foundation",
        "objc",
    ],
    "plist": {
        "CFBundleName": "Arrow Front",
        "CFBundleDisplayName": "Arrow Front",
        "CFBundleIdentifier": "com.arrow.front",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        # The reason for bundling: lets Core Location prompt for and then deliver
        # GPS / Wi-Fi fixes. Both keys provided for older/newer macOS.
        "NSLocationWhenInUseUsageDescription":
            "Arrow shows your own position on the tactical map.",
        "NSLocationUsageDescription":
            "Arrow shows your own position on the tactical map.",
    },
}

setup(
    name="Arrow Front",
    app=APP,
    options={"py2app": OPTIONS},
    cmdclass=CMDCLASS,
)
