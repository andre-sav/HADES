"""
Sync Operators from Zoho CRM to HADES database.
Adapts Zoho Accounts (Owner Operator type) to HADES operators table.
"""

import asyncio
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from zoho_auth import ZohoAuth
from zoho_client import ZohoClient

# Configure logging
logger = logging.getLogger(__name__)

# Set up console handler if not already configured
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Zoho fields to fetch
ZOHO_FIELDS = [
    "id",                   # Zoho ID for sync tracking
    "Account_Name",         # -> operator_name
    "Ref_Company_Name",     # -> vending_business_name
    "email",                # -> operator_email
    "Phone",                # -> operator_phone
    "City_State_Zip",       # For parsing zip code (fallback)
    "Shipping_Code",        # -> operator_zip (preferred)
    "Domain_URL",           # -> operator_website
    "Account_Type",         # Filter field
    "Modified_Time",        # For incremental sync
]

# Sync metadata key
SYNC_KEY = "zoho_operators_last_sync"


def parse_zip(city_state_zip: Optional[str]) -> Optional[str]:
    """Extract 5-digit zip from 'City, State, Zip' format."""
    if not city_state_zip:
        return None
    match = re.search(r'\b(\d{5})(?:-\d{4})?\s*$', city_state_zip)
    return match.group(1) if match else None


def map_zoho_to_hades(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map Zoho Account record to HADES operators schema.

    Zoho Fields -> HADES Columns:
        id              -> zoho_id
        Account_Name    -> operator_name
        Ref_Company_Name -> vending_business_name
        Phone           -> operator_phone
        email           -> operator_email
        Shipping_Code   -> operator_zip (or parsed from City_State_Zip)
        Domain_URL      -> operator_website
    """
    zip_code = record.get("Shipping_Code") or parse_zip(record.get("City_State_Zip"))

    return {
        "zoho_id": record.get("id"),
        "operator_name": record.get("Account_Name"),
        "vending_business_name": record.get("Ref_Company_Name"),
        "operator_phone": record.get("Phone"),
        "operator_email": record.get("email"),
        "operator_zip": zip_code,
        "operator_website": record.get("Domain_URL"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def ensure_sync_metadata_table(db) -> None:
    """Ensure sync_metadata table exists (handles schema migration edge case)."""
    db.connection.execute("""
        CREATE TABLE IF NOT EXISTS sync_metadata (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.connection.commit()


def get_last_sync_time(db) -> Optional[str]:
    """Get the last successful sync timestamp."""
    ensure_sync_metadata_table(db)
    rows = db.execute(
        "SELECT value FROM sync_metadata WHERE key = ?",
        (SYNC_KEY,)
    )
    if rows and rows[0][0]:
        return rows[0][0]
    return None


def set_last_sync_time(db, timestamp: str) -> None:
    """Set the last successful sync timestamp."""
    db.execute_write(
        """INSERT INTO sync_metadata (key, value, updated_at)
           VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP""",
        (SYNC_KEY, timestamp, timestamp)
    )


async def fetch_owner_operators(
    client: ZohoClient,
    modified_since: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch Owner Operator accounts from Zoho using COQL.

    Uses COQL instead of search endpoint to bypass 2000 record limit.
    COQL supports up to 100k records with offset-based pagination.

    Args:
        client: ZohoClient instance
        modified_since: ISO timestamp - only fetch records modified after this time

    Returns:
        List of Zoho account records
    """
    # Build field list for COQL SELECT
    fields_str = ", ".join(ZOHO_FIELDS)

    if modified_since:
        # Incremental sync - only modified records
        # COQL expects format: 'yyyy-MM-dd HH:mm:ss'
        # Validate and parse timestamp to prevent injection
        try:
            from datetime import datetime as dt
            # Parse to validate format, handle various ISO formats
            ts = modified_since.replace("Z", "+00:00")
            parsed = dt.fromisoformat(ts)
            zoho_timestamp = parsed.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid timestamp format: {modified_since} - {e}")
            raise ValueError(f"Invalid sync timestamp format: {modified_since}")
        query = f"select {fields_str} from Accounts where Account_Type = 'Owner Operator' and Modified_Time > '{zoho_timestamp}'"
        logger.info(f"Incremental sync (COQL): fetching records modified since {modified_since}")
    else:
        # Full sync
        query = f"select {fields_str} from Accounts where Account_Type = 'Owner Operator'"
        logger.info("Full sync (COQL): fetching all Owner Operator records")

    return await client.coql_query_all(query)


async def sync_operators(
    db,
    auth: ZohoAuth,
    force_full: bool = False,
    batch_size: int = 100,
) -> Dict[str, int]:
    """
    Sync Owner Operators from Zoho to HADES operators table.

    Uses incremental sync by default - only fetches records modified since
    the last successful sync. Use force_full=True to resync everything.

    Args:
        db: HADES TursoDatabase instance
        auth: ZohoAuth instance
        force_full: If True, ignore last sync time and fetch all records
        batch_size: Records per commit batch

    Returns:
        {"created": N, "updated": N, "linked": N, "skipped": N, "total_zoho": N, "sync_type": str}
    """
    # Determine sync type
    last_sync = None if force_full else get_last_sync_time(db)
    sync_type = "full" if last_sync is None else "incremental"
    sync_start_time = datetime.now(timezone.utc).isoformat()

    logger.info(f"Starting {sync_type} sync...")
    if last_sync:
        logger.info(f"  Last sync: {last_sync}")

    client = ZohoClient(auth)
    zoho_records = await fetch_owner_operators(client, modified_since=last_sync)

    if not zoho_records:
        if sync_type == "incremental":
            logger.info("No records modified since last sync")
            # Update sync time even if no changes (so next sync uses new baseline)
            set_last_sync_time(db, sync_start_time)
        else:
            logger.info("No Owner Operators found in Zoho")
        return {
            "created": 0, "updated": 0, "linked": 0, "skipped": 0,
            "total_zoho": 0, "sync_type": sync_type
        }

    logger.info(f"Found {len(zoho_records)} {'modified ' if sync_type == 'incremental' else ''}records in Zoho")

    # Get existing operators with zoho_id
    existing = db.execute(
        "SELECT id, zoho_id, operator_name FROM operators WHERE zoho_id IS NOT NULL"
    )
    existing_by_zoho_id = {row[1]: {"id": row[0], "name": row[2]} for row in existing}

    # Also check for name matches (for linking existing manual entries)
    existing_by_name = db.execute(
        "SELECT id, operator_name FROM operators WHERE zoho_id IS NULL"
    )
    unlinked_by_name = {row[1].lower(): row[0] for row in existing_by_name}

    created = updated = skipped = linked = 0
    logger.info(f"Processing {len(zoho_records)} Zoho records...")
    logger.info(f"  Existing synced operators: {len(existing_by_zoho_id)}")
    logger.info(f"  Unlinked manual operators: {len(unlinked_by_name)}")

    for i, record in enumerate(zoho_records):
        mapped = map_zoho_to_hades(record)
        zoho_id = mapped["zoho_id"]

        if not mapped["operator_name"]:
            logger.warning(f"  Skipping record with no Account_Name: {zoho_id}")
            skipped += 1
            continue

        if zoho_id in existing_by_zoho_id:
            # Update existing synced record
            db.execute_write("""
                UPDATE operators SET
                    operator_name = ?,
                    vending_business_name = ?,
                    operator_phone = ?,
                    operator_email = ?,
                    operator_zip = ?,
                    operator_website = ?,
                    synced_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE zoho_id = ?
            """, (
                mapped["operator_name"],
                mapped["vending_business_name"],
                mapped["operator_phone"],
                mapped["operator_email"],
                mapped["operator_zip"],
                mapped["operator_website"],
                mapped["synced_at"],
                zoho_id,
            ))
            updated += 1
            logger.debug(f"  Updated: {mapped['operator_name']}")

        elif mapped["operator_name"].lower() in unlinked_by_name:
            # Link existing manual entry to Zoho record
            existing_id = unlinked_by_name[mapped["operator_name"].lower()]
            db.execute_write("""
                UPDATE operators SET
                    zoho_id = ?,
                    vending_business_name = COALESCE(vending_business_name, ?),
                    operator_phone = COALESCE(operator_phone, ?),
                    operator_email = COALESCE(operator_email, ?),
                    operator_zip = COALESCE(operator_zip, ?),
                    operator_website = COALESCE(operator_website, ?),
                    synced_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                zoho_id,
                mapped["vending_business_name"],
                mapped["operator_phone"],
                mapped["operator_email"],
                mapped["operator_zip"],
                mapped["operator_website"],
                mapped["synced_at"],
                existing_id,
            ))
            linked += 1
            logger.info(f"  Linked existing: {mapped['operator_name']} -> {zoho_id}")
            # Remove from unlinked so we don't match again
            del unlinked_by_name[mapped["operator_name"].lower()]

        else:
            # Create new operator
            try:
                db.execute_write("""
                    INSERT INTO operators (
                        operator_name, vending_business_name, operator_phone,
                        operator_email, operator_zip, operator_website, zoho_id, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    mapped["operator_name"],
                    mapped["vending_business_name"],
                    mapped["operator_phone"],
                    mapped["operator_email"],
                    mapped["operator_zip"],
                    mapped["operator_website"],
                    zoho_id,
                    mapped["synced_at"],
                ))
                created += 1
                logger.info(f"  Created: {mapped['operator_name']}")
            except Exception as e:
                if "UNIQUE" in str(e) or "unique" in str(e).lower():
                    # Duplicate name or zoho_id - skip
                    skipped += 1
                    logger.warning(f"  Skipped duplicate: {mapped['operator_name']} ({e})")
                else:
                    raise  # Re-raise unexpected errors

        # Progress log every 50 records
        if (i + 1) % 50 == 0:
            logger.info(f"  Progress: {i + 1}/{len(zoho_records)} records processed")

    # Save sync time on success
    set_last_sync_time(db, sync_start_time)
    logger.info(f"  Updated last sync time to {sync_start_time}")

    result = {
        "created": created,
        "updated": updated,
        "linked": linked,
        "skipped": skipped,
        "total_zoho": len(zoho_records),
        "sync_type": sync_type,
    }
    logger.info(f"Zoho Sync complete ({sync_type}): created={created}, updated={updated}, linked={linked}, skipped={skipped}")
    return result


def run_sync(db, auth: ZohoAuth, force_full: bool = False) -> Dict[str, int]:
    """Synchronous wrapper for sync_operators."""
    return asyncio.run(sync_operators(db, auth, force_full=force_full))
