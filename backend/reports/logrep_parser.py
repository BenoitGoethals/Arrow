"""Best-effort parser for free-form NATO LOGREP text messages.

Supports the most common formatting conventions:
  - Section headers like "A.", "A. PERSTAT", "SECTION A", "A -"
  - Key: Value pairs (case-insensitive)
  - Tabular ammo / equipment lines (TYPE QTY QTY …)
  - CoT-embedded XML LOGREP (<__logrep …> / <logrep …> elements)

The output dict mirrors the canonical Arrow LOGREP JSON schema
(section_a … section_g) so it can be stored directly as a Report payload.
"""

from __future__ import annotations

import re
from typing import Any


# ── Helpers ───────────────────────────────────────────────────────────────────

def _kv(text: str, *keys: str, default: Any = None) -> Any:
    """Find the first 'KEY: value' line matching any of *keys* (case-insensitive)."""
    for key in keys:
        m = re.search(rf"(?im)^\s*{re.escape(key)}\s*[:\-]\s*(.+)", text)
        if m:
            return m.group(1).strip()
    return default


def _int(text: str, *keys: str, default: int = 0) -> int:
    v = _kv(text, *keys, default=None)
    if v is None:
        return default
    try:
        return int(re.sub(r"[^\d]", "", v.split()[0]))
    except (ValueError, IndexError):
        return default


def _float_val(text: str, *keys: str, default: float = 0.0) -> float:
    v = _kv(text, *keys, default=None)
    if v is None:
        return default
    try:
        return float(re.sub(r"[^\d.]", "", v.split()[0]))
    except (ValueError, IndexError):
        return default


def _section(text: str, letter: str) -> str:
    """Extract the text block for a given section letter (A-G)."""
    pattern = rf"(?im)^[ \t]*{letter}[\.\-\s].*?$"
    starts  = [m.start() for m in re.finditer(pattern, text)]
    if not starts:
        return ""
    start = starts[0]
    next_letter = chr(ord(letter) + 1)
    # Build next-section search only when a following letter exists (not past G)
    if next_letter <= "G":
        next_sec = re.search(
            rf"(?im)^[ \t]*[{next_letter}-G][\.\-\s]",
            text[start + 1:],
        )
        end = start + 1 + next_sec.start() if next_sec else len(text)
    else:
        end = len(text)
    return text[start:end]


# ── Section parsers ───────────────────────────────────────────────────────────

def _parse_perstat(block: str) -> dict:
    return {
        "authorised":    _int(block, "AUTH", "AUTHORISED", "AUTHORIZED", "STRENGTH AUTH"),
        "present":       _int(block, "PRESENT", "PRES", "EFFECTIVE"),
        "kia":           _int(block, "KIA", "KILLED"),
        "wia_evacuated": _int(block, "WIA EVAC", "WIA-EVAC", "WIAEVAC", "WIA(E)", "EVACUATED"),
        "wia_duty":      _int(block, "WIA DUTY", "WIA-DUTY", "WIA(D)", "DUTY"),
        "missing":       _int(block, "MISSING", "MIA"),
        "sick":          _int(block, "SICK", "ILL", "NON-EFFECTIVE"),
    }


def _parse_supply(block: str) -> dict:
    class_i = {
        "dos":         _float_val(block, "DOS", "DAYS OF SUPPLY"),
        "ration_type": _kv(block, "RATION TYPE", "RATION", "RATIONS", default=""),
        "water_litres":_float_val(block, "WATER", "H2O"),
    }
    class_iii = {
        "diesel_litres": _float_val(block, "DIESEL", "DSL"),
        "petrol_litres": _float_val(block, "PETROL", "PETROL ON HAND", "POH"),
        "avgas_litres":  _float_val(block, "AVGAS", "AVIATION FUEL"),
    }

    # Ammo table: lines like  "5.56MM BALL  4200  800"  or  "5.56  4200  -"
    ammo: list[dict] = []
    in_ammo = False
    for line in block.splitlines():
        if re.search(r"class\s*v|ammo|ammunition", line, re.I):
            in_ammo = True
            continue
        if in_ammo:
            if re.search(r"class\s*vi|class\s*vii|class\s*viii", line, re.I):
                break
            parts = re.split(r"\s{2,}|\t", line.strip())
            if len(parts) >= 2 and parts[0]:
                try:
                    ammo.append({
                        "type":        parts[0],
                        "on_hand":     int(re.sub(r"[^\d]", "", parts[1])) if len(parts) > 1 else 0,
                        "consumption": int(re.sub(r"[^\d]", "", parts[2])) if len(parts) > 2 else 0,
                    })
                except (ValueError, IndexError):
                    pass

    class_viii = {
        "morphine":    _int(block, "MORPHINE", "MORPHINE AUTO"),
        "tourniquets": _int(block, "TOURNIQUET", "TOURNIQUETS"),
        "iv_bags":     _int(block, "IV BAG", "IV BAGS", "IV"),
        "shortfalls":  _kv(block, "VIII SHORTFALL", "MED SHORTFALL", default=""),
    }
    return {
        "class_i":   class_i,
        "class_iii": class_iii,
        "class_v":   ammo,
        "class_viii": class_viii,
        "class_ix_shortfalls": _kv(block, "IX SHORTFALL", "PARTS SHORTFALL", default=""),
    }


def _parse_eqpstat(block: str) -> list[dict]:
    rows: list[dict] = []
    header_seen = False
    for line in block.splitlines():
        if re.search(r"eqpstat|equipment stat", line, re.I):
            header_seen = True
            continue
        if not header_seen:
            continue
        parts = re.split(r"\s{2,}|\t", line.strip())
        if len(parts) >= 2 and parts[0]:
            def _i(s: str) -> int:
                try:
                    return int(re.sub(r"[^\d]", "", s))
                except ValueError:
                    return 0
            rows.append({
                "type":    parts[0],
                "auth":    _i(parts[1]) if len(parts) > 1 else 0,
                "on_hand": _i(parts[2]) if len(parts) > 2 else 0,
                "fmc":     _i(parts[3]) if len(parts) > 3 else 0,
                "pmc":     _i(parts[4]) if len(parts) > 4 else 0,
                "nmc":     _i(parts[5]) if len(parts) > 5 else 0,
            })
    return rows


def _parse_maintenance(block: str) -> dict:
    return {
        "open_work_orders":   _int(block, "OPEN WO", "WORK ORDERS", "WO"),
        "deadline_equipment": _kv(block, "DEADLINE", "NMC EQUIP", default=""),
        "parts_awaiting":     _kv(block, "PARTS AWAIT", "PARTS", "AWAITING", default=""),
    }


def _parse_medical(block: str) -> dict:
    return {
        "evacuations_24h": _int(block, "EVAC 24H", "EVACUATIONS", "CASEVAC 24H"),
        "medic_operational": not bool(re.search(r"medic.*not.*oper|medic.*non-oper", block, re.I)),
        "supplies_critical": bool(re.search(r"suppl.*critical|critical.*suppl", block, re.I)),
        "note": _kv(block, "MED NOTE", "MEDICAL NOTE", "NOTE", default=""),
    }


def _parse_logreq(block: str) -> list[dict]:
    reqs: list[dict] = []
    for line in block.splitlines():
        # Expect lines like  "1  5.56mm ball  10000 rds  D+3"
        m = re.match(r"^\s*(\d+)\s+(.+?)\s{2,}(\S.*?)\s{2,}(\S+)\s*$", line)
        if m:
            reqs.append({
                "priority": int(m.group(1)),
                "item":     m.group(2).strip(),
                "quantity": m.group(3).strip(),
                "eta":      m.group(4).strip(),
            })
        else:
            # Fallback: any line with PRIO / ITEM keywords
            mp = re.search(r"(?i)prio\s*[:\-]?\s*(\d+)", line)
            mi = re.search(r"(?i)item\s*[:\-]?\s*(.+)", line)
            if mp and mi:
                reqs.append({
                    "priority": int(mp.group(1)),
                    "item":     mi.group(1).strip(),
                    "quantity": "",
                    "eta":      "",
                })
    return reqs


def _parse_assessment(block: str) -> dict:
    for word in ("GREEN", "AMBER", "RED"):
        if word in block.upper():
            return {
                "assessment": word,
                "remarks":    _kv(block, "REMARKS", "COMMENT", "REMARK", default=""),
            }
    return {"assessment": "AMBER", "remarks": block.strip()[:300]}


# ── Top-level parser ──────────────────────────────────────────────────────────

def parse_logrep_text(text: str) -> dict:
    """Parse a free-form LOGREP text string into the Arrow LOGREP JSON schema.

    Returns a dict with keys: dtg, serial, higher_hq, period_from, period_to,
    section_a … section_g, source='text'.

    Never raises — partial / empty dicts are returned for sections that cannot
    be recognised.
    """
    result: dict[str, Any] = {
        "source":      "text",
        "dtg":         _kv(text, "DTG", "DATE TIME GROUP", default=""),
        "serial":      _kv(text, "SERIAL", "SER", default=""),
        "higher_hq":   _kv(text, "HIGHER HQ", "TO", "ADDRESSEE", default=""),
        "period_from": _kv(text, "PERIOD FROM", "FROM DATE", "FROM", default=""),
        "period_to":   _kv(text, "PERIOD TO", "TO DATE", "PERIOD", default=""),
        "section_a":   _parse_perstat(_section(text, "A")),
        "section_b":   _parse_supply(_section(text, "B")),
        "section_c":   _parse_eqpstat(_section(text, "C")),
        "section_d":   _parse_maintenance(_section(text, "D")),
        "section_e":   _parse_medical(_section(text, "E")),
        "section_f":   _parse_logreq(_section(text, "F")),
        "section_g":   _parse_assessment(_section(text, "G")),
    }
    return result


# ── CoT-embedded LOGREP ───────────────────────────────────────────────────────

def parse_logrep_cot(xml_text: str) -> dict | None:
    """Extract a LOGREP payload from a CoT XML string.

    ATAK / third-party systems may embed LOGREP data inside a CoT event's
    <detail> element either as:
      <__logrep …>  or  <logrep …>
    with child elements per section.

    Returns None if no LOGREP element is found.
    """
    from lxml import etree
    _SAFE = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(
            xml_text.encode() if isinstance(xml_text, str) else xml_text,
            _SAFE,
        )
    except etree.XMLSyntaxError:
        return None

    lr = root.find("detail/__logrep") or root.find("detail/logrep")
    if lr is None:
        return None

    def _ai(el: Any, attr: str, default: int = 0) -> int:
        try:
            return int(el.get(attr, default))
        except (ValueError, TypeError):
            return default

    def _af(el: Any, attr: str, default: float = 0.0) -> float:
        try:
            return float(el.get(attr, default))
        except (ValueError, TypeError):
            return default

    perstat = lr.find("perstat")
    supply  = lr.find("supply")
    eqp     = lr.find("eqpstat")
    maint   = lr.find("maintenance")
    med     = lr.find("medical")
    logreq  = lr.find("logreq")
    assess  = lr.find("assessment")

    section_a = {}
    if perstat is not None:
        section_a = {
            "authorised":    _ai(perstat, "auth"),
            "present":       _ai(perstat, "present"),
            "kia":           _ai(perstat, "kia"),
            "wia_evacuated": _ai(perstat, "wia_evacuated"),
            "wia_duty":      _ai(perstat, "wia_duty"),
            "missing":       _ai(perstat, "missing"),
            "sick":          _ai(perstat, "sick"),
        }

    section_b: dict = {}
    if supply is not None:
        ci  = supply.find("class_i")
        ciii = supply.find("class_iii")
        cv  = supply.findall("class_v/item") or supply.findall("ammo")
        cviii = supply.find("class_viii")
        section_b = {
            "class_i": {
                "dos":          _af(ci,  "dos")          if ci  is not None else 0.0,
                "ration_type":  ci.get("ration_type", "") if ci  is not None else "",
                "water_litres": _af(ci,  "water_litres") if ci  is not None else 0.0,
            },
            "class_iii": {
                "diesel_litres": _af(ciii, "diesel_litres") if ciii is not None else 0.0,
                "petrol_litres": _af(ciii, "petrol_litres") if ciii is not None else 0.0,
                "avgas_litres":  _af(ciii, "avgas_litres")  if ciii is not None else 0.0,
            },
            "class_v": [
                {
                    "type":        a.get("type", ""),
                    "on_hand":     _ai(a, "on_hand"),
                    "consumption": _ai(a, "consumption"),
                }
                for a in cv
            ],
            "class_viii": {
                "morphine":    _ai(cviii, "morphine")    if cviii is not None else 0,
                "tourniquets": _ai(cviii, "tourniquets") if cviii is not None else 0,
                "iv_bags":     _ai(cviii, "iv_bags")     if cviii is not None else 0,
                "shortfalls":  cviii.get("shortfalls", "") if cviii is not None else "",
            },
            "class_ix_shortfalls": supply.get("class_ix_shortfalls", ""),
        }

    section_c = []
    if eqp is not None:
        for item in eqp.findall("item"):
            section_c.append({
                "type":    item.get("type", ""),
                "auth":    _ai(item, "auth"),
                "on_hand": _ai(item, "on_hand"),
                "fmc":     _ai(item, "fmc"),
                "pmc":     _ai(item, "pmc"),
                "nmc":     _ai(item, "nmc"),
            })

    section_d = {}
    if maint is not None:
        section_d = {
            "open_work_orders":   _ai(maint, "open_work_orders"),
            "deadline_equipment": maint.get("deadline_equipment", ""),
            "parts_awaiting":     maint.get("parts_awaiting", ""),
        }

    section_e = {}
    if med is not None:
        section_e = {
            "evacuations_24h":  _ai(med, "evacuations_24h"),
            "medic_operational": med.get("medic_operational", "true").lower() != "false",
            "supplies_critical": med.get("supplies_critical", "false").lower() == "true",
            "note": med.get("note", "") or (med.text or "").strip(),
        }

    section_f = []
    if logreq is not None:
        for req in logreq.findall("req"):
            section_f.append({
                "priority": _ai(req, "priority"),
                "item":     req.get("item", ""),
                "quantity": req.get("quantity", ""),
                "eta":      req.get("eta", ""),
            })

    section_g = {"assessment": "AMBER", "remarks": ""}
    if assess is not None:
        section_g = {
            "assessment": assess.get("status", assess.get("assessment", "AMBER")).upper(),
            "remarks":    assess.get("remarks", "") or (assess.text or "").strip(),
        }

    return {
        "source":      "cot",
        "dtg":         lr.get("dtg", ""),
        "serial":      lr.get("serial", ""),
        "higher_hq":   lr.get("higher_hq", ""),
        "period_from": lr.get("period_from", ""),
        "period_to":   lr.get("period_to", ""),
        "section_a":   section_a,
        "section_b":   section_b,
        "section_c":   section_c,
        "section_d":   section_d,
        "section_e":   section_e,
        "section_f":   section_f,
        "section_g":   section_g,
    }
