"""Native macOS Core Location provider for the front desktop COP.

Why this exists
---------------
QtWebEngine's ``navigator.geolocation`` does not resolve a fix on macOS: the
embedded Chromium has no network-geolocation provider configured and Core
Location is not wired into it, so the in-page GPS watcher (see ``map.html``)
just times out with ``POSITION_UNAVAILABLE`` and falls back to a dead Wi-Fi
watcher that also fails.

This module asks macOS directly through Core Location, which transparently uses
GPS when the hardware has it and falls back to Wi-Fi / network positioning
otherwise — i.e. exactly the "GPS if available, else Wi-Fi" behaviour we want.
The resolved fix is handed back to the map's own-position HUD via Qt signals.

Threading
---------
Core Location delivers its delegate callbacks on the main run loop. On macOS Qt
drives that same CFRunLoop, so callbacks arrive on the Qt main thread and it is
safe to emit Qt signals straight from the delegate.

Portability
-----------
No-op everywhere except macOS — ``is_supported()`` returns ``False`` and
``start()`` returns ``False`` so callers transparently keep the in-page JS
geolocation path on Linux/Windows.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QObject, pyqtSignal


def is_supported() -> bool:
    """True only on macOS, where Core Location is available."""
    return sys.platform == "darwin"


_USAGE_KEY = "NSLocationWhenInUseUsageDescription"
_USAGE_TEXT = "Arrow shows your own position on the tactical map."


def _inject_usage_description() -> None:
    """Best-effort: add a location usage string to the running bundle's info
    dictionary so an unbundled (uv-launched) process can present the Core
    Location authorisation prompt. A no-op once a value is present."""
    try:
        from Foundation import NSBundle  # noqa: PLC0415

        bundle = NSBundle.mainBundle()
        if bundle is None:
            return
        info = bundle.infoDictionary()
        if info is None:
            return
        if not info.get(_USAGE_KEY):
            info[_USAGE_KEY] = _USAGE_TEXT
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[LocationProvider] usage-description inject failed: {exc}", file=sys.stderr)


class LocationProvider(QObject):
    """Wraps a ``CLLocationManager`` and re-emits fixes as Qt signals."""

    # lat, lon, accuracy (m), heading (deg, -1 if unknown), source ("GPS"/"WIFI")
    position_changed = pyqtSignal(float, float, float, float, str)
    # short human-readable status for the HUD when there is no usable fix
    status_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = None
        self._delegate = None

    def start(self, high_accuracy: bool = True) -> bool:
        """Begin location updates. Returns False if unavailable (caller falls back)."""
        if not is_supported():
            return False
        try:
            from CoreLocation import (  # noqa: PLC0415  (lazy: macOS-only dep)
                CLLocationManager,
                kCLLocationAccuracyBest,
                kCLLocationAccuracyHundredMeters,
            )
        except Exception as exc:  # pyobjc-framework-CoreLocation not installed
            print(f"[LocationProvider] Core Location unavailable: {exc}", file=sys.stderr)
            self.status_changed.emit("NO CORELOC")
            return False

        if _Delegate is None:
            self.status_changed.emit("NO CORELOC")
            return False

        if not CLLocationManager.locationServicesEnabled():
            self.status_changed.emit("LOC OFF")
            return False

        # macOS only presents the authorisation prompt (and only then delivers
        # fixes) when the running bundle advertises a usage description. Running
        # via `uv run` the host is a bare interpreter with no such key, so inject
        # one into the main bundle's info dictionary before requesting auth.
        _inject_usage_description()

        self._delegate = _Delegate.alloc().initWithOwner_(self)
        mgr = CLLocationManager.alloc().init()
        mgr.setDelegate_(self._delegate)
        mgr.setDesiredAccuracy_(
            kCLLocationAccuracyBest if high_accuracy else kCLLocationAccuracyHundredMeters
        )
        mgr.setDistanceFilter_(5.0)  # metres of movement before a fresh callback
        # Best-effort authorisation prompt. An unbundled Python process may not be
        # able to present the prompt, in which case the delegate reports DENIED.
        try:
            mgr.requestWhenInUseAuthorization()
        except Exception:
            pass
        mgr.startUpdatingLocation()
        self._manager = mgr
        self.status_changed.emit("SEARCHING…")
        return True

    def stop(self):
        if self._manager is not None:
            self._manager.stopUpdatingLocation()
            self._manager.setDelegate_(None)
            self._manager = None
        self._delegate = None

    # -- called by the Obj-C delegate (already on the Qt main thread) ----------
    def _emit_position(self, lat: float, lon: float, acc: float,
                       heading: float, source: str):
        self.position_changed.emit(lat, lon, acc, heading, source)

    def _emit_status(self, text: str):
        self.status_changed.emit(text)


# ---------------------------------------------------------------------------
# Obj-C delegate — defined only on macOS so importing this module is harmless
# on other platforms and when pyobjc is absent.
# ---------------------------------------------------------------------------
_Delegate = None

if is_supported():
    try:
        import objc  # noqa: PLC0415
        from Foundation import NSObject  # noqa: PLC0415

        class _Delegate(NSObject):  # type: ignore[no-redef]
            def initWithOwner_(self, owner):
                self = objc.super(_Delegate, self).init()
                if self is None:
                    return None
                self._owner = owner
                return self

            # Core Location delivers an array of locations, newest last.
            def locationManager_didUpdateLocations_(self, manager, locations):
                loc = locations.lastObject()
                if loc is None:
                    return
                acc = float(loc.horizontalAccuracy())
                if acc < 0:
                    return  # negative accuracy == invalid fix
                coord = loc.coordinate()
                course = float(loc.course())
                heading = course if course >= 0 else -1.0
                # Macs rarely have GPS; treat a tight fix as GPS, loose as Wi-Fi.
                source = "GPS" if acc <= 65 else "WIFI"
                self._owner._emit_position(
                    float(coord.latitude), float(coord.longitude), acc, heading, source
                )

            def locationManager_didFailWithError_(self, manager, error):
                # kCLErrorDenied == 1; anything else is a transient "no fix yet".
                if int(error.code()) == 1:
                    self._owner._emit_status("DENIED")
                else:
                    self._owner._emit_status("NO FIX")

            # Modern single-argument authorisation callback.
            def locationManagerDidChangeAuthorization_(self, manager):
                try:
                    status = int(manager.authorizationStatus())
                except Exception:
                    return
                # 0 notDetermined, 1 restricted, 2 denied, 3 always, 4 whenInUse
                if status in (1, 2):
                    self._owner._emit_status("DENIED")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[LocationProvider] delegate init failed: {exc}", file=sys.stderr)
        _Delegate = None
