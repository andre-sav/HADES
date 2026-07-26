#!/usr/bin/env python3
"""Scheduled ZoomInfo health check (HADES-1d3).

Makes the SYSTEM the detector instead of the operator. Fetches ZoomInfo usage,
evaluates it against warn/critical thresholds, and emails an alert when credits
or entitlements are running out — the condition that caused the 2026-06-15
blank-enrichment incident (search keeps working while enrichment silently
returns fieldless records once credits are exhausted).

Run from a scheduled GitHub Actions workflow:
    python scripts/check_zoominfo_health.py

Exit code: 0 when healthy, or when an alert email was actually delivered (the
email is the signal). Exits 1 when the verdict is critical/unknown AND the
alert channel could not deliver — otherwise a critical verdict with SMTP
unconfigured vanishes into a green run and nobody is ever told (HADES-2oe).
The red run makes GitHub's own workflow-failure notification the fallback
channel. Prints the verdict to stdout for the run log.
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
    from observability import init_sentry
    init_sentry(component="health-check")  # no-op without SENTRY_DSN

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
        sent = send_alert(f"[HADES] ZoomInfo health {verdict['severity'].upper()}", "\n".join(body_lines))
        if not sent:
            # No human-visible signal exists: fail the run so GitHub's own
            # failure notification becomes the fallback channel (HADES-2oe).
            # Warnings included (review N-12): the 80-94% window is this
            # script's entire purpose — an SMTP outage there produced green
            # runs until usage crossed critical.
            logger.error("Alert email undeliverable for %s verdict — failing the "
                         "run so the condition is visible.", verdict["severity"])
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
