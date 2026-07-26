#!/usr/bin/env python3
"""Hard-delete rows soft-deleted more than N days ago (HADES-l3n).

The end of the 90-day recovery window. Only ever touches rows with a
non-NULL ``deleted_at`` — live data can never be caught by it.

Usage:
    python scripts/purge_soft_deleted.py            # 90-day window
    python scripts/purge_soft_deleted.py --days 30
    python scripts/purge_soft_deleted.py --dry-run
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

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("purge_soft_deleted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90,
                        help="Recovery window in days (default: 90)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be purged without deleting")
    args = parser.parse_args()

    from observability import init_sentry
    init_sentry(component="purge-soft-deleted")

    from _credentials import load_credentials
    from turso_db import TursoDatabase

    creds = load_credentials()
    db = TursoDatabase(url=creds["TURSO_DATABASE_URL"],
                       auth_token=creds["TURSO_AUTH_TOKEN"])
    db.init_schema()

    if args.dry_run:
        for table in ("operators", "staged_exports"):
            rows = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE deleted_at IS NOT NULL "
                "AND deleted_at < datetime('now', ?)",
                (f"-{args.days} days",),
            )
            logger.info("DRY RUN: would purge %d %s row(s)",
                        rows[0][0] if rows else 0, table)
        return 0

    result = db.purge_soft_deleted(days=args.days)
    logger.info("Purged past the %d-day window: %s", args.days, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
