#!/usr/bin/env python3
"""
simulate_logreps.py — Send 10 realistic NATO LOGREP reports to the backend.

Usage
  uv run python simulate_logreps.py
  uv run python simulate_logreps.py --backend https://78.21.255.210:6001
  uv run python simulate_logreps.py --mission "Op RANGER"   # adopt existing
  uv run python simulate_logreps.py --delay 0.5             # seconds between posts
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import time
from datetime import datetime, timezone, timedelta

import httpx
import sim_utils

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
)
log = logging.getLogger("sim_logrep")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Send 10 NATO LOGREPs to Arrow backend")
parser.add_argument(
    "--backend",
    default=(
        os.environ.get("ARROW_BACKEND_URL")
        or sim_utils.load_saved_backend()
        or "https://78.21.255.210:6200/api"
    ),
)
parser.add_argument(
    "--mission", default="Op LOGREP SIM", help="Mission name (created if absent)"
)
parser.add_argument(
    "--delay", type=float, default=0.3, help="Seconds between each POST (default 0.3)"
)
parser.add_argument(
    "--count", type=int, default=10, help="Number of LOGREPs to send (default 10)"
)
args = parser.parse_args()

BACKEND = args.backend.rstrip("/")

# ---------------------------------------------------------------------------
# Scenario data
# ---------------------------------------------------------------------------

UNITS = [
    ("1 PLT A COY", "A COY HQ"),
    ("2 PLT A COY", "A COY HQ"),
    ("3 PLT A COY", "A COY HQ"),
    ("1 PLT B COY", "B COY HQ"),
    ("2 PLT B COY", "B COY HQ"),
    ("SP COY", "BN HQ S4"),
    ("ENGR PLT", "BN HQ S4"),
    ("MED PLT", "BN HQ S4"),
    ("SIG PLT", "BN HQ S4"),
    ("RECCE PLT", "BN HQ"),
]

RATION_TYPES = ["COMPO A", "COMPO B", "IMP", "24HR ORP"]
VEHICLE_TYPES = ["LAND ROVER", "MASTIFF", "JACKAL", "RIDGBACK", "WARRIOR", "CVRT"]
ASSESSMENTS = ["GREEN", "AMBER", "RED"]


def dtg(offset_hours: float = 0.0) -> str:
    """Return a NATO DTG string offset from now."""
    t = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    return t.strftime("%d%H%MZ %b %y").upper()


def make_logrep(i: int) -> dict:
    """Build a realistic LOGREP payload for unit index i (0-based)."""
    unit, higher = UNITS[i % len(UNITS)]
    serial = f"LR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{i+1:03d}"

    rng = random.Random(i * 7 + 42)  # deterministic per unit for readable output

    auth = rng.randint(28, 34)
    present = rng.randint(max(20, auth - 8), auth)
    kia = rng.randint(0, 2)
    wia_evac = rng.randint(0, 3)
    wia_duty = rng.randint(0, 4)
    missing = rng.randint(0, 1)

    # Section B — supplies
    class_i = {
        "dos": round(rng.uniform(0.5, 3.0), 1),
        "ration_type": rng.choice(RATION_TYPES),
        "water_litres": rng.randint(40, 200),
    }
    class_iii = {
        "petrol_litres": rng.randint(0, 500),
        "diesel_litres": rng.randint(100, 2000),
        "oil_litres": rng.randint(0, 80),
        "coolant_litres": rng.randint(0, 40),
    }
    class_v = [
        {"ammo_type": "5.56MM BALL", "auth": 3600, "on_hand": rng.randint(1200, 3600)},
        {"ammo_type": "7.62MM GPMG", "auth": 1800, "on_hand": rng.randint(600, 1800)},
        {"ammo_type": "40MM HE", "auth": 120, "on_hand": rng.randint(20, 120)},
    ]
    class_viii = {
        "blood_units": rng.randint(0, 4),
        "morphine_mg": rng.randint(0, 200),
        "iv_bags": rng.randint(0, 20),
        "cas_bags": rng.randint(0, 6),
    }

    # Section C — equipment status
    veh_count = rng.randint(2, 5)
    section_c = []
    for _ in range(veh_count):
        total = rng.randint(2, 6)
        fmc = rng.randint(max(0, total - 3), total)
        pmc = rng.randint(0, total - fmc)
        nmc = total - fmc - pmc
        section_c.append(
            {
                "type": rng.choice(VEHICLE_TYPES),
                "auth": total,
                "on_hand": total,
                "fmc": fmc,
                "pmc": pmc,
                "nmc": nmc,
            }
        )

    # Section D — maintenance
    section_d = {
        "open_work_orders": rng.randint(0, 8),
        "deadline_equipment": rng.randint(0, 3),
        "parts_awaiting": rng.randint(0, 5),
    }

    # Section E — medical
    section_e = {
        "evacuations_24h": kia + wia_evac,
        "medic_operational": rng.choice([True, True, True, False]),
        "supplies_critical": rng.choice([False, False, True]),
        "note": "" if rng.random() > 0.3 else "MEDIC REQUEST FOR RESUPPLY",
    }

    # Section F — requests
    logreqs = []
    if class_i["dos"] < 1.5:
        logreqs.append(
            {
                "priority": "URGENT",
                "item": "24HR ORP x40",
                "quantity": 40,
                "eta": "AS SOON AS POSSIBLE",
            }
        )
    if class_iii["diesel_litres"] < 400:
        logreqs.append(
            {
                "priority": "ROUTINE",
                "item": "DIESEL JERRY CAN x20",
                "quantity": 20,
                "eta": "NLT 24H",
            }
        )
    if section_d["deadline_equipment"] > 1:
        logreqs.append(
            {
                "priority": "PRIORITY",
                "item": "TRACK LINK SETS",
                "quantity": 2,
                "eta": "NLT 12H",
            }
        )
    if not logreqs:
        logreqs.append(
            {"priority": "ROUTINE", "item": "NO REQUEST", "quantity": 0, "eta": ""}
        )

    # Section G — assessment
    fmc_ratio = sum(v["fmc"] for v in section_c) / max(
        1, sum(v["on_hand"] for v in section_c)
    )
    personnel_ratio = present / max(1, auth)
    if fmc_ratio >= 0.8 and personnel_ratio >= 0.85 and class_i["dos"] >= 1.5:
        assessment = "GREEN"
    elif fmc_ratio >= 0.5 and personnel_ratio >= 0.65:
        assessment = "AMBER"
    else:
        assessment = "RED"

    return {
        "serial": serial,
        "dtg": dtg(),
        "period_from": dtg(-24),
        "period_to": dtg(),
        "higher_hq": higher,
        "section_a": {
            "authorised": auth,
            "present": present,
            "kia": kia,
            "wia_evacuated": wia_evac,
            "wia_duty": wia_duty,
            "missing": missing,
            "sick": rng.randint(0, 3),
        },
        "section_b": {
            "class_i": class_i,
            "class_iii": class_iii,
            "class_v": class_v,
            "class_viii": class_viii,
            "class_ix_shortfalls": "" if rng.random() > 0.4 else "BRAKE PADS, FILTERS",
        },
        "section_c": section_c,
        "section_d": section_d,
        "section_e": section_e,
        "section_f": logreqs,
        "section_g": {
            "assessment": assessment,
            "remarks": f"Report from {unit}. Period covers last 24H.",
        },
        "_unit": unit,  # extra field for simulator output — ignored by renderer
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    sim_utils.save_backend(BACKEND)
    origin, prefix = sim_utils.split_base(BACKEND)
    base = f"{origin}{prefix}"

    with httpx.Client(timeout=15, verify=False) as client:
        # Authenticate
        log.info("Authenticating as benoit@%s …", origin)
        r = client.post(
            f"{base}/auth/login", data={"username": "benoit", "password": "ranger14"}
        )
        if r.status_code != 200:
            log.error("Login failed: %d %s", r.status_code, r.text[:200])
            return
        token = r.json()["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}
        log.info("Login OK")

        # Create / adopt mission
        mission_id = sim_utils.create_mission_sync(
            client,
            BACKEND,
            token,
            name=args.mission,
            description="LOGREP simulation — 10 unit periodic reports",
        )
        if mission_id is None:
            log.warning("No mission — LOGREPs will be posted without mission context")

        mission_hdr = {**hdr, "X-Mission-ID": str(mission_id)} if mission_id else hdr

        # Send LOGREPs
        log.info("Sending %d LOGREPs …", args.count)
        success = 0
        for i in range(args.count):
            payload = make_logrep(i)
            unit = payload.pop("_unit")

            r = client.post(
                f"{base}/reports",
                json={"type": "LOGREP", "payload": payload},
                headers=mission_hdr,
            )
            if r.status_code == 201:
                rep = r.json()
                log.info(
                    "  [%2d/%d] %-18s  serial=%-22s  id=%d  assessment=%s",
                    i + 1,
                    args.count,
                    unit,
                    payload["serial"],
                    rep["id"],
                    payload["section_g"]["assessment"],
                )
                success += 1
            else:
                log.error(
                    "  [%2d/%d] %-18s  FAILED %d %s",
                    i + 1,
                    args.count,
                    unit,
                    r.status_code,
                    r.text[:120],
                )

            if args.delay > 0 and i < args.count - 1:
                time.sleep(args.delay)

        log.info(
            "Done — %d/%d LOGREPs submitted (mission_id=%s)",
            success,
            args.count,
            mission_id,
        )


if __name__ == "__main__":
    main()
