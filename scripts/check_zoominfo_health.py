#!/usr/bin/env python3
"""Scheduled ZoomInfo health check (HADES-1d3).

Makes the SYSTEM the detector instead of the operator. Fetches ZoomInfo usage,
evaluates it against warn/critical thresholds, and emails an alert when credits
or entitlements are running out — the condition that caused the 2026-06-15
blank-enrichment incident (search keeps working while enrichment silently
returns fieldless records once credits are exhausted).

Run from a scheduled GitHub Actions workflow:
    python scripts/check_zoominfo_health.py

Always exits 0 (the email IS the signal; a non-zero exit would chain a second
generic failure alert on top). Prints the verdict to stdout for the run log.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

# Allow both `python scripts/check_zoominfo_health.py` and in-dir execution.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from zoominfo_client import ZoomInfoClient  # noqa: E402
from monitoring import evaluate_usage  # noqa: E402
from notify_failure import send_alert  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("check_zoominfo_health")


def main() -> int:
    from _credentials import load_credentials

    try:
        creds = load_credentials()
        client = ZoomInfoClient(
            client_id=creds["ZOOMINFO_CLIENT_ID"],
            client_secret=creds["ZOOMINFO_CLIENT_SECRET"],
        )
        usage = client.get_usage()
    except Exception as exc:  # noqa: BLE001 — health check must never crash the cron
        logger.warning("Health check could not fetch usage: %r", exc, exc_info=True)
        # An unreadable usage signal is itself worth surfacing.
        usage = {"error": repr(exc)}

    verdict = evaluate_usage(usage)
    logger.info("ZoomInfo health: %s — %s", verdict["severity"].upper(), verdict["message"])

    if verdict["severity"] in ("warning", "critical", "unknown"):
        body_lines = [
            verdict["message"],
            "",
            "Why this matters: when ZoomInfo enrichment credits/entitlement run out, "
            "search keeps working but enrichment returns fieldless records — the "
            "operator then sees blank leads (see the 2026-06-15 incident).",
            "",
            "Breaching limits:",
        ]
        for b in verdict.get("breaches", []):
            body_lines.append(
                f"  - {b['label']}: {b['used']:,}/{b['limit']:,} ({b['pct']:.0f}%, {b['remaining']:,} left)"
            )
        if not verdict.get("breaches"):
            body_lines.append("  (none parseable — see message above)")
        send_alert(f"[HADES] ZoomInfo health {verdict['severity'].upper()}", "\n".join(body_lines))

    return 0


if __name__ == "__main__":
    sys.exit(main())
