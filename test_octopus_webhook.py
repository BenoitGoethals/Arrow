#!/usr/bin/env python3
"""Fire test Octopus detection webhooks at an Arrow server.

Simulates the Octopus AI camera server sending detection events so you can
verify the full pipeline:  webhook → DB → WebSocket broadcast → browser toast.

Usage:
    uv run python test_octopus_webhook.py
    uv run python test_octopus_webhook.py --url http://192.168.0.X:6200
    uv run python test_octopus_webhook.py --url http://192.168.0.X:6200 --api-key SECRET
    uv run python test_octopus_webhook.py --count 10 --stream test-cam-01
    uv run python test_octopus_webhook.py --loop --interval 5
    uv run python test_octopus_webhook.py --burst 20          # rapid-fire 20 detections
    uv run python test_octopus_webhook.py --label drone --confidence 0.97
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx

# ── ANSI colours ────────────────────────────────────────────────────────────
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

DEFAULT_URL = "http://192.168.0.240:6200"

LABELS = ["person", "drone", "vehicle", "car", "truck", "animal"]

LABEL_DESCRIPTIONS = {
    "person": "Human figure detected in sector",
    "drone": "Unmanned aerial vehicle detected",
    "vehicle": "Ground vehicle detected",
    "car": "Passenger vehicle detected",
    "truck": "Heavy vehicle / truck detected",
    "animal": "Animal movement detected",
}

STREAM_IDS = [
    "cam-north-01",
    "cam-south-02",
    "cam-east-03",
    "cam-gate-04",
    "test-stream",
]


def _sign(payload: bytes, key: str) -> str:
    return "sha256=" + hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def _make_detection(
    label: str | None = None,
    stream_id: str | None = None,
    confidence: float | None = None,
    octopus_base_url: str = "",
) -> dict:
    lbl = label or random.choice(LABELS)
    sid = stream_id or random.choice(STREAM_IDS)
    # Point snapshot_url at the Octopus live-frame endpoint if we know the server URL
    snap = (
        f"{octopus_base_url.rstrip('/')}/api/client/streams/{sid}/snapshot"
        if octopus_base_url
        else ""
    )
    return {
        "event": "detection",
        "id": str(uuid.uuid4()),
        "stream_id": sid,
        "label": lbl,
        "confidence": (
            confidence
            if confidence is not None
            else round(random.uniform(0.70, 0.99), 2)
        ),
        "description": LABEL_DESCRIPTIONS.get(lbl, f"{lbl} detected"),
        "bbox": [
            round(random.uniform(0.05, 0.35), 3),
            round(random.uniform(0.05, 0.35), 3),
            round(random.uniform(0.40, 0.80), 3),
            round(random.uniform(0.40, 0.80), 3),
        ],
        "snapshot_url": snap,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _probe(base_url: str, client: httpx.Client) -> bool:
    """GET /api/octopus/webhook — confirm endpoint is alive."""
    url = base_url.rstrip("/") + "/api/octopus/webhook"
    try:
        r = client.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            sig = data.get("signature", "?")
            print(
                f"{GREEN}✓ Endpoint reachable{RESET}  "
                f"signature={CYAN}{sig}{RESET}  "
                f"octopus_url={DIM}{data.get('octopus_url') or '(not set)'}{RESET}"
            )
            return True
        else:
            print(f"{RED}✗ Endpoint returned HTTP {r.status_code}{RESET}")
            return False
    except Exception as exc:
        print(f"{RED}✗ Cannot reach {url}: {exc}{RESET}")
        return False


def _fire(
    base_url: str,
    api_key: str,
    detection: dict,
    client: httpx.Client,
    idx: int,
) -> bool:
    url = base_url.rstrip("/") + "/api/octopus/webhook"
    payload = json.dumps(detection).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Octopus-Signature"] = _sign(payload, api_key)

    ts = datetime.now().strftime("%H:%M:%S")
    label = detection["label"].upper()
    conf = int(detection["confidence"] * 100)
    stream = detection["stream_id"]

    try:
        r = client.post(url, content=payload, headers=headers, timeout=8)
    except Exception as exc:
        print(f"  {RED}[{ts}] #{idx:03d} FAILED — {exc}{RESET}")
        return False

    body = {}
    try:
        body = r.json()
    except Exception:
        pass

    if r.status_code == 200 and body.get("broadcast"):
        print(
            f"  {GREEN}[{ts}] #{idx:03d} ✓ broadcast{RESET}  "
            f"{BOLD}{label:<8}{RESET} {conf}%  stream={CYAN}{stream}{RESET}"
        )
        return True
    elif r.status_code == 200 and body.get("duplicate"):
        print(
            f"  {YELLOW}[{ts}] #{idx:03d} ~ duplicate{RESET}  {label} (event_id already in DB)"
        )
        return True
    elif r.status_code == 200 and body.get("skipped"):
        detail = body.get("detail", "event type not 'detection'")
        print(f"  {YELLOW}[{ts}] #{idx:03d} ~ skipped{RESET}  {detail}")
        return False
    elif r.status_code == 403:
        print(
            f"  {RED}[{ts}] #{idx:03d} ✗ 403 Forbidden{RESET}  "
            f"— signature {'mismatch' if api_key else 'missing (server requires API key)'}"
        )
        return False
    else:
        print(
            f"  {RED}[{ts}] #{idx:03d} ✗ HTTP {r.status_code}{RESET}  {str(body)[:120]}"
        )
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fire Octopus detection webhooks at Arrow"
    )
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"Arrow base URL (default: {DEFAULT_URL})"
    )
    parser.add_argument(
        "--api-key", default="", help="HMAC API key (if Arrow has one configured)"
    )
    parser.add_argument(
        "--count", type=int, default=3, help="Number of detections to fire (default: 3)"
    )
    parser.add_argument(
        "--stream", default="", help="Fixed stream_id (default: random)"
    )
    parser.add_argument(
        "--label",
        default="",
        choices=[""] + LABELS,
        help="Fixed label (default: random)",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        help="Fixed confidence 0–1 (default: random 0.70–0.99)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between detections (default: 2)",
    )
    parser.add_argument(
        "--loop", action="store_true", help="Run indefinitely until Ctrl+C"
    )
    parser.add_argument(
        "--burst",
        type=int,
        default=0,
        help="Fire N detections as fast as possible (overrides --count/--interval)",
    )
    parser.add_argument(
        "--octopus-url",
        default="",
        help="Octopus base URL for snapshot links e.g. http://192.168.0.240:8080",
    )
    parser.add_argument(
        "--no-probe", action="store_true", help="Skip the initial endpoint health check"
    )
    args = parser.parse_args()

    count = args.burst if args.burst else args.count
    interval = 0.0 if args.burst else args.interval
    oct_url = args.octopus_url

    print(f"\n{BOLD}Arrow Octopus Webhook Tester{RESET}")
    print(f"  Target      : {CYAN}{args.url}{RESET}")
    print(
        f"  API key     : {GREEN}set{RESET}"
        if args.api_key
        else f"  API key     : {YELLOW}none{RESET}"
    )
    print(
        f"  Snapshot src: {CYAN}{oct_url}{RESET}"
        if oct_url
        else f"  Snapshot src: {DIM}none (images will show 'No image'){RESET}"
    )
    print(
        f"  Mode        : {'burst x' + str(count) if args.burst else ('loop' if args.loop else f'{count} shot(s)')}"
    )
    print()

    with httpx.Client(verify=False) as client:

        if not args.no_probe:
            alive = _probe(args.url, client)
            if not alive:
                print(f"\n{RED}Aborting — endpoint not reachable.{RESET}")
                return 1
            print()

        ok = err = 0
        idx = 0

        try:
            while True:
                for _ in range(count):
                    idx += 1
                    det = _make_detection(
                        label=args.label or None,
                        stream_id=args.stream or None,
                        confidence=args.confidence,
                        octopus_base_url=oct_url,
                    )
                    success = _fire(args.url, args.api_key, det, client, idx)
                    if success:
                        ok += 1
                    else:
                        err += 1
                    if interval > 0:
                        time.sleep(interval)

                if not args.loop:
                    break

                print(
                    f"  {DIM}--- loop #{idx // count} done, sleeping {interval}s ---{RESET}"
                )
                time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Interrupted.{RESET}")

    print(
        f"\n{BOLD}Results:{RESET}  {GREEN}{ok} broadcast{RESET}  {RED}{err} failed{RESET}  "
        f"(total {ok + err})"
    )
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
