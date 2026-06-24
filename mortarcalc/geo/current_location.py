"""macOS CoreLocation wrapper — geeft huidige positie als UTM Position.

Probeert eerst de pyobjc-CoreLocation API (in-process); valt terug op
`CoreLocationCLI` (extern, brew install corelocationcli) als die geïnstalleerd
is en de in-process API geweigerd wordt — die CLI is een gesigneerde .app
en krijgt wél een toestemmings-prompt van macOS.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time

from .coords import Position, latlon_to_utm


class LocationUnavailable(RuntimeError):
    """Geen huidige locatie te krijgen (geen permissie, timeout, niet-macOS, ...)."""


_DENIED_HINT = (
    "macOS weigert locatie aan dit Python-proces. "
    "Oplossingen:\n"
    "  1) Installeer CoreLocationCLI:  brew install corelocationcli\n"
    "     (gesigneerde tool die wél een toestemmings-prompt krijgt)\n"
    "  2) Of geef Terminal/PyCharm permissie in Systeeminstellingen → "
    "Privacy & Beveiliging → Locatievoorzieningen (werkt niet voor alle apps).\n"
    "  3) Of voer de coördinaten manueel in via de fallback-dialog."
)


_DelegateClass = None


def _get_delegate_class():
    global _DelegateClass
    if _DelegateClass is not None:
        return _DelegateClass
    from Foundation import NSObject
    import objc

    class _LocationDelegate(NSObject):
        def init(self):
            self = objc.super(_LocationDelegate, self).init()
            if self is None:
                return None
            self.location = None
            self.error = None
            return self

        def locationManager_didUpdateLocations_(self, manager, locations):
            if locations:
                self.location = locations[-1]

        def locationManager_didFailWithError_(self, manager, error):
            self.error = error

    _DelegateClass = _LocationDelegate
    return _DelegateClass


def get_current_position(timeout_s: float = 10.0) -> Position:
    """Vraag huidige Mac-locatie via CoreLocation; valt terug op CoreLocationCLI."""
    if sys.platform != "darwin":
        raise LocationUnavailable("Huidige locatie is alleen beschikbaar op macOS.")

    # 1) Probeer in-process via pyobjc
    try:
        return _via_pyobjc(timeout_s)
    except LocationUnavailable as e:
        in_process_error = str(e)

    # 2) Probeer CoreLocationCLI als die geïnstalleerd is
    cli = shutil.which("CoreLocationCLI")
    if cli:
        try:
            return _via_corelocationcli(cli, timeout_s)
        except LocationUnavailable as cli_err:
            raise LocationUnavailable(
                f"In-process: {in_process_error}\nCoreLocationCLI: {cli_err}\n\n{_DENIED_HINT}"
            )

    raise LocationUnavailable(f"{in_process_error}\n\n{_DENIED_HINT}")


def _via_pyobjc(timeout_s: float) -> Position:
    try:
        from CoreLocation import CLLocationManager
        from Foundation import NSRunLoop, NSDate
    except ImportError as e:
        raise LocationUnavailable(f"pyobjc-framework-CoreLocation ontbreekt: {e}")

    if not CLLocationManager.locationServicesEnabled():
        raise LocationUnavailable("Locatievoorzieningen staan uit in macOS-instellingen.")

    delegate_cls = _get_delegate_class()
    manager = CLLocationManager.alloc().init()
    delegate = delegate_cls.alloc().init()
    manager.setDelegate_(delegate)
    manager.requestWhenInUseAuthorization()
    manager.requestLocation()

    deadline = time.monotonic() + timeout_s
    loop = NSRunLoop.currentRunLoop()
    while time.monotonic() < deadline:
        if delegate.location is not None or delegate.error is not None:
            break
        loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

    if delegate.error is not None:
        raise LocationUnavailable(f"CoreLocation fout: {delegate.error.localizedDescription()}")
    if delegate.location is None:
        raise LocationUnavailable("Geen locatie binnen timeout.")

    coord = delegate.location.coordinate()
    altitude_m = float(delegate.location.altitude())
    return latlon_to_utm(lat=coord.latitude, lon=coord.longitude, altitude_m=altitude_m)


def _via_corelocationcli(cli_path: str, timeout_s: float) -> Position:
    """Roep `CoreLocationCLI -format "%latitude %longitude %altitude"` aan."""
    try:
        out = subprocess.run(
            [cli_path, "-format", "%latitude %longitude %altitude"],
            capture_output=True, text=True, timeout=timeout_s + 5, check=True,
        )
    except subprocess.TimeoutExpired:
        raise LocationUnavailable("CoreLocationCLI timeout.")
    except subprocess.CalledProcessError as e:
        raise LocationUnavailable(f"CoreLocationCLI: {e.stderr.strip() or 'onbekende fout'}")
    parts = out.stdout.strip().split()
    if len(parts) < 3:
        raise LocationUnavailable(f"CoreLocationCLI gaf onverwachte output: {out.stdout!r}")
    try:
        lat = float(parts[0]); lon = float(parts[1]); alt = float(parts[2])
    except ValueError:
        raise LocationUnavailable(f"CoreLocationCLI gaf niet-numerieke output: {out.stdout!r}")
    return latlon_to_utm(lat=lat, lon=lon, altitude_m=alt)
