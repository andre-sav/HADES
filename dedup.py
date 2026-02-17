"""
Deduplication logic for phone numbers and cross-workflow leads.
"""

import re
from functools import lru_cache
from typing import Any

from rapidfuzz.fuzz import token_sort_ratio
from utils import load_config, normalize_phone


# Common company suffixes to strip for matching
COMPANY_SUFFIXES = [
    r"\s+inc\.?$",
    r"\s+incorporated$",
    r"\s+corp\.?$",
    r"\s+corporation$",
    r"\s+llc\.?$",
    r"\s+llp\.?$",
    r"\s+ltd\.?$",
    r"\s+limited$",
    r"\s+co\.?$",
    r"\s+company$",
    r"\s+pllc\.?$",
    r"\s+pc\.?$",
    r"\s+pa\.?$",
    r",?\s+inc\.?$",
    r",?\s+llc\.?$",
]


def normalize_company_name(name: str) -> str:
    """
    Normalize company name for matching.

    - Lowercase
    - Strip common suffixes (Inc, LLC, Corp, etc.)
    - Remove extra whitespace
    - Remove punctuation
    """
    if not name:
        return ""

    # Lowercase
    normalized = name.lower().strip()

    # Strip common suffixes
    for suffix in COMPANY_SUFFIXES:
        normalized = re.sub(suffix, "", normalized, flags=re.IGNORECASE)

    # Remove punctuation except spaces
    normalized = re.sub(r"[^\w\s]", "", normalized)

    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


@lru_cache(maxsize=1)
def _get_fuzzy_threshold() -> float:
    """Load fuzzy match threshold from config. Cached for process lifetime."""
    config = load_config()
    return config.get("dedup", {}).get("fuzzy_threshold", 85)


def fuzzy_company_match(
    name1: str,
    name2: str,
    threshold: float | None = None,
) -> bool:
    """
    Check if two normalized company names are a fuzzy match.

    Uses token_sort_ratio which handles word reordering.
    Names should already be passed through normalize_company_name().

    Args:
        name1: First normalized company name
        name2: Second normalized company name
        threshold: Match threshold (0-100). None = use config value.

    Returns:
        True if names match above threshold
    """
    if not name1 or not name2:
        return False

    if threshold is None:
        threshold = _get_fuzzy_threshold()

    score = token_sort_ratio(name1, name2)
    return score >= threshold


def get_dedup_key(lead: dict) -> str:
    """
    Generate deduplication key from lead data.

    Combines normalized phone and normalized company name.
    """
    phone = normalize_phone(lead.get("phone", "") or lead.get("Business", "") or "")
    company = normalize_company_name(lead.get("companyName", "") or lead.get("Company", "") or "")

    return f"{phone}|{company}"


def dedupe_by_phone(leads: list[dict], phone_field: str = "phone") -> tuple[list[dict], int]:
    """
    Remove leads with duplicate phone numbers.

    Args:
        leads: List of lead dicts
        phone_field: Field name containing phone number

    Returns:
        Tuple of (deduped_leads, removed_count)
    """
    seen_phones = set()
    deduped = []
    removed = 0

    for lead in leads:
        # Try multiple possible phone fields
        phone = (
            lead.get(phone_field)
            or lead.get("phone")
            or lead.get("Business")
            or ""
        )
        normalized = normalize_phone(phone)

        # Skip empty phones (keep the lead but don't dedupe on it)
        if not normalized:
            deduped.append(lead)
            continue

        if normalized in seen_phones:
            removed += 1
            continue

        seen_phones.add(normalized)
        deduped.append(lead)

    return deduped, removed


def dedupe_leads(leads: list[dict]) -> tuple[list[dict], int]:
    """
    Remove duplicate leads based on phone + company name.

    Keeps first occurrence (assumes leads are pre-sorted by score).

    Args:
        leads: List of lead dicts (should be sorted by score descending)

    Returns:
        Tuple of (deduped_leads, removed_count)
    """
    seen_keys = set()
    deduped = []
    removed = 0

    for lead in leads:
        key = get_dedup_key(lead)

        # If no meaningful key, keep the lead
        if key == "|":
            deduped.append(lead)
            continue

        if key in seen_keys:
            removed += 1
            continue

        seen_keys.add(key)
        deduped.append(lead)

    return deduped, removed


def find_duplicates(
    leads1: list[dict],
    leads2: list[dict],
) -> list[dict]:
    """
    Find leads that appear in both lists.

    Uses exact key matching first, then fuzzy company name fallback
    for cross-workflow dedup.

    Returns:
        List of dicts with duplicate info:
        {
            "key": dedup_key,
            "lead1": lead from leads1,
            "lead2": lead from leads2,
            "score1": score from lead1,
            "score2": score from lead2,
        }
    """
    duplicates = []
    matched_leads2_indices = set()

    # Extract normalized names for leads2 (once)
    leads2_normalized = []
    for lead in leads2:
        key = get_dedup_key(lead)
        company = normalize_company_name(
            lead.get("companyName", "") or lead.get("Company", "") or ""
        )
        leads2_normalized.append((key, company, lead))

    for lead1 in leads1:
        key1 = get_dedup_key(lead1)
        if key1 == "|":
            continue

        company1 = normalize_company_name(
            lead1.get("companyName", "") or lead1.get("Company", "") or ""
        )

        best_match = None
        best_idx = None

        for idx, (key2, company2, lead2) in enumerate(leads2_normalized):
            if idx in matched_leads2_indices:
                continue
            if key2 == "|":
                continue

            # Tier 1: exact key match
            if key1 == key2:
                best_match = lead2
                best_idx = idx
                break

            # Tier 2/3: fuzzy company match
            if company1 and company2 and fuzzy_company_match(company1, company2):
                best_match = lead2
                best_idx = idx
                break

        if best_match is not None:
            matched_leads2_indices.add(best_idx)
            duplicates.append({
                "key": key1,
                "lead1": lead1,
                "lead2": best_match,
                "score1": lead1.get("_score", 0),
                "score2": best_match.get("_score", 0),
            })

    return duplicates


def merge_lead_lists(
    intent_leads: list[dict],
    geo_leads: list[dict],
    tag_source: bool = True,
) -> tuple[list[dict], int]:
    """
    Merge intent and geography leads, keeping higher-scored duplicates.
    Uses exact key match first, then fuzzy company name fallback.

    Args:
        intent_leads: Leads from intent workflow (should have _score)
        geo_leads: Leads from geography workflow (should have _score)
        tag_source: If True, add _source field to each lead

    Returns:
        Tuple of (merged_leads, duplicate_count)
    """
    if tag_source:
        for lead in intent_leads:
            lead["_source"] = "intent"
        for lead in geo_leads:
            lead["_source"] = "geography"

    # Build index of intent leads by key and normalized company
    best_leads: dict[str, dict] = {}
    intent_companies: dict[str, str] = {}

    for lead in intent_leads:
        key = get_dedup_key(lead)
        if key == "|":
            key = f"intent_{id(lead)}"

        company = normalize_company_name(
            lead.get("companyName", "") or lead.get("Company", "") or ""
        )
        intent_companies[key] = company

        if key not in best_leads or lead.get("_score", 0) > best_leads[key].get("_score", 0):
            best_leads[key] = lead

    # Process geo leads with exact match first, then fuzzy fallback
    duplicate_count = 0
    for lead in geo_leads:
        key = get_dedup_key(lead)
        if key == "|":
            key = f"geo_{id(lead)}"

        # Try exact match first
        matched_key = None
        if key in best_leads:
            matched_key = key
        else:
            # Fuzzy fallback: compare company name against all intent companies
            geo_company = normalize_company_name(
                lead.get("companyName", "") or lead.get("Company", "") or ""
            )
            if geo_company:
                for ikey, icompany in intent_companies.items():
                    if icompany and fuzzy_company_match(geo_company, icompany):
                        matched_key = ikey
                        break

        if matched_key is not None:
            duplicate_count += 1
            if lead.get("_score", 0) > best_leads[matched_key].get("_score", 0):
                best_leads[matched_key] = lead
        else:
            best_leads[key] = lead

    merged = sorted(best_leads.values(), key=lambda x: x.get("_score", 0), reverse=True)
    return merged, duplicate_count


def flag_duplicates_in_list(leads: list[dict], other_leads: list[dict]) -> list[dict]:
    """
    Add _is_duplicate flag to leads that also appear in other_leads.
    Uses exact key match first, then fuzzy company name fallback.
    """
    other_keys = set()
    other_companies = []
    for lead in other_leads:
        key = get_dedup_key(lead)
        if key and key != "|":
            other_keys.add(key)
        company = normalize_company_name(
            lead.get("companyName", "") or lead.get("Company", "") or ""
        )
        if company:
            other_companies.append(company)

    for lead in leads:
        key = get_dedup_key(lead)

        # Tier 1: exact key match
        if key in other_keys:
            lead["_is_duplicate"] = True
            continue

        # Tier 2/3: fuzzy company fallback
        company = normalize_company_name(
            lead.get("companyName", "") or lead.get("Company", "") or ""
        )
        if company and any(fuzzy_company_match(company, oc) for oc in other_companies):
            lead["_is_duplicate"] = True
        else:
            lead["_is_duplicate"] = False

    return leads
