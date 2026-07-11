"""
Cross-session export deduplication.

Filters search results against previously exported companies (from lead_outcomes table).
Separate from dedup.py which handles in-memory, within-session dedup.
"""

import logging

from dedup import normalize_company_name

logger = logging.getLogger(__name__)


def get_previously_exported(db, days_back: int = 365,
                            exclude_batch_id: str | None = None) -> dict:
    """Query DB for previously exported companies.

    Returns:
        {
            "by_id": {company_id: {company_name, exported_at, workflow_type}},
            "by_name": {normalized_name: {company_name, exported_at, workflow_type}},
        }
    """
    exported = db.get_exported_company_ids(days_back=days_back,
                                           exclude_batch_id=exclude_batch_id)

    by_id = exported  # Already keyed by company_id
    by_name = {}
    for cid, meta in exported.items():
        name = meta.get("company_name", "")
        if name:
            normalized = normalize_company_name(name)
            if normalized and normalized not in by_name:
                by_name[normalized] = meta

    return {"by_id": by_id, "by_name": by_name}


def filter_previously_exported(
    contacts: list[dict],
    lookup: dict,
) -> tuple[list[dict], list[dict]]:
    """Partition contacts into (new, filtered).

    Matching priority:
    1. company_id exact match
    2. Normalized company name fallback (when no company_id)

    Filtered contacts get tagged with _previously_exported metadata.
    """
    by_id = lookup.get("by_id", {})
    by_name = lookup.get("by_name", {})

    new = []
    filtered = []

    for contact in contacts:
        # _numeric_company_id (stamped by the intent pipeline from the
        # hashed→numeric mapping cache) takes precedence: lead_outcomes stores
        # numeric IDs, so a hashed companyId can never match by_id (HADES-oq9).
        raw_cid = contact.get("_numeric_company_id") or contact.get("companyId")
        cid = str(raw_cid) if raw_cid else ""
        company_name = contact.get("companyName", "") or ""

        match = None

        # Try company_id match first
        if cid and cid in by_id:
            match = by_id[cid]
        # Name fallback ONLY when the contact has no usable companyId: a
        # present-but-unknown NUMERIC ID is proof the company was never
        # exported (matching by name there silently dropped same-name
        # franchises — Planet Fitness Dallas vs Fort Worth, HADES-u1x).
        # An untranslated HASHED intent id (non-numeric) lives in a different
        # id-space than lead_outcomes, proves nothing, and still needs the
        # name fallback.
        elif company_name and (not cid or not cid.isdigit()):
            normalized = normalize_company_name(company_name)
            if normalized and normalized in by_name:
                match = by_name[normalized]

        if match:
            contact["_previously_exported"] = True
            contact["_last_exported_at"] = match.get("exported_at", "")
            filtered.append(contact)
        else:
            new.append(contact)

    return new, filtered


def apply_export_dedup(
    contacts: list[dict],
    db,
    days_back: int = 365,
    include_exported: bool = False,
    exclude_batch_id: str | None = None,
) -> dict:
    """Convenience wrapper for workflow pages.

    Returns:
        {
            "contacts": list — filtered (or all if include_exported),
            "filtered_count": int,
            "filtered_contacts": list,
            "total_before_filter": int,
            "days_back": int,
        }
    """
    total_before = len(contacts)
    lookup = get_previously_exported(db, days_back=days_back,
                                     exclude_batch_id=exclude_batch_id)

    new_contacts, filtered_contacts = filter_previously_exported(contacts, lookup)

    if include_exported:
        # Return all contacts, but filtered ones keep their _previously_exported tag
        result_contacts = new_contacts + filtered_contacts
    else:
        result_contacts = new_contacts

    return {
        "contacts": result_contacts,
        "filtered_count": len(filtered_contacts),
        "filtered_contacts": filtered_contacts,
        "total_before_filter": total_before,
        "days_back": days_back,
    }
