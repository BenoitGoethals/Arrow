"""Download bundled JS/CSS map libraries into front/map/html/lib/.

Called automatically at startup if any file is missing.
Safe to call repeatedly — skips already-downloaded files.
"""

from pathlib import Path
import httpx

LIB_DIR = Path(__file__).parent / "html" / "lib"

LIBS = {
    "leaflet.js": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "leaflet.css": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "leaflet.draw.js": "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js",
    "leaflet.draw.css": "https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css",
    "milsymbol.js": "https://cdn.jsdelivr.net/npm/milsymbol@2.0.0/dist/milsymbol.js",
    "mgrs.js": "https://cdn.jsdelivr.net/npm/mgrs@1.0.0/dist/mgrs.js",
}


def libs_present() -> bool:
    return all((LIB_DIR / name).exists() for name in LIBS)


def download_libs(progress_cb=None) -> None:
    """Download all missing libraries. Raises on network failure."""
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in LIBS.items():
        dest = LIB_DIR / name
        if dest.exists():
            continue
        if progress_cb:
            progress_cb(f"Downloading {name}…")
        resp = httpx.get(url, timeout=30.0, follow_redirects=True, verify=False)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    if progress_cb:
        progress_cb("Map libraries ready.")


def ensure_libs() -> bool:
    """Return True if libs are ready, False if download failed (CDN fallback used)."""
    if libs_present():
        return True
    try:
        download_libs()
        return True
    except Exception:
        return False
