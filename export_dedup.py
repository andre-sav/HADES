"""
Cross-session export deduplication.

Filters search results against previously exported companies (from the
lead_outcomes table) AND against VanillaSoft lead history imported into
the vanillasoft_leads table (HADES-dio: leads created by other reps or
pre-HADES channels have no ZoomInfo companyId and were invisible here).
Separate from dedup.py which handles in-memory, within-session dedup.
"""

import logging

from dedup import normalize_company_name
from utils import normalize_zip
from vs_leads import normalize_phone

logger = logging.getLogger(__name__)

# Person-level phones are unique to a contact — a match is proof on its own.
# COMPANY-level numbers are the chain-wide switchboard shared by every
# location of a franchise, so they only count when the ZIP corroborates the
# same physical location (HADES-u1x class).
#
# `phone` is COMPANY-level despite the bare name: utils.ZOOMINFO_TO_VANILLASOFT
# documents it as the fallback for the VanillaSoft "Business" column, i.e. the
# company line, not a personal one (review N2-07).
_PERSON_PHONE_FIELDS = ("directPhone", "mobilePhone")
_COMPANY_PHONE_FIELDS = ("phone", "companyPhone", "companyHQPhone")

# Same split on the VanillaSoft side: the "Business" column is the company
# line; Mobile/Home are person-level.
_VS_PERSON_PHONE_KEYS = ("phone_mobile", "phone_home")
_VS_COMPANY_PHONE_KEYS = ("phone_business",)


def get_previously_exported(db, days_back: int = 365,
                            exclude_batch_id: str | None = None) -> dict:
    """Query DB for previously exported companies.

    Returns:
        {
            "by_id": {company_id: {company_name, exported_at, workflow_type}},
            "by_name": {normalized_name: {company_name, exported_at, workflow_type}},
            "vs_by_name": {normalized_name: [vs_entry, ...]},
            "vs_by_phone": {ten_digit_phone: vs_entry},
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

    # Third source: VanillaSoft lead history (no companyId universe — the
    # index cutoff enforces the 1-year re-contact rule).
    vs_by_name: dict[str, list] = {}
    vs_by_phone: dict[str, dict] = {}          # person-level: standalone proof
    vs_by_company_phone: dict[str, dict] = {}  # company-level: needs ZIP
    for entry in db.get_vs_dedup_index(days_back=days_back):
        if entry.get("company_norm"):
            vs_by_name.setdefault(entry["company_norm"], []).append(entry)
        # Two indexes, because a match on the VS "Business" column is only
        # company-level evidence and needs ZIP corroboration (N2-07).
        for key in _VS_PERSON_PHONE_KEYS:
            ph = entry.get(key)
            if ph and ph not in vs_by_phone:
                vs_by_phone[ph] = entry
        for key in _VS_COMPANY_PHONE_KEYS:
            ph = entry.get(key)
            if ph and ph not in vs_by_company_phone:
                vs_by_company_phone[ph] = entry

    return {"by_id": by_id, "by_name": by_name,
            "vs_by_name": vs_by_name, "vs_by_phone": vs_by_phone,
            "vs_by_company_phone": vs_by_company_phone}


def _match_vs_lead(contact: dict, vs_by_name: dict, vs_by_phone: dict,
                   vs_by_company_phone: dict | None = None) -> dict | None:
    """Match a contact against VanillaSoft history.

    VS rows have no ZoomInfo companyId, so a name match alone would
    re-introduce the franchise false-drop (HADES-u1x). Rules:
    1. A PERSON-level phone on BOTH sides — proof on its own.
    2. A company-level phone on EITHER side, or a normalized name match,
       corroborated by an exact ZIP match.
    No contact ZIP -> no company-phone/name matching -> keep the contact.
    """
    vs_by_company_phone = vs_by_company_phone or {}
    czip = normalize_zip(contact.get("zip") or contact.get("zipCode")
                         or contact.get("companyZipCode") or "")

    # 1. person-level on both sides
    if vs_by_phone:
        for f in _PERSON_PHONE_FIELDS:
            ph = normalize_phone(contact.get(f))
            if ph and ph in vs_by_phone:
                return vs_by_phone[ph]

    # 2. company-level on EITHER side — always needs ZIP corroboration
    if czip:
        for f in _PERSON_PHONE_FIELDS + _COMPANY_PHONE_FIELDS:
            ph = normalize_phone(contact.get(f))
            if not ph:
                continue
            entry = vs_by_company_phone.get(ph)
            if entry and entry.get("zip") == czip:
                return entry
        for f in _COMPANY_PHONE_FIELDS:
            ph = normalize_phone(contact.get(f))
            entry = vs_by_phone.get(ph) if ph else None
            if entry and entry.get("zip") == czip:
                return entry

    if vs_by_name and czip:
        normalized = normalize_company_name(contact.get("companyName", "") or "")
        if normalized:
            for entry in vs_by_name.get(normalized, []):
                if entry.get("zip") and entry["zip"] == czip:
                    return entry
    return None


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
    vs_by_name = lookup.get("vs_by_name", {})
    vs_by_phone = lookup.get("vs_by_phone", {})
    vs_by_company_phone = lookup.get("vs_by_company_phone", {})

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
            contact["_dedup_source"] = "lead_outcomes"
            filtered.append(contact)
            continue

        # Third source: VanillaSoft history — runs regardless of companyId
        # (VS rows live in a companyId-less universe, so a known-numeric id
        # proves nothing here).
        vs_match = _match_vs_lead(contact, vs_by_name, vs_by_phone,
                                  vs_by_company_phone)
        if vs_match:
            contact["_previously_exported"] = True
            contact["_last_exported_at"] = vs_match.get("added_date", "")
            contact["_dedup_source"] = "vanillasoft"
            contact["_vs_lead_status"] = vs_match.get("lead_status", "")
            contact["_vs_added_date"] = vs_match.get("added_date", "")
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


def partition_companies_for_enrichment(
    companies: dict,
    cached_ids: dict,
    lookup: dict,
) -> tuple[dict, list[dict]]:
    """Split selected intent companies into (worth enriching, already exported).

    The headless pipeline filters previously-exported companies BEFORE
    enrichment; the Intent UI only filtered at export time, so every company
    already exported inside the dedup window was enriched — real credits spent
    on leads that were then discarded downstream (HADES-7qi).

    Matching runs before numeric company IDs exist for most companies, so it
    leans on `filter_previously_exported`'s normalized-name fallback (including
    its franchise-safety rules) and uses the numeric ID only where the company
    ID cache already has one, which is a stronger match.

    Args:
        companies: {hashed_company_id: lead dict} the operator selected.
        cached_ids: {hashed_company_id: {"numeric_id": ...}} from the ID cache.
        lookup: the dict returned by `get_previously_exported`.

    Returns:
        (kept, skipped) — `kept` is the same {hashed_id: lead} shape with the
        original lead objects intact so it can feed enrichment directly;
        `skipped` is a list of the lead dicts, each tagged by
        `filter_previously_exported` with its `_previously_exported` metadata.
    """
    candidates = []
    for hashed_id, lead in companies.items():
        candidate = dict(lead)
        candidate["_hashed_company_id"] = hashed_id
        cached = cached_ids.get(hashed_id) or {}
        if cached.get("numeric_id"):
            candidate["companyId"] = cached["numeric_id"]
        candidates.append(candidate)

    new_candidates, skipped = filter_previously_exported(candidates, lookup)

    kept_ids = {c.get("_hashed_company_id") for c in new_candidates}
    kept = {hid: lead for hid, lead in companies.items() if hid in kept_ids}
    return kept, skipped
