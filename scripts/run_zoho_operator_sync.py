#!/usr/bin/env python3
"""Sync Owner Operators from Zoho CRM to HADES Turso DB.

Headless entry for the scheduled GitHub Actions job. Reuses zoho_sync.run_sync().

Usage:
    python scripts/run_zoho_operator_sync.py            # Incremental
    python scripts/run_zoho_operator_sync.py --full     # Full resync
    python scripts/run_zoho_operator_sync.py --verbose  # Debug logging

Required env vars:
    TURSO_DATABASE_URL, TURSO_AUTH_TOKEN
    ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN

Exit codes:
    0 — success
    1 — sync error
    2 — missing credentials
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

logger = logging.getLogger("zoho_operator_sync")

REQUIRED_ENV = (
    "TURSO_DATABASE_URL",
    "TURSO_AUTH_TOKEN",
    "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
)


def main(force_full: bool) -> int:
    from observability import init_sentry
    init_sentry(component="zoho-sync")  # no-op without SENTRY_DSN

    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing required env vars: {', '.join(missing)}")
        return 2

    from turso_db import TursoDatabase
    from zoho_auth import ZohoAuth
    from zoho_sync import run_sync

    db = TursoDatabase(
        url=os.environ["TURSO_DATABASE_URL"],
        auth_token=os.environ["TURSO_AUTH_TOKEN"],
    )
    db.init_schema()

    auth = ZohoAuth.from_env()

    try:
        result = run_sync(db, auth, force_full=force_full)
    except Exception:
        logger.exception("Zoho operator sync failed")
        return 1

    logger.info(
        f"Sync complete ({result.get('sync_type', 'unknown')}): "
        f"created={result.get('created', 0)}, "
        f"updated={result.get('updated', 0)}, "
        f"linked={result.get('linked', 0)}, "
        f"skipped={result.get('skipped', 0)}, "
        f"total_zoho={result.get('total_zoho', 0)}"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--full", action="store_true", help="Force full resync")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sys.exit(main(force_full=args.full))
