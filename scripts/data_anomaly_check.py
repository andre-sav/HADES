#!/usr/bin/env python3
"""Daily data-health check (HADES-e7j).

Early warning for the slow-drift failure modes nothing else catches:

  - operators table shrinking (accidental or buggy mass delete)
  - Zoho linkage percentage regressing (sync degrading silently)
  - export volume collapsing (filter change or upstream breakage)
  - a burst of deletes in the mutation log (mass-delete signature)

Detection logic lives in monitoring.py (pure + unit-tested); this script
only supplies the DB reads, stores the day's baselines, and alerts.

Exit codes mirror check_zoominfo_health.py (HADES-2oe): 0 when healthy or
when the alert was DELIVERED (the email is the signal); 1 when an anomaly
was found but the alert could not be delivered — the red run then becomes
the fallback channel.

Usage:
    python scripts/data_anomaly_check.py
    python scripts/data_anomaly_check.py --dry-run   # report, don't alert or save baselines
"""

import argparse
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from monitoring import (  # noqa: E402
    evaluate_row_count_drop,
    evaluate_linkage_drop,
    evaluate_export_volume,
    evaluate_mutation_burst,
    summarise_verdicts,
)
from utils import utc_now_str  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("data_anomaly_check")

# Liveness stamp. GitHub disables scheduled workflows after 60 days of repo
# inactivity and every cron stops at once with no alert, because the alert
# channel IS a failing run. Stamping each completion lets the Pipeline Health
# page detect the schedule dying by absence (HADES-7qi).
LAST_RUN_KEY = "anomaly_last_run_utc"
BASELINE_OPERATORS = "anomaly_baseline_operators"
BASELINE_ZOHO_LINKED = "anomaly_baseline_zoho_linked"


def _float_or_none(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def collect_verdicts(db) -> tuple[list[dict], dict]:
    """Run every check. Returns (verdicts, baselines_to_store).

    Each check is independently guarded: one failing query must not
    suppress the others (a partial signal beats none).
    """
    verdicts: list[dict] = []
    new_baselines: dict[str, str] = {}

    # 1. operators row count vs yesterday
    try:
        live = db.execute("SELECT COUNT(*) FROM operators WHERE deleted_at IS NULL")[0][0]
        baseline = _float_or_none(db.get_sync_value(BASELINE_OPERATORS))
        verdicts.append(evaluate_row_count_drop(
            "operators", live, int(baseline) if baseline is not None else None))
        new_baselines[BASELINE_OPERATORS] = str(live)
    except Exception as exc:
        logger.warning("operators count check failed: %r", exc, exc_info=True)
        verdicts.append({"severity": "unknown",
                         "message": f"operators count check failed: {exc!r}"})

    # 2. Zoho linkage percentage
    try:
        rows = db.execute(
            "SELECT COUNT(*), SUM(CASE WHEN zoho_id IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM operators WHERE deleted_at IS NULL"
        )
        total, linked = (rows[0][0] or 0), (rows[0][1] or 0)
        if total:
            fraction = linked / total
            baseline = _float_or_none(db.get_sync_value(BASELINE_ZOHO_LINKED))
            verdicts.append(evaluate_linkage_drop(fraction, baseline))
            new_baselines[BASELINE_ZOHO_LINKED] = f"{fraction:.4f}"
    except Exception as exc:
        logger.warning("zoho linkage check failed: %r", exc, exc_info=True)
        verdicts.append({"severity": "unknown",
                         "message": f"zoho linkage check failed: {exc!r}"})

    # 3. export volume vs the 30-day distribution
    try:
        rows = db.execute(
            "SELECT DATE(exported_at) AS d, COUNT(*) FROM lead_outcomes "
            "WHERE exported_at >= date('now', '-31 days') "
            "GROUP BY d ORDER BY d"
        )
        by_day = {r[0]: r[1] for r in rows}
        # Measure the last COMPLETED day, not the in-progress one (N2-04).
        # This runs at 07:00 UTC — before any US-hours export lands — so
        # comparing "today" against a mean of complete days scored 0 vs a
        # healthy mean and fired critical every single morning.
        today, yesterday = db.execute(
            "SELECT date('now'), date('now', '-1 day')"
        )[0]
        by_day.pop(today, None)                 # in-progress: not comparable
        measured = by_day.pop(yesterday, 0)
        verdicts.append(evaluate_export_volume(measured, list(by_day.values())))
    except Exception as exc:
        logger.warning("export volume check failed: %r", exc, exc_info=True)
        verdicts.append({"severity": "unknown",
                         "message": f"export volume check failed: {exc!r}"})

    # 4. mass-delete signature in the mutation log
    try:
        # Scope to deletes (N2 tail): the newest-N-of-any-op window let
        # ordinary inserts push a real delete burst out of view.
        verdicts.append(evaluate_mutation_burst(
            db.get_recent_mutations(limit=500, op="delete")))
    except Exception as exc:
        logger.warning("mutation burst check failed: %r", exc, exc_info=True)
        verdicts.append({"severity": "unknown",
                         "message": f"mutation burst check failed: {exc!r}"})

    return verdicts, new_baselines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report findings without alerting or storing baselines")
    args = parser.parse_args()

    from observability import init_sentry
    init_sentry(component="data-anomaly-check")

    from _credentials import load_credentials
    from notify_failure import send_alert
    from turso_db import TursoDatabase

    creds = load_credentials()
    db = TursoDatabase(url=creds["TURSO_DATABASE_URL"],
                       auth_token=creds["TURSO_AUTH_TOKEN"])
    db.init_schema()

    verdicts, new_baselines = collect_verdicts(db)
    summary = summarise_verdicts(verdicts)

    for v in verdicts:
        logger.info("[%s] %s", v["severity"].upper(), v["message"])
    logger.info("Overall: %s", summary["severity"].upper())

    if args.dry_run:
        logger.info("Dry run — no alert sent, baselines not updated.")
        return 0

    # Baselines advance even when an anomaly fired: otherwise a one-off drop
    # would re-alert every day against a stale high-water mark.
    new_baselines[LAST_RUN_KEY] = utc_now_str()
    for key, value in new_baselines.items():
        try:
            db.set_sync_value(key, value)
        except Exception:
            logger.warning("Could not store baseline %s", key, exc_info=True)

    if summary["severity"] == "ok":
        return 0

    sent = send_alert(
        f"[HADES] Data health {summary['severity'].upper()}",
        summary["message"] + "\n\nChecks run: operators row count, Zoho linkage, "
        "export volume, mutation-log delete bursts.",
    )
    if not sent:
        logger.error("Anomaly detected but the alert could not be delivered — "
                     "failing the run so the condition is visible.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
