"""Backfill staged exports with missing fields by re-enriching contacts.

Re-enriches contacts from staged exports using the current
DEFAULT_ENRICH_OUTPUT_FIELDS (which now includes SIC, industry,
employee count, and address fields). Uses merge_contact to preserve
all existing data while filling in gaps.

Usage:
    python scripts/backfill_exports.py              # list staged exports
    python scripts/backfill_exports.py --id 1 --id 2  # backfill specific staged exports
    python scripts/backfill_exports.py --all          # backfill all staged exports
"""

import argparse
import json
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Backfill staged exports with re-enrichment")
    parser.add_argument("--id", type=int, action="append", help="Staged export ID(s) to backfill")
    parser.add_argument("--all", action="store_true", help="Backfill all staged exports")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making API calls")
    args = parser.parse_args()

    from turso_db import get_database
    db = get_database()

    # List all staged exports
    exports = db.get_staged_exports(limit=50)
    if not exports:
        print("No staged exports found.")
        return

    if not args.id and not args.all:
        # Just list exports
        print(f"\n{'ID':>4}  {'Time':<20} {'Type':<12} {'Leads':>5}  {'Status':<10}  Missing Fields")
        print("-" * 90)
        for exp in exports:
            # Fetch full export to inspect leads
            full = db.get_staged_export(exp["id"])
            leads = full["leads"] if full else []
            # Check which key fields are missing
            missing = []
            sample = leads[0] if leads else {}
            for field in ("sicCode", "industry", "employeeCount", "street", "companyStreet"):
                if not sample.get(field):
                    missing.append(field)
            status = "Exported" if exp.get("batch_id") else "Staged"
            missing_str = ", ".join(missing) if missing else "none"
            print(f"{exp['id']:>4}  {exp.get('created_at', ''):<20} {exp['workflow_type']:<12} {exp['lead_count']:>5}  {status:<10}  {missing_str}")
        print(f"\nTo backfill: python scripts/backfill_exports.py --id <ID> [--id <ID2>]")
        print(f"To backfill all: python scripts/backfill_exports.py --all")
        return

    # Determine which exports to process
    target_ids = args.id if args.id else [exp["id"] for exp in exports]

    from zoominfo_client import get_zoominfo_client, DEFAULT_ENRICH_OUTPUT_FIELDS
    from export import merge_contact

    if not args.dry_run:
        client = get_zoominfo_client()

    total_backfilled = 0

    for export_id in target_ids:
        export_row = db.get_staged_export(export_id)
        if not export_row:
            logger.warning("Staged export %d not found, skipping", export_id)
            continue

        leads = export_row["leads"]
        logger.info(
            "Processing staged export %d: %s workflow, %d leads",
            export_id, export_row["workflow_type"], len(leads),
        )

        # Extract personIds
        person_ids = []
        leads_by_pid = {}
        for lead in leads:
            pid = str(lead.get("personId") or lead.get("id") or "")
            if pid:
                person_ids.append(pid)
                leads_by_pid[pid] = lead

        if not person_ids:
            logger.warning("No person IDs found in staged export %d, skipping", export_id)
            continue

        logger.info("Found %d person IDs to re-enrich", len(person_ids))

        if args.dry_run:
            # Check what fields are missing
            sample = leads[0]
            missing = [f for f in ("sicCode", "industry", "employeeCount", "street", "companyStreet")
                       if not sample.get(f)]
            logger.info("DRY RUN: Would re-enrich %d contacts. Missing fields in sample: %s",
                        len(person_ids), missing or "none")
            continue

        # Re-enrich
        try:
            enriched = client.enrich_contacts_batch(
                person_ids=person_ids,
                output_fields=DEFAULT_ENRICH_OUTPUT_FIELDS,
            )
            logger.info("Re-enriched %d contacts", len(enriched))
        except Exception as e:
            logger.error("Re-enrichment failed for export %d: %s", export_id, e)
            continue

        # Merge: original lead data (with scores, metadata) + fresh enrich data
        merged_leads = []
        for enriched_contact in enriched:
            pid = str(enriched_contact.get("id") or enriched_contact.get("personId") or "")
            original = leads_by_pid.get(pid, {})
            merged = merge_contact(original, enriched_contact)
            merged_leads.append(merged)

        # Include any leads that weren't in the enriched response (no personId match)
        enriched_pids = {str(c.get("id") or c.get("personId") or "") for c in enriched}
        for lead in leads:
            pid = str(lead.get("personId") or lead.get("id") or "")
            if pid and pid not in enriched_pids:
                merged_leads.append(lead)
                logger.warning("Lead %s not in enrich response, keeping original", pid)

        # Verify fields were actually filled
        filled_count = sum(1 for l in merged_leads if l.get("sicCode") or l.get("companyStreet"))
        logger.info("After merge: %d/%d leads have SIC or address data", filled_count, len(merged_leads))

        # Update the staged export in the database
        db.execute_write(
            "UPDATE staged_exports SET leads_json = ?, lead_count = ? WHERE id = ?",
            (json.dumps(merged_leads), len(merged_leads), export_id),
        )
        logger.info("Updated staged export %d with %d backfilled leads", export_id, len(merged_leads))
        total_backfilled += len(merged_leads)

    if not args.dry_run:
        logger.info("Backfill complete: %d total leads updated", total_backfilled)


if __name__ == "__main__":
    main()
