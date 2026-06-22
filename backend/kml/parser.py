"""KML → flat JSON feature list.

Both web (Leaflet) and Android (OSMdroid) consume the same JSON so neither
needs an XML parser. KMZ archives are accepted: we unzip in-memory and read
the first ``*.kml`` entry (matches Google Earth's convention of ``doc.kml``).

Output shape (one dict per Placemark, after MultiGeometry is flattened):

    {
        "type":        "POINT" | "LINE" | "POLYGON",
        "name":        str,
        "description": str,
        "style":       {"stroke": "#aabbcc", "fill": "#aabbcc", "width": 2.0},
        # POINT      → coords = [lat, lon]                  (single pair)
        # LINE       → coords = [[lat, lon], ...]           (vertex list)
        # POLYGON    → coords = [[lat, lon], ...]           (outer ring)
        "coords":      list,
    }

Coordinates are returned as ``[lat, lon]`` pairs because every consumer
(Leaflet's ``L.polygon``, OSMdroid's ``GeoPoint``) wants lat-first.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Iterable, cast

from lxml import etree

# KML 2.2 / 2.3 namespaces — accept both.
_NS = {
    "k": "http://www.opengis.net/kml/2.2",
    "k3": "http://www.opengis.net/kml/2.3",
    "gx": "http://www.google.com/kml/ext/2.2",
}

# KML coordinates: "lon,lat[,alt] lon,lat[,alt] ..." (whitespace-separated).
_COORD_RE = re.compile(r"[\s\n\r\t]+")


class KmlParseError(ValueError):
    """Raised when the upload is not a recognisable KML/KMZ document."""


def _strip_ns(tag: object) -> str:
    """Return the local name of an lxml tag, or ``""`` for non-element nodes.

    lxml represents Comment/ProcessingInstruction nodes by setting ``.tag`` to
    a *callable* (``etree.Comment`` / ``etree.ProcessingInstruction``). Naive
    string handling there crashes — return an empty string so callers can
    filter the node out by an inequality check.
    """
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_all(root: etree._Element, local: str) -> list[etree._Element]:
    """Find descendants by local name, namespace-agnostic.

    Authoring tools sprinkle KML across two namespaces (2.2 vs 2.3) and
    sometimes drop them entirely on hand-rolled files. Iterating with
    ``iter()`` and filtering on the local part is the only thing that
    catches all variants without writing each XPath three times.
    """
    return [e for e in root.iter() if _strip_ns(e.tag) == local]


def _local_child(node: etree._Element, local: str) -> etree._Element | None:
    for c in node:
        if _strip_ns(c.tag) == local:
            return c
    return None


def _local_text(node: etree._Element, local: str) -> str:
    c = _local_child(node, local)
    if c is None or c.text is None:
        return ""
    return c.text.strip()


def _parse_coords(text: str) -> list[tuple[float, float]]:
    """KML lon,lat[,alt] tuples → [(lat, lon), ...]."""
    out: list[tuple[float, float]] = []
    for tok in _COORD_RE.split(text.strip()):
        if not tok:
            continue
        parts = tok.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue
        # Sanity bounds — drop obvious garbage rather than throw, so a single
        # bad vertex doesn't kill the whole import.
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            continue
        out.append((lat, lon))
    return out


def _abgr_to_hex(abgr: str) -> str | None:
    """KML colours are ``aabbggrr`` hex; convert to web ``#rrggbb``."""
    s = abgr.strip().lower()
    if len(s) != 8 or any(c not in "0123456789abcdef" for c in s):
        return None
    # Drop alpha, swap BB GG RR -> RR GG BB.
    return f"#{s[6:8]}{s[4:6]}{s[2:4]}"


def _collect_styles(root: etree._Element) -> dict[str, dict[str, str | float]]:
    """Build a {style_id: {stroke,fill,width}} map.

    Resolves ``<StyleMap>`` → ``<Style>`` indirection so a Placemark that
    points at a StyleMap still gets the underlying colours. We pick the
    ``normal`` pair; the ``highlight`` pair is reserved for hover state
    on the desktop client and would just confuse the static map view.
    """
    styles: dict[str, dict[str, str | float]] = {}

    for style in _find_all(root, "Style"):
        sid = style.get("id")
        if not sid:
            continue
        entry: dict[str, str | float] = {}
        line = _local_child(style, "LineStyle")
        if line is not None:
            colour = _abgr_to_hex(_local_text(line, "color"))
            if colour:
                entry["stroke"] = colour
            width = _local_text(line, "width")
            if width:
                try:
                    entry["width"] = float(width)
                except ValueError:
                    pass
        poly = _local_child(style, "PolyStyle")
        if poly is not None:
            colour = _abgr_to_hex(_local_text(poly, "color"))
            if colour:
                entry["fill"] = colour
        icon = _local_child(style, "IconStyle")
        if icon is not None:
            colour = _abgr_to_hex(_local_text(icon, "color"))
            if colour:
                entry["stroke"] = colour
        styles[sid] = entry

    for smap in _find_all(root, "StyleMap"):
        sid = smap.get("id")
        if not sid:
            continue
        chosen_ref: str | None = None
        for pair in smap:
            if _strip_ns(pair.tag) != "Pair":
                continue
            key = _local_text(pair, "key")
            ref = _local_text(pair, "styleUrl").lstrip("#")
            if key == "normal" and ref:
                chosen_ref = ref
                break
        if chosen_ref and chosen_ref in styles:
            styles[sid] = styles[chosen_ref]

    return styles


def _placemark_geometries(placemark: etree._Element) -> Iterable[etree._Element]:
    """Yield primitive geometry nodes, flattening MultiGeometry."""
    for child in placemark:
        local = _strip_ns(child.tag)
        if local == "MultiGeometry":
            yield from _placemark_geometries(child)
        elif local in {
            "Point",
            "LineString",
            "LinearRing",
            "Polygon",
            "Track",
            "MultiTrack",
        }:
            yield child


def _polygon_outer_coords(poly: etree._Element) -> list[tuple[float, float]]:
    """Return the outer ring vertices of a Polygon, ignoring inner holes.

    OSMdroid's ``Polygon.setPoints`` and Leaflet's ``L.polygon`` both accept
    the outer ring directly. We deliberately drop ``innerBoundaryIs`` because
    rendering holes from raw KML would need a per-platform "subtract" pass
    that isn't worth the code for our tactical overlays.
    """
    outer = None
    for child in poly:
        if _strip_ns(child.tag) == "outerBoundaryIs":
            outer = child
            break
    if outer is None:
        return []
    ring = None
    for child in outer:
        if _strip_ns(child.tag) == "LinearRing":
            ring = child
            break
    if ring is None:
        return []
    return _parse_coords(_local_text(ring, "coordinates"))


def _extract_features(root: etree._Element) -> list[dict]:
    styles = _collect_styles(root)
    out: list[dict] = []

    for pm in _find_all(root, "Placemark"):
        name = _local_text(pm, "name")
        desc = _local_text(pm, "description")
        style_ref = _local_text(pm, "styleUrl").lstrip("#")
        style = styles.get(style_ref, {})

        for geom in _placemark_geometries(pm):
            local = _strip_ns(geom.tag)
            if local == "Point":
                pts = _parse_coords(_local_text(geom, "coordinates"))
                if pts:
                    lat, lon = pts[0]
                    out.append(
                        {
                            "type": "POINT",
                            "name": name,
                            "description": desc,
                            "style": style,
                            "coords": [lat, lon],
                        }
                    )
            elif local in {"LineString", "LinearRing"}:
                pts = _parse_coords(_local_text(geom, "coordinates"))
                if len(pts) >= 2:
                    out.append(
                        {
                            "type": "LINE",
                            "name": name,
                            "description": desc,
                            "style": style,
                            "coords": [list(p) for p in pts],
                        }
                    )
            elif local == "Polygon":
                pts = _polygon_outer_coords(geom)
                if len(pts) >= 3:
                    out.append(
                        {
                            "type": "POLYGON",
                            "name": name,
                            "description": desc,
                            "style": style,
                            "coords": [list(p) for p in pts],
                        }
                    )
            # gx:Track / Track / MultiTrack — rare in tactical overlays;
            # we skip them rather than try to time-resolve the samples.

    return out


def _read_kml_bytes(data: bytes) -> bytes:
    """Return raw KML XML, unwrapping a KMZ archive if needed."""
    if data[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise KmlParseError(f"KMZ archive is corrupt: {exc}")
        # Prefer doc.kml (Google Earth's convention), else the first .kml entry.
        names = zf.namelist()
        target = next((n for n in names if n.lower() == "doc.kml"), None)
        if target is None:
            target = next((n for n in names if n.lower().endswith(".kml")), None)
        if target is None:
            raise KmlParseError("KMZ archive contains no .kml document")
        return zf.read(target)
    return data


def parse_kml(
    data: bytes,
) -> tuple[list[dict], tuple[float, float, float, float] | None]:
    """Parse KML/KMZ bytes into (features, bbox).

    ``bbox`` is ``(min_lon, min_lat, max_lon, max_lat)`` over every coordinate
    we extract — useful for the web client's "fit to layer" button and the
    Android client's auto-center on enable.
    """
    xml = _read_kml_bytes(data)
    try:
        # ``resolve_entities=False`` blocks billion-laughs / external-entity
        # attacks. KML never legitimately needs entity expansion.
        parser = etree.XMLParser(
            resolve_entities=False, no_network=True, huge_tree=False
        )
        root = etree.fromstring(xml, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise KmlParseError(f"KML is not valid XML: {exc}")

    features = _extract_features(cast(etree._Element, root))

    min_lon = 180.0
    min_lat = 90.0
    max_lon = -180.0
    max_lat = -90.0
    found = False
    for f in features:
        if f["type"] == "POINT":
            lat, lon = f["coords"]
            pts = [(lat, lon)]
        else:
            pts = [(p[0], p[1]) for p in f["coords"]]
        for lat, lon in pts:
            found = True
            if lon < min_lon:
                min_lon = lon
            if lat < min_lat:
                min_lat = lat
            if lon > max_lon:
                max_lon = lon
            if lat > max_lat:
                max_lat = lat

    bbox = (min_lon, min_lat, max_lon, max_lat) if found else None
    return features, bbox
