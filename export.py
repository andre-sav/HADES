"""
CSV export functionality for VanillaSoft format with operator metadata.
"""

import csv
import io
from datetime import datetime

from utils import VANILLASOFT_COLUMNS, ZOOMINFO_TO_VANILLASOFT, format_phone


def generate_batch_id(db) -> str:
    """Generate a sequential batch ID for this export: HADES-YYYYMMDD-NNN.

    Uses sync_metadata table to track today's sequence number.
    """
    today = datetime.now().strftime("%Y%m%d")
    seq_key = f"hades_batch_seq_{today}"

    rows = db.execute(
        "SELECT value FROM sync_metadata WHERE key = ?", (seq_key,)
    )
    seq = int(rows[0][0]) + 1 if rows else 1

    db.execute_write(
        """INSERT INTO sync_metadata (key, value, updated_at)
           VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP""",
        (seq_key, str(seq), str(seq)),
    )

    return f"HADES-{today}-{seq:03d}"


def build_vanillasoft_row(
    lead: dict,
    operator: dict | None = None,
    data_source: str = "ZoomInfo",
    batch_id: str | None = None,
) -> dict:
    """
    Build a single VanillaSoft CSV row from a lead and optional operator.

    Args:
        lead: Lead data from ZoomInfo (with _score, _lead_source, etc.)
        operator: Optional operator dict with business metadata
        data_source: Data source name for List Source attribution (default: "ZoomInfo")

    Returns:
        Dict with VanillaSoft column names as keys
    """
    row = {col: "" for col in VANILLASOFT_COLUMNS}

    # Map ZoomInfo fields to VanillaSoft columns
    for zi_field, vs_col in ZOOMINFO_TO_VANILLASOFT.items():
        value = lead.get(zi_field, "")
        if value is not None:
            row[vs_col] = str(value)

    # Format phone numbers
    if row.get("Business"):
        row["Business"] = format_phone(row["Business"])
    if row.get("Mobile"):
        row["Mobile"] = format_phone(row["Mobile"])

    # List Source attribution: "{DataSource} {Date}" per VSDP format
    today = datetime.now().strftime("%b %d %Y")  # e.g., "Jan 29 2026"
    row["List Source"] = f"{data_source} {today}"

    # Lead Source can hold workflow-specific tag (optional)
    row["Lead Source"] = ""

    # Add priority as call priority
    row["Call Priority"] = lead.get("_priority", "")

    # Build import notes with score info
    notes_parts = []
    if lead.get("_score"):
        notes_parts.append(f"Score: {lead['_score']}")
    if lead.get("_age_days") is not None:
        notes_parts.append(f"Age: {lead['_age_days']}d")
    if lead.get("_freshness_label"):
        notes_parts.append(f"Freshness: {lead['_freshness_label']}")
    if lead.get("_distance_miles"):
        notes_parts.append(f"Distance: {lead['_distance_miles']}mi")
    if lead.get("intentStrength"):
        notes_parts.append(f"Signal: {lead['intentStrength']}")

    notes = " | ".join(notes_parts)
    if batch_id:
        notes = f"Batch: {batch_id} | {notes}" if notes else f"Batch: {batch_id}"
    row["Import Notes"] = notes

    # Add operator metadata if provided
    if operator:
        row["Operator Name"] = operator.get("operator_name") or ""
        row["Vending Business Name"] = operator.get("vending_business_name") or ""
        row["Operator Phone #"] = format_phone(operator.get("operator_phone") or "")
        row["Operator Email Address"] = operator.get("operator_email") or ""
        row["Operator Zip Code"] = operator.get("operator_zip") or ""
        row["Operator Website Address"] = operator.get("operator_website") or ""
        row["Team"] = operator.get("team") or ""
        row["Contact Owner"] = operator.get("operator_name") or ""

    return row


def export_leads_to_csv(
    leads: list[dict],
    operator: dict | None = None,
    workflow_type: str = "export",
    data_source: str = "ZoomInfo",
    db=None,
) -> tuple[str, str, str | None]:
    """
    Export leads to VanillaSoft CSV format.

    Args:
        leads: List of lead dicts (with _score, _lead_source, etc.)
        operator: Optional operator dict for metadata
        workflow_type: 'intent' or 'geography' for filename
        data_source: Data source name for List Source attribution
        db: Optional TursoDatabase for batch ID generation

    Returns:
        Tuple of (csv_content, filename, batch_id). batch_id is None if db not provided.
    """
    batch_id = generate_batch_id(db) if db else None

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=VANILLASOFT_COLUMNS)
    writer.writeheader()

    for lead in leads:
        row = build_vanillasoft_row(lead, operator, data_source, batch_id=batch_id)
        writer.writerow(row)

    csv_content = output.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{workflow_type}_leads_{timestamp}.csv"

    return csv_content, filename, batch_id


def get_export_summary(leads: list[dict]) -> dict:
    """
    Generate summary statistics for export preview.

    Args:
        leads: List of leads to summarize

    Returns:
        Dict with summary stats
    """
    if not leads:
        return {
            "total": 0,
            "by_priority": {},
            "by_state": {},
        }

    by_priority = {}
    by_state = {}

    for lead in leads:
        # Count by priority
        priority = lead.get("_priority", "Unknown")
        by_priority[priority] = by_priority.get(priority, 0) + 1

        # Count by state
        state = lead.get("state", "Unknown")
        by_state[state] = by_state.get(state, 0) + 1

    return {
        "total": len(leads),
        "by_priority": by_priority,
        "by_state": dict(sorted(by_state.items(), key=lambda x: -x[1])[:5]),
    }
