#!/usr/bin/env python3
"""Generate Arrow_Pitch.pdf — a multi-page pitch deck for the ARROW platform.

Run:
    uv run python pitch_pdf.py             # writes Arrow_Pitch.pdf in cwd
    uv run python pitch_pdf.py --out X.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)

# ── Palette ──────────────────────────────────────────────────────────────────
NAVY      = HexColor("#0F2540")
NAVY_DEEP = HexColor("#081A30")
BLUE      = HexColor("#2D7FB8")
LIGHT     = HexColor("#9BE0FF")
ACCENT    = HexColor("#FBBF24")    # amber
RED       = HexColor("#DC2626")
GREEN     = HexColor("#22C55E")
GREY_LT   = HexColor("#E5E7EB")
GREY_MD   = HexColor("#94A3B8")
TEXT      = HexColor("#0F172A")

PAGE      = landscape(A4)            # 29.7 × 21 cm
PAGE_W, PAGE_H = PAGE
MARGIN    = 1.8 * cm


# ── Styles ──────────────────────────────────────────────────────────────────
def _styles() -> dict[str, ParagraphStyle]:
    ss = getSampleStyleSheet()
    return {
        "title":     ParagraphStyle("title", parent=ss["Title"],
                                    fontName="Helvetica-Bold", fontSize=42,
                                    textColor=white, alignment=TA_LEFT,
                                    leading=46, spaceAfter=8),
        "subtitle":  ParagraphStyle("subtitle", parent=ss["BodyText"],
                                    fontName="Helvetica", fontSize=18,
                                    textColor=LIGHT, alignment=TA_LEFT,
                                    leading=22, spaceAfter=10),
        "tag":       ParagraphStyle("tag", parent=ss["BodyText"],
                                    fontName="Helvetica-Bold", fontSize=10,
                                    textColor=ACCENT, alignment=TA_LEFT,
                                    leading=12, spaceAfter=4),
        "h1":        ParagraphStyle("h1", parent=ss["Heading1"],
                                    fontName="Helvetica-Bold", fontSize=26,
                                    textColor=NAVY, alignment=TA_LEFT,
                                    leading=30, spaceAfter=10),
        "h2":        ParagraphStyle("h2", parent=ss["Heading2"],
                                    fontName="Helvetica-Bold", fontSize=14,
                                    textColor=BLUE, alignment=TA_LEFT,
                                    leading=18, spaceBefore=6, spaceAfter=2),
        "body":      ParagraphStyle("body", parent=ss["BodyText"],
                                    fontName="Helvetica", fontSize=11.5,
                                    textColor=TEXT, leading=15.5, spaceAfter=3),
        "bullet":    ParagraphStyle("bullet", parent=ss["BodyText"],
                                    fontName="Helvetica", fontSize=11,
                                    textColor=TEXT, leading=14,
                                    leftIndent=14, bulletIndent=2, spaceAfter=2),
        "quote":     ParagraphStyle("quote", parent=ss["BodyText"],
                                    fontName="Helvetica-Oblique", fontSize=14,
                                    textColor=NAVY, leading=20,
                                    leftIndent=12, rightIndent=12, spaceAfter=6),
        "footer":    ParagraphStyle("footer", parent=ss["BodyText"],
                                    fontName="Helvetica", fontSize=8.5,
                                    textColor=GREY_MD, alignment=TA_CENTER,
                                    leading=10),
        "metric_n":  ParagraphStyle("metric_n", fontName="Helvetica-Bold",
                                    fontSize=36, textColor=ACCENT,
                                    alignment=TA_CENTER, leading=40),
        "metric_l":  ParagraphStyle("metric_l", fontName="Helvetica", fontSize=10,
                                    textColor=GREY_MD, alignment=TA_CENTER,
                                    leading=12, spaceAfter=0),
    }


S = _styles()


# ── Chrome (page decoration) ─────────────────────────────────────────────────
def _draw_chrome(canv: Canvas, doc: BaseDocTemplate, slide_no: int) -> None:
    """Draw header bar, footer line and page meta on every content slide."""
    canv.saveState()
    # Top accent strip
    canv.setFillColor(NAVY)
    canv.rect(0, PAGE_H - 0.9 * cm, PAGE_W, 0.9 * cm, stroke=0, fill=1)
    canv.setFillColor(ACCENT)
    canv.rect(0, PAGE_H - 1.0 * cm, PAGE_W, 0.1 * cm, stroke=0, fill=1)
    # Brand mark, left
    canv.setFillColor(white)
    canv.setFont("Helvetica-Bold", 11)
    canv.drawString(MARGIN, PAGE_H - 0.62 * cm, "▶  ARROW")
    canv.setFillColor(LIGHT)
    canv.setFont("Helvetica", 9)
    canv.drawString(MARGIN + 2.0 * cm, PAGE_H - 0.62 * cm,
                    "Soldier System Platform · Situational Awareness")
    # Slide counter, right
    canv.setFillColor(LIGHT)
    canv.setFont("Helvetica", 9)
    canv.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.62 * cm,
                         f"{slide_no:02d} / 10")
    # Footer rule
    canv.setStrokeColor(GREY_LT)
    canv.setLineWidth(0.4)
    canv.line(MARGIN, MARGIN - 0.5 * cm, PAGE_W - MARGIN, MARGIN - 0.5 * cm)
    canv.setFillColor(GREY_MD)
    canv.setFont("Helvetica", 8)
    canv.drawString(MARGIN, MARGIN - 0.9 * cm,
                    "ARROW — Open situational awareness for the warfighter")
    canv.drawRightString(PAGE_W - MARGIN, MARGIN - 0.9 * cm,
                         "github.com/BenoitGoethals/Arrow")
    canv.restoreState()


class SlideTemplate(PageTemplate):
    def __init__(self, slide_no: int, hero: bool = False):
        self.slide_no = slide_no
        self.hero     = hero
        x = MARGIN
        y = MARGIN
        w = PAGE_W - 2 * MARGIN
        h = PAGE_H - 2 * MARGIN - (0.6 * cm if not hero else 0)
        frame = Frame(x, y, w, h, leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0, showBoundary=0)
        super().__init__(id=f"slide-{slide_no}", frames=[frame])

    def beforeDrawPage(self, canv, doc):
        if self.hero:
            # Full-bleed dark background
            canv.saveState()
            canv.setFillColor(NAVY_DEEP)
            canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
            canv.setFillColor(NAVY)
            canv.rect(0, 0, PAGE_W, 1.4 * cm, stroke=0, fill=1)
            canv.setFillColor(ACCENT)
            canv.rect(0, 1.4 * cm, PAGE_W, 0.12 * cm, stroke=0, fill=1)
            # Subtle "compass" mark right side
            canv.setStrokeColor(BLUE)
            canv.setLineWidth(1.2)
            canv.circle(PAGE_W - 5.5 * cm, PAGE_H / 2, 3.2 * cm, stroke=1, fill=0)
            canv.setStrokeColor(ACCENT)
            canv.setLineWidth(0.5)
            canv.line(PAGE_W - 5.5 * cm, PAGE_H / 2 - 4 * cm,
                      PAGE_W - 5.5 * cm, PAGE_H / 2 + 4 * cm)
            canv.line(PAGE_W - 9.5 * cm, PAGE_H / 2,
                      PAGE_W - 1.5 * cm, PAGE_H / 2)
            canv.setFillColor(LIGHT)
            canv.setFont("Helvetica-Bold", 11)
            canv.drawCentredString(PAGE_W - 5.5 * cm, PAGE_H / 2 - 0.2 * cm, "N")
            canv.setFillColor(GREY_MD)
            canv.setFont("Helvetica", 8.5)
            canv.drawCentredString(PAGE_W / 2, 0.7 * cm,
                                   "ARROW — Open situational awareness for the warfighter")
            canv.restoreState()
        else:
            _draw_chrome(canv, doc, self.slide_no)


# ── Building blocks ──────────────────────────────────────────────────────────
def _bullet_para(text: str) -> Paragraph:
    return Paragraph(f"<bullet>•</bullet>&nbsp;&nbsp;{text}", S["bullet"])


def _metric(value: str, label: str) -> Table:
    t = Table([[Paragraph(value, S["metric_n"])],
               [Paragraph(label, S["metric_l"])]],
              colWidths=[5.6 * cm], rowHeights=[1.8 * cm, 0.7 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F8FAFC")),
        ("BOX",        (0, 0), (-1, -1), 0.5, HexColor("#E2E8F0")),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _two_col(left_flowables, right_flowables, ratio=(1, 1)) -> Table:
    """Two-column row of flowables."""
    cw = PAGE_W - 2 * MARGIN
    w_l = cw * ratio[0] / sum(ratio) - 0.4 * cm
    w_r = cw * ratio[1] / sum(ratio) - 0.4 * cm
    t = Table([[left_flowables, right_flowables]],
              colWidths=[w_l, w_r])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    return t


# ── Slide content ────────────────────────────────────────────────────────────
def slide_cover() -> list:
    return [
        Spacer(1, 4.0 * cm),
        Paragraph("ARROW", S["title"]),
        Paragraph("Open situational awareness for the warfighter.", S["subtitle"]),
        Spacer(1, 6 * mm),
        Paragraph("Faster OODA · Fewer screens · No black boxes.",
                  ParagraphStyle("tagline", fontName="Helvetica-Bold", fontSize=14,
                                 textColor=ACCENT, leading=18)),
        Spacer(1, 1.4 * cm),
        Paragraph(
            "A TAK-class soldier system — operator GPS, MIL-STD-2525, full NATO five-paragraph OPORDs, "
            "tactical messaging, fires, alerts and CoT bridge — on a stack you can read, run and own.",
            ParagraphStyle("kicker", fontName="Helvetica", fontSize=13,
                           textColor=LIGHT, leading=18)),
    ]


def slide_problem() -> list:
    body = [
        Paragraph("The problem.", S["h1"]),
        Spacer(1, 2 * mm),
        Paragraph("Commercial SA stacks solved this on paper a decade ago. "
                  "In practice, small units still face four hard frictions.", S["body"]),
        Spacer(1, 4 * mm),
        Paragraph("Fragmentation.", S["h2"]),
        Paragraph("Map, chat, fires, the OPORD PDF and the contact-report "
                  "notebook never live in the same place. Every cross-domain "
                  "hand-off is a screenshot or a verbal repeat over the net.", S["body"]),
        Paragraph("Closed ecosystems.", S["h2"]),
        Paragraph("Vendor lock-in, opaque protocols, hardware you can't audit, "
                  "license counts that don't survive a battalion rotation.", S["body"]),
        Paragraph("Slow OODA.", S["h2"]),
        Paragraph("OPORDs live in PDFs. 9-Lines live on radios. The "
                  "common operating picture is rarely common, rarely current.", S["body"]),
        Paragraph("Hard to interoperate.", S["h2"]),
        Paragraph("ATAK speaks CoT, NATO speaks APP-11, partners speak "
                  "what they were issued. Bridging them is a project, not a feature.", S["body"]),
    ]
    return body


def slide_what_arrow_is() -> list:
    left = [
        Paragraph("What ARROW is.", S["h1"]),
        Paragraph("A modern soldier-system platform — open, inspectable, "
                  "doctrinally honest.", S["body"]),
        Spacer(1, 4 * mm),
        Paragraph("Three tiers, one picture.", S["h2"]),
        Paragraph("FastAPI backend — JWT auth, SQLAlchemy, WebSocket pub/sub.", S["bullet"]),
        Paragraph("Flask Battle-Captain dashboard — live map, OPORD editor, FDC.", S["bullet"]),
        Paragraph("Android Jetpack-Compose client — OSMdroid, milsymbol, foreground GPS.", S["bullet"]),
        Spacer(1, 3 * mm),
        Paragraph("Every domain is a SOLID, pluggable module: auth, tracking, "
                  "alerts, messaging, reports, fires, OPORDs, battle "
                  "management, CoT, photos, streams.", S["body"]),
    ]
    right = [
        Paragraph("By the numbers.", S["h2"]),
        Spacer(1, 2 * mm),
        Table([
            [_metric("116", "tactical objects / scenario"),
             _metric("4",  "Ardennes COY plans")],
            [_metric("124", "backend tests passing"),
             _metric("24",  "live OPFOR units")],
        ], colWidths=[5.6 * cm] * 2, rowHeights=[2.7 * cm, 2.7 * cm],
            style=TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),
                              ("RIGHTPADDING",(0,0),(-1,-1),0),
                              ("TOPPADDING",(0,0),(-1,-1),2),
                              ("BOTTOMPADDING",(0,0),(-1,-1),2)])),
        Spacer(1, 4 * mm),
        Paragraph("Built in Python 3.14, Kotlin, modern web — no Electron, "
                  "no native blobs you can't read.", S["body"]),
    ]
    return [_two_col(left, right, ratio=(11, 9))]


def slide_capabilities() -> list:
    rows = [
        ["Live tracking",        "Operator GPS · online/offline · role-aware · 90-s heartbeat."],
        ["MIL-STD-2525",         "Friendly blue / enemy red / unknown yellow · all tactical control graphics drawable as either side · echelon designators."],
        ["OPORDs",               "Full five-paragraph NATO/US Operation Orders · server-rendered map snapshots with overlays · PDF export · sendable to operators · readable on Android."],
        ["Tactical messaging",   "Direct / group / broadcast · photo attachments · auto-dismiss notifications · 10-min chat toasts with inline reply."],
        ["Reports",              "Contact / Spot / CASEVAC / MEDEVAC / CAS 9-Liners · reviewer workflow · NATO CBRN 1–6 parser."],
        ["Fire missions",        "Call-for-fire · FDC dashboard · L16 81 mm firing solutions (charge, QE, deflection, TOF)."],
        ["Alerts",               "TIC · MEDICAL · EVAC · LOST_COMMS · one-tap broadcast · audio + visual escalation."],
        ["Streams",              "Operator camera → company TOC · MJPEG over WebSocket · persisted recordings."],
        ["CoT bridge",           "Cursor-on-Target XML in/out — interop with ATAK and partner systems."],
        ["Security",             "JWT + auto-secret · TOTP MFA · AES-256-GCM photo encryption at rest · NIST CSF audit log · rate limiting · CSP."],
    ]
    body = [Paragraph("What ARROW does today.", S["h1"]),
            Spacer(1, 3 * mm)]
    data = [[Paragraph(f"<b>{k}</b>", S["body"]),
             Paragraph(v, S["body"])] for k, v in rows]
    t = Table(data, colWidths=[4.6 * cm, PAGE_W - 2 * MARGIN - 4.6 * cm])
    t.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("BACKGROUND",   (0, 0), (0, -1), HexColor("#F0F6FC")),
        ("LINEBELOW",    (0, 0), (-1, -2), 0.25, GREY_LT),
    ]))
    body.append(t)
    return body


def slide_diff() -> list:
    items = [
        ("Single source of truth.",
         "One in-process broadcaster fans every event to every client. Swap "
         "for Redis/NATS without touching callers."),
        ("Open and auditable.",
         "Pure Python + Kotlin + standard web stack. Read the code, run the "
         "tests, deploy it. 124 tests passing."),
        ("Doctrinally honest.",
         "OPORDs are real OPORDs. Symbols are real MIL-STD-2525. PACE plans "
         "are real PACE. We speak the operator's language, not a vendor's."),
        ("Edge-tolerant.",
         "OSM tile cache · offline-zone manifests · foreground tracking that "
         "survives doze · WebSocket auto-reconnect · in-memory token "
         "blacklist when Redis is down."),
        ("Cross-domain by design.",
         "A contact report drops a marker, fires an alert, broadcasts on "
         "chat, lands in history, can be cited in the next OPORD — without "
         "any glue code."),
        ("Built for ROE.",
         "Every action gated: ADMIN / BATTLE_CAPTAIN / OPERATOR. Every event "
         "signed by a JWT subject. Every change in the audit log."),
    ]
    body = [Paragraph("What makes it different.", S["h1"]),
            Spacer(1, 3 * mm)]
    data = []
    for title, txt in items:
        data.append([
            Paragraph(f"<font color='#FBBF24'>■</font>", S["body"]),
            Paragraph(f"<b>{title}</b>  {txt}", S["body"]),
        ])
    t = Table(data, colWidths=[0.6 * cm, PAGE_W - 2 * MARGIN - 0.6 * cm])
    t.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ]))
    body.append(t)
    return body


def slide_scenario() -> list:
    body = [
        Paragraph("Why it matters — one screen, one fight.", S["h1"]),
        Spacer(1, 3 * mm),
        Paragraph(
            "A platoon leader with ARROW has <b>one screen</b> to:", S["body"]),
        _bullet_para("see where her people are,"),
        _bullet_para("see what the enemy is doing,"),
        _bullet_para("read the OPORD that brought her here,"),
        _bullet_para("send the contact report,"),
        _bullet_para("call fires on the position,"),
        _bullet_para("mark the casualty,"),
        _bullet_para("stream the room she just cleared,"),
        _bullet_para("coordinate with the adjacent unit on chat."),
        Spacer(1, 4 * mm),
        Paragraph(
            "— from the same phone, on the same battery, on the same JWT, "
            "with the same audit trail. No vendor in the loop. "
            "No license to expire. No data leaving her infrastructure.",
            S["quote"]),
    ]
    return body


def slide_demo() -> list:
    """Reference screens that exist in the build today."""
    body = [
        Paragraph("Operation IRON ARDENNES — the demo.", S["h1"]),
        Spacer(1, 2 * mm),
        Paragraph(
            "The simulator drops a full battalion-minus laydown into the "
            "Belgian Ardennes — four company plans against four real "
            "villages, with live OPFOR shuffling under each objective.",
            S["body"]),
        Spacer(1, 4 * mm),
    ]
    villages = [
        ("A CO",   "OBJ HAWK",   "Bastogne",            "attack E → W"),
        ("B CO",   "OBJ EAGLE",  "Houffalize",          "attack NE → SW"),
        ("C CO",   "OBJ FALCON", "La Roche-en-Ardenne", "attack W → E"),
        ("D CO",   "OBJ KITE",   "Vielsalm",            "attack N → S"),
    ]
    data = [["Unit", "Objective", "Village", "Axis"]] + villages
    t = Table(data, colWidths=[3.2 * cm, 4 * cm, 6 * cm, 5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 11),
        ("ALIGN",      (0, 0), (-1, -1), "LEFT"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#F8FAFC"), white]),
        ("GRID",       (0, 0), (-1, -1), 0.25, GREY_LT),
    ]))
    body.append(t)
    body.append(Spacer(1, 6 * mm))
    body.append(Paragraph(
        "Each plan exercises every graphic in the palette — OBJ_AREA, "
        "ATK_AXIS (main + supporting), DEF_AREA, COUNTERATTACK, AMBUSH, "
        "BLOCK, BYPASS, WITHDRAW, FLOT, FLET, BOUNDARY, three phase lines — "
        "plus hostile MIL-STD-2525C units (T-72, ATGM, mortar, sniper, "
        "MANPADS) and friendly POIs (CCP, BAS, LZ, AMMO, POL, HQ). "
        "OPFOR jitters every 25 s in real time so the picture moves.",
        S["body"]))
    return body


def slide_architecture() -> list:
    body = [
        Paragraph("Architecture.", S["h1"]),
        Spacer(1, 3 * mm),
        Paragraph("Backend — FastAPI", S["h2"]),
        Paragraph(
            "REST + WebSocket. JWT (auto-generated secret, persisted). "
            "SQLAlchemy on SQLite (Postgres-ready). One <i>broadcaster</i> "
            "singleton fans every realtime event onto channels: "
            "<font face='Courier'>tracking · tactical-object · alert · chat · report · fire-mission · opord · stream · presence</font>.",
            S["body"]),
        Paragraph("Web — Flask", S["h2"]),
        Paragraph(
            "Operational dashboard. Each capability is a blueprint with its own "
            "routes and templates. Frontend stores the JWT in localStorage and "
            "talks to the FastAPI backend directly; Flask serves only HTML/CSS/JS "
            "shells and a CSP-hardened reverse proxy under /api.",
            S["body"]),
        Paragraph("Android — Jetpack Compose", S["h2"]),
        Paragraph(
            "Standalone Gradle project. OSMdroid map, milsymbol-equivalent renderer, "
            "Fused Location foreground service, OkHttp + kotlinx.serialization, "
            "Compose-native screens for every domain. Composition root in "
            "<font face='Courier'>di/AppContainer.kt</font>.",
            S["body"]),
        Paragraph("Security posture", S["h2"]),
        Paragraph(
            "JWT with auto-rotated secret · TOTP MFA · account lockout · "
            "AES-256-GCM photo encryption at rest · structured JSON audit log · "
            "rate limiting (slowapi) · CSP / X-Frame-Options · Redis-backed "
            "token revocation (with in-memory fallback). Aligns to NIST CSF 2.0.",
            S["body"]),
    ]
    return body


def slide_roadmap() -> list:
    items = [
        ("Multi-domain interop", "Full CoT 2.0 · OGC GeoPackage · NATO ADatP-3 · OpenC2."),
        ("Battlefield AI",       "Snapshot → automatic symbol recognition; chat → automatic SITREP draft; sensor fusion across operator feeds."),
        ("Federation",           "Mesh of company TOCs gossiping state — disconnected ops, autonomous reconnect."),
        ("Coalition profile",    "Per-partner data partitions · ROE-aware sharing · automatic redaction."),
        ("Hardware",             "Reference deployments on EUD, Samsung S25 Tactical, Boxer-class command vehicles."),
    ]
    body = [Paragraph("Where it goes next.", S["h1"]),
            Spacer(1, 4 * mm)]
    for title, txt in items:
        body.append(Paragraph(f"<b>{title}.</b> &nbsp; {txt}", S["body"]))
        body.append(Spacer(1, 2 * mm))
    return body


def slide_ask() -> list:
    body = [
        Paragraph("The ask.", S["h1"]),
        Spacer(1, 4 * mm),
        Paragraph("Give us this — we give you a SA platform your operators "
                  "actually want to use, on infrastructure you own.", S["body"]),
        Spacer(1, 6 * mm),
    ]
    asks = [
        ("A pilot battalion",  "Six weeks · one rotation · real feedback."),
        ("A partner SI",       "Harden the deployment story — Caddy, Kubernetes, FedRAMP."),
        ("A coalition exercise", "Prove CoT and APP-11 interop in the wild."),
    ]
    for title, txt in asks:
        body.append(Paragraph(
            f"<font color='#FBBF24'>▶</font> &nbsp; <b>{title}.</b> &nbsp; {txt}",
            ParagraphStyle("ask", fontName="Helvetica", fontSize=14,
                           textColor=TEXT, leading=20, spaceAfter=4)))
    body.append(Spacer(1, 1.2 * cm))
    body.append(Paragraph(
        "ARROW — situational awareness, by warfighters, for warfighters.",
        S["quote"]))
    body.append(Paragraph(
        "Faster OODA. Fewer screens. No black boxes.",
        ParagraphStyle("close", fontName="Helvetica-Bold", fontSize=13,
                       textColor=BLUE, alignment=TA_LEFT, leading=18)))
    return body


def slide_thanks() -> list:
    return [
        Spacer(1, 4 * cm),
        Paragraph("Thank you.", S["title"]),
        Spacer(1, 6 * mm),
        Paragraph("Let's get your platoons on one screen.", S["subtitle"]),
        Spacer(1, 1.2 * cm),
        Paragraph("github.com/BenoitGoethals/Arrow",
                  ParagraphStyle("link", fontName="Courier", fontSize=14,
                                 textColor=ACCENT, leading=18)),
        Paragraph("benoit.goethals@gmail.com",
                  ParagraphStyle("mail", fontName="Helvetica", fontSize=12,
                                 textColor=LIGHT, leading=18)),
    ]


# ── Build doc ────────────────────────────────────────────────────────────────
def build(path: Path) -> None:
    doc = BaseDocTemplate(
        str(path), pagesize=PAGE,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title="ARROW — Pitch", author="ARROW", subject="Soldier System Platform",
    )

    # Hero (cover) + closing get a custom dark layout; the rest use the chrome.
    slides = [
        (slide_cover,        True),
        (slide_problem,      False),
        (slide_what_arrow_is,False),
        (slide_capabilities, False),
        (slide_diff,         False),
        (slide_scenario,     False),
        (slide_demo,         False),
        (slide_architecture, False),
        (slide_roadmap,      False),
        (slide_ask,          False),
        (slide_thanks,       True),
    ]
    doc.addPageTemplates([
        SlideTemplate(slide_no=i + 1, hero=hero)
        for i, (_, hero) in enumerate(slides)
    ])

    story: list = []
    for i, (fn, _hero) in enumerate(slides):
        if i:
            story.append(PageBreak())
        story.extend(fn())

    doc.build(story)
    print(f"Wrote {path}  ({path.stat().st_size / 1024:.1f} KB)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the ARROW pitch PDF.")
    ap.add_argument("--out", default="Arrow_Pitch.pdf",
                    help="Output PDF path (default: Arrow_Pitch.pdf in cwd)")
    args = ap.parse_args()
    build(Path(args.out))


if __name__ == "__main__":
    main()
