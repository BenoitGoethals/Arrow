"""Render an OPORD as PDF using ReportLab.

Map snapshots are pulled from the existing ``photos/`` storage path so the
encryption-at-rest support there is preserved.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from backend.storage.models import Opord, Photo

# photos router stores files under data/photos with optional .enc suffix
PHOTO_DIR = Path("data/photos")


def _decrypt_if_needed(path: Path) -> bytes:
    raw = path.read_bytes()
    if path.suffix != ".enc":
        return raw
    import os as _os
    key_hex = _os.environ.get("ARROW_PHOTO_KEY", "")
    if len(key_hex) != 64:
        return raw
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aes = AESGCM(bytes.fromhex(key_hex))
    return aes.decrypt(raw[:12], raw[12:], None)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title":   ParagraphStyle("title", parent=base["Title"], fontSize=16, spaceAfter=8),
        "h1":      ParagraphStyle("h1", parent=base["Heading1"], fontSize=12, spaceBefore=10, spaceAfter=4, textColor="#1f2a44"),
        "h2":      ParagraphStyle("h2", parent=base["Heading2"], fontSize=10, spaceBefore=6, spaceAfter=2, textColor="#374151"),
        "body":    ParagraphStyle("body", parent=base["BodyText"], fontSize=9.5, leading=12),
        "meta":    ParagraphStyle("meta", parent=base["BodyText"], fontSize=8, textColor="#475569"),
        "classif": ParagraphStyle("classif", parent=base["BodyText"], fontSize=10, alignment=1, textColor="#b91c1c", spaceAfter=8),
    }


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe = safe.replace("\n", "<br/>")
    return Paragraph(safe or "—", style)


def _block(label: str, value: Any, styles: dict[str, ParagraphStyle]) -> list:
    if value is None or value == "" or value == [] or value == {}:
        return []
    if isinstance(value, dict):
        out = [Paragraph(f"<b>{label}</b>", styles["h2"])]
        for k, v in value.items():
            out.extend(_block(k.replace("_", " ").title(), v, styles))
        return out
    if isinstance(value, list):
        text = "<br/>".join(f"• {item}" for item in value if str(item).strip())
        return [Paragraph(f"<b>{label}:</b> ", styles["h2"]), _para(text, styles["body"])]
    return [Paragraph(f"<b>{label}:</b>", styles["h2"]), _para(str(value), styles["body"])]


def render_opord_pdf(opord: Opord, photos_by_id: dict[int, Photo]) -> bytes:
    """Return PDF bytes for the OPORD; ``photos_by_id`` resolves snapshots."""
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=f"OPORD {opord.opord_number or opord.id} — {opord.title}",
    )
    story: list = []

    story.append(Paragraph(opord.classification or "UNCLASSIFIED", styles["classif"]))
    story.append(Paragraph(
        f"OPERATION ORDER {opord.opord_number or ''} — {opord.title}".strip(),
        styles["title"],
    ))
    meta = (
        f"DTG: {opord.dtg or '—'} &nbsp;&nbsp; TZ: {opord.time_zone} "
        f"&nbsp;&nbsp; Status: {opord.status}"
    )
    story.append(Paragraph(meta, styles["meta"]))
    if opord.references:
        story.append(Paragraph("<b>References:</b>", styles["h2"]))
        story.append(_para(opord.references, styles["body"]))
    if opord.task_organization:
        story.append(Paragraph("<b>Task Organization:</b>", styles["h2"]))
        story.append(_para(opord.task_organization, styles["body"]))

    def _load_json(s: str) -> dict:
        try:
            return json.loads(s) if s else {}
        except Exception:
            return {}

    sit = _load_json(opord.situation)
    exe = _load_json(opord.execution)
    sus = _load_json(opord.sustainment)
    cs  = _load_json(opord.command_signal)
    snaps = _load_json(opord.map_snapshots) if isinstance(opord.map_snapshots, str) else (opord.map_snapshots or [])

    story.append(Paragraph("1. SITUATION", styles["h1"]))
    for k, v in sit.items():
        story.extend(_block(k.replace("_", " ").title(), v, styles))

    story.append(Paragraph("2. MISSION", styles["h1"]))
    story.append(_para(opord.mission, styles["body"]))

    story.append(Paragraph("3. EXECUTION", styles["h1"]))
    for k, v in exe.items():
        story.extend(_block(k.replace("_", " ").title(), v, styles))

    story.append(Paragraph("4. SUSTAINMENT", styles["h1"]))
    for k, v in sus.items():
        story.extend(_block(k.replace("_", " ").title(), v, styles))

    story.append(Paragraph("5. COMMAND AND SIGNAL", styles["h1"]))
    for k, v in cs.items():
        story.extend(_block(k.replace("_", " ").title(), v, styles))

    if snaps:
        story.append(PageBreak())
        story.append(Paragraph("MAP SNAPSHOTS", styles["h1"]))
        for snap in snaps:
            story.append(Spacer(1, 6))
            label = snap.get("label") or f"Snapshot {snap.get('id')}"
            story.append(Paragraph(f"<b>{label}</b>", styles["h2"]))
            center = snap.get("center") or []
            if len(center) == 2:
                story.append(Paragraph(
                    f"Center: {center[0]:.5f}, {center[1]:.5f} &nbsp; Zoom: {snap.get('zoom', '')}",
                    styles["meta"],
                ))
            photo = photos_by_id.get(snap.get("photo_id"))
            if photo:
                path = PHOTO_DIR / photo.filename
                if path.exists():
                    try:
                        img_bytes = _decrypt_if_needed(path)
                        img = Image(ImageReader(io.BytesIO(img_bytes)), width=16 * cm, height=10 * cm, kind="proportional")
                        story.append(img)
                    except Exception:
                        story.append(Paragraph("<i>(snapshot unavailable)</i>", styles["meta"]))
            if snap.get("annotations"):
                story.append(_para(snap["annotations"], styles["body"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph(opord.classification or "UNCLASSIFIED", styles["classif"]))

    doc.build(story)
    return buf.getvalue()
