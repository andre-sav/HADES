"""
CSV export functionality for VanillaSoft format with operator metadata.
"""

import csv
import io
from datetime import datetime

from utils import VANILLASOFT_COLUMNS, ZOOMINFO_TO_VANILLASOFT, format_phone


def build_vanillasoft_row(
    lead: dict,
    operator: dict | None = None,
    data_source: str = "ZoomInfo",
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

    # Format phone number
    if row.get("Business"):
        row["Business"] = format_phone(row["Business"])

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

    row["Import Notes"] = " | ".join(notes_parts)

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
) -> tuple[str, str]:
    """
    Export leads to VanillaSoft CSV format.

    Args:
        leads: List of lead dicts (with _score, _lead_source, etc.)
        operator: Optional operator dict for metadata
        workflow_type: 'intent' or 'geography' for filename
        data_source: Data source name for List Source attribution

    Returns:
        Tuple of (csv_content, filename)
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=VANILLASOFT_COLUMNS)
    writer.writeheader()

    for lead in leads:
        row = build_vanillasoft_row(lead, operator, data_source)
        writer.writerow(row)

    csv_content = output.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{workflow_type}_leads_{timestamp}.csv"

    return csv_content, filename


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
