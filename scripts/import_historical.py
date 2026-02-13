"""
Import historical outcome data from CSV files into Turso historical_outcomes table.

Data sources:
  - data/enriched_locatings.csv (HLM locating data)
  - data/enriched_nonhlm_deliveries.csv (non-HLM delivery data)

Idempotent: skips import if historical_outcomes already has data.

Usage:
    python scripts/import_historical.py
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path so we can import project modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from calibrate_scoring import extract_sic, parse_employees, load_overrides

LOCATINGS_PATH = PROJECT_ROOT / "data" / "enriched_locatings.csv"
NONHLM_PATH = PROJECT_ROOT / "data" / "enriched_nonhlm_deliveries.csv"

# US state name → abbreviation for normalizing nonhlm data
STATE_ABBREV = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}

# Reverse mapping for validation
VALID_ABBREVS = set(STATE_ABBREV.values())


def normalize_state(raw: str | None) -> str | None:
    """Normalize state to 2-letter abbreviation."""
    if not raw or not raw.strip():
        return None
    val = raw.strip()
    # Already a 2-letter abbreviation
    if len(val) == 2:
        return val.upper()
    # Full state name
    abbrev = STATE_ABBREV.get(val.lower())
    return abbrev


def normalize_zip(raw: str | None) -> str | None:
    """Normalize ZIP to 5-digit string."""
    if not raw or not raw.strip():
        return None
    val = raw.strip()
    # Handle 9-digit ZIPs (e.g., "75201-1234")
    if "-" in val:
        val = val.split("-")[0]
    # Pad 4-digit ZIPs (e.g., leading zero dropped)
    if len(val) == 4 and val.isdigit():
        val = "0" + val
    if len(val) == 5 and val.isdigit():
        return val
    return None


def import_locatings(imported_at: str) -> list[tuple]:
    """Import HLM locating data. Returns list of param tuples."""
    overrides = load_overrides()
    rows_out = []

    with open(LOCATINGS_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            stage = (row.get("stage") or "").strip()
            if not stage:
                continue

            company_name = (row.get("company_name") or "").strip()
            if not company_name:
                continue

            # SIC: parse from vs_sic, fallback to manual overrides
            sic = extract_sic(row.get("vs_sic", ""))
            if not sic:
                sic = extract_sic(overrides.get(company_name, ""))

            # Employee count from vs_employees
            emp = parse_employees(row.get("vs_employees", ""))
            emp_int = int(emp) if emp is not None else None

            outcome = "delivery" if stage == "Green/ Delivered" else "no_delivery"

            rows_out.append((
                company_name,
                sic,
                emp_int,
                normalize_zip(row.get("zip_code")),
                normalize_state(row.get("state")),
                outcome,
                "enriched_locatings.csv",
                row.get("created_date") or None,
                imported_at,
            ))

    return rows_out


def import_nonhlm(imported_at: str) -> list[tuple]:
    """Import non-HLM delivery data. Returns list of param tuples."""
    rows_out = []

    with open(NONHLM_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            category = (row.get("category") or "").strip()
            if not category:
                continue

            company_name = (row.get("location_name") or "").strip()
            if not company_name:
                continue

            sic = extract_sic(row.get("sic_code", ""))
            outcome = "delivery" if "Delivered" in category else "no_delivery"

            rows_out.append((
                company_name,
                sic,
                None,  # employee_count not available
                normalize_zip(row.get("zip_code")),
                normalize_state(row.get("state")),
                outcome,
                "enriched_nonhlm_deliveries.csv",
                row.get("created_time") or None,
                imported_at,
            ))

    return rows_out


def main():
    # Import here to avoid Streamlit auto-launch
    import os
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

    # Connect to Turso directly (not through Streamlit cache)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Try to load secrets from .streamlit/secrets.toml
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    db_url = os.environ.get("TURSO_DATABASE_URL")
    db_token = os.environ.get("TURSO_AUTH_TOKEN")

    if not db_url and secrets_path.exists():
        import tomllib
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
        db_url = secrets.get("TURSO_DATABASE_URL")
        db_token = secrets.get("TURSO_AUTH_TOKEN")

    if not db_url or not db_token:
        print("ERROR: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN required.")
        print("Set via environment or .streamlit/secrets.toml")
        sys.exit(1)

    import libsql_experimental as libsql
    from turso_db import TursoDatabase

    db = TursoDatabase(url=db_url, auth_token=db_token)
    db.init_schema()

    # Idempotent check
    existing = db.get_historical_count()
    if existing > 0:
        print(f"historical_outcomes already has {existing} rows. Skipping import.")
        print("To re-import, manually DELETE FROM historical_outcomes first.")
        return

    imported_at = datetime.now().isoformat()

    # Import locatings
    print(f"Reading {LOCATINGS_PATH.name}...")
    locating_rows = import_locatings(imported_at)
    locating_deliveries = sum(1 for r in locating_rows if r[5] == "delivery")
    print(f"  {len(locating_rows)} rows ({locating_deliveries} deliveries)")

    # Import non-HLM
    print(f"Reading {NONHLM_PATH.name}...")
    nonhlm_rows = import_nonhlm(imported_at)
    nonhlm_deliveries = sum(1 for r in nonhlm_rows if r[5] == "delivery")
    print(f"  {len(nonhlm_rows)} rows ({nonhlm_deliveries} deliveries)")

    # Batch insert in chunks (SQLite has param limits)
    all_rows = locating_rows + nonhlm_rows
    print(f"\nInserting {len(all_rows)} total rows...")

    chunk_size = 500
    for i in range(0, len(all_rows), chunk_size):
        chunk = all_rows[i:i + chunk_size]
        db.insert_historical_outcomes_batch(chunk)
        print(f"  Inserted {min(i + chunk_size, len(all_rows))}/{len(all_rows)}")

    # Verify
    final_count = db.get_historical_count()
    print(f"\nDone. historical_outcomes now has {final_count} rows.")

    # Summary
    total_deliveries = locating_deliveries + nonhlm_deliveries
    print(f"  Deliveries: {total_deliveries}")
    print(f"  Non-deliveries: {final_count - total_deliveries}")
    print(f"  Overall delivery rate: {total_deliveries / final_count * 100:.1f}%")


if __name__ == "__main__":
    main()
