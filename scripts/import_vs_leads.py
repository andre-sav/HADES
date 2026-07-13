"""
Import a VanillaSoft contact export CSV into the vanillasoft_leads table
so export dedup can see leads created outside HADES (HADES-dio).

Idempotent: keyed on VS ContactID (INSERT OR REPLACE) — re-running with
the same or a newer export updates rows in place.

Usage:
    python scripts/import_vs_leads.py <path-to-vs-export.csv> [--dry-run]
"""

import argparse
import sys
from pathlib import Path

# Add project root to path so we can import project modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vs_leads import parse_vs_export  # noqa: E402

CHUNK_SIZE = 500  # SQLite param limits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="VanillaSoft contact export CSV")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report stats without writing to the DB")
    args = parser.parse_args()

    path = Path(args.csv_path).expanduser()
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return 1

    print(f"Parsing {path} ...")
    result = parse_vs_export(str(path))
    print(f"  rows in file:        {result.total_rows:,}")
    print(f"  importable rows:     {len(result.rows):,}")
    print(f"  skipped (no company AND no phone): {result.skipped_unmatchable:,}")
    print(f"  HADES-pushed rows:   {result.hades_count:,}")
    print(f"  unparseable dates:   {result.bad_dates:,}")

    if result.total_rows == 0:
        print("ERROR: no rows parsed — wrong file or format changed. Nothing written.")
        return 1

    if args.dry_run:
        print("Dry run — nothing written.")
        return 0

    from scripts._credentials import load_credentials
    from turso_db import TursoDatabase

    creds = load_credentials()
    db = TursoDatabase(url=creds["TURSO_DATABASE_URL"],
                       auth_token=creds["TURSO_AUTH_TOKEN"])
    db.init_schema()

    rows = result.rows
    for i in range(0, len(rows), CHUNK_SIZE):
        db.upsert_vs_leads_batch(rows[i:i + CHUNK_SIZE])
        done = min(i + CHUNK_SIZE, len(rows))
        if done % 25000 < CHUNK_SIZE or done == len(rows):
            print(f"  upserted {done:,}/{len(rows):,}")

    stats = db.get_vs_leads_stats()
    print(f"Done. vanillasoft_leads now holds {stats['total']:,} rows "
          f"({stats['hades']:,} HADES-pushed), latest Added Date {stats['latest_added']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
