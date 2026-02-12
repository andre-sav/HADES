"""
Search Expansion Strategy - Auto-expand search parameters to meet target contact count.

This module handles the logic for automatically expanding ZoomInfo search parameters
when the initial search doesn't meet the target contact count. The expansion strategy
prioritizes filter relaxation over radius expansion to keep contacts geographically relevant.

Expansion Order:
1. Management levels (Manager → Director → VP/C-Level)
2. Employee cap removal (5000 → unlimited)
3. Accuracy threshold reduction (95 → 85 → 75)
4. Radius expansion (10mi → 12.5mi → 15mi → 17.5mi → 20mi) - last resort

Usage:
    from expand_search import expand_search, EXPANSION_STEPS, DEFAULT_TARGET_CONTACTS

    result = expand_search(
        client=zoominfo_client,
        base_params=search_params,
        zip_codes=["75201", "75202"],
        states=["TX"],
        target=25,
        stop_early=True,
    )
"""

import logging
import time
from typing import Any, Optional

from zoominfo_client import ContactQueryParams
from geo import get_zips_in_radius, get_states_from_zips
from utils import get_employee_minimum

logger = logging.getLogger(__name__)

# =============================================================================
# EXPANSION CONFIGURATION
# =============================================================================

# Applied in order when target contact count not met
# Strategy: Expand filter criteria FIRST, radius LAST (preserve geographic area)
# Valid ZoomInfo management levels: Board Member, C Level Exec, VP Level Exec, Director, Manager, Non Manager
EXPANSION_STEPS = [
    # Phase 1: Expand management levels (stay in territory)
    {"management_levels": ["Manager", "Director"]},
    {"management_levels": ["Manager", "Director", "VP Level Exec", "C Level Exec"]},
    # Phase 2: Remove employee cap (larger companies)
    {"employee_max": 0},  # Remove 5000 cap (0 = no limit)
    # Phase 3: Lower accuracy threshold (more contacts)
    {"accuracy_min": 85},
    {"accuracy_min": 75},
    # Phase 4: Expand radius as last resort
    {"radius": 12.5},
    {"radius": 15.0},
    {"radius": 17.5},
    {"radius": 20.0},
]

# Default starting values
DEFAULT_TARGET_CONTACTS = 25
DEFAULT_START_RADIUS = 10.0
DEFAULT_START_ACCURACY = 95
DEFAULT_START_MANAGEMENT = ["Manager"]
DEFAULT_START_EMPLOYEE_MAX = 5000


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def build_contacts_by_company(contacts_list: list) -> dict:
    """
    Group contacts by company and sort by accuracy score.

    Args:
        contacts_list: List of contact dicts from ZoomInfo API

    Returns:
        Dict mapping company_id to {"company_name": str, "contacts": list}
    """
    contacts_by_company = {}

    for contact in contacts_list:
        company_id = contact.get("companyId") or contact.get("company", {}).get("id")
        company_name = contact.get("companyName") or contact.get("company", {}).get("name", "Unknown")
        if company_id:
            if company_id not in contacts_by_company:
                contacts_by_company[company_id] = {
                    "company_name": company_name,
                    "contacts": [],
                }
            contacts_by_company[company_id]["contacts"].append(contact)

    # Sort contacts within each company by accuracy score
    for company_id, data in contacts_by_company.items():
        data["contacts"].sort(
            key=lambda c: c.get("contactAccuracyScore", 0),
            reverse=True,
        )

    return contacts_by_company


def get_company_id(contact: dict) -> Optional[str]:
    """Extract company ID from contact (handles nested structure)."""
    return contact.get("companyId") or contact.get("company", {}).get("id")


# =============================================================================
# MAIN EXPANSION FUNCTION
# =============================================================================

def expand_search(
    client,
    base_params: dict,
    zip_codes: list[str],
    states: list[str],
    target: int,
    stop_early: bool,
    status_container: Any = None,
) -> dict:
    """
    Search with automatic expansion until target met or steps exhausted.

    This function performs an initial search with the provided parameters, then
    progressively relaxes search criteria if the target contact count isn't met.
    Expansion happens in a specific order to maintain geographic relevance:
    management levels → employee cap → accuracy → radius.

    Args:
        client: ZoomInfo client instance
        base_params: Starting search parameters dict with keys:
            - radius: Starting radius in miles
            - accuracy_min: Minimum accuracy score (0-100)
            - management_levels: List of management levels
            - employee_max: Maximum employee count (0 = no limit)
            - location_type: PersonAndHQ, Person, etc.
            - include_person_only: Run combined search
            - current_only: Only current employees
            - required_fields: List of required field names
            - required_fields_operator: "or" or "and"
            - exclude_org_exported: Skip previously exported contacts
            - sic_codes: List of SIC codes to filter
            - center_zip: Center ZIP for radius recalculation
        zip_codes: List of ZIP codes to search
        states: List of state codes (e.g., ["TX", "CA"])
        target: Target number of unique companies (not contacts)
        stop_early: Stop once target reached (vs. run all expansion steps)
        status_container: Optional Streamlit status container for progress updates

    Returns:
        dict with keys:
            - target: The target count requested
            - found: Number of unique companies found
            - found_contacts: Total contacts found
            - target_met: Whether target was reached
            - steps_applied: Number of expansion steps used
            - final_params: The final search parameters used
            - searches_performed: Number of API calls made
            - contacts: List of all contacts found
            - contacts_by_company: Dict grouping contacts by company
            - expansion_log: List of progress messages
            - error: Error message if search failed (optional)
    """
    all_contacts = {}  # personId -> contact (for deduplication)
    unique_companies = set()  # Track unique company IDs for target comparison
    searches_performed = 0
    steps_applied = 0
    expansion_log = []  # Track what we did for verbose output

    def log_progress(message: str, is_step: bool = False):
        """Log progress to status container if available."""
        expansion_log.append(message)
        if status_container:
            status_container.write(f"{'→' if is_step else '  '} {message}")

    # Current parameters (will be modified by expansion)
    current_params = {
        "radius": base_params.get("radius", DEFAULT_START_RADIUS),
        "accuracy_min": base_params.get("accuracy_min", DEFAULT_START_ACCURACY),
        "management_levels": list(base_params.get("management_levels", DEFAULT_START_MANAGEMENT)),
        "employee_max": base_params.get("employee_max", DEFAULT_START_EMPLOYEE_MAX),
    }

    # Fixed parameters (don't change during expansion)
    fixed_params = {
        "location_type": base_params.get("location_type", "PersonAndHQ"),
        "current_only": base_params.get("current_only", True),
        "required_fields": base_params.get("required_fields"),
        "required_fields_operator": base_params.get("required_fields_operator", "or"),
        "exclude_org_exported": base_params.get("exclude_org_exported", True),
        "sic_codes": base_params.get("sic_codes", []),
    }

    # Combined search flag (run both PersonAndHQ and Person, merge results)
    include_person_only = base_params.get("include_person_only", False)
    center_zip = base_params.get("center_zip")

    def do_search(radius_miles, accuracy_min, management_levels, employee_max, location_type_override=None):
        """Execute a single search with given parameters."""
        # Recalculate ZIPs if radius changed and we have a center ZIP
        if center_zip and radius_miles != base_params.get("radius"):
            calculated = get_zips_in_radius(center_zip, radius_miles)
            search_zips = [z["zip"] for z in calculated]
            search_states = get_states_from_zips(calculated)
        else:
            search_zips = zip_codes
            search_states = states

        # Allow override for combined search (Person-only after PersonAndHQ)
        search_location_type = location_type_override if location_type_override else fixed_params["location_type"]

        params = ContactQueryParams(
            zip_codes=search_zips,
            radius_miles=0,  # Explicit ZIP list
            states=search_states,
            location_type=search_location_type,
            employee_min=get_employee_minimum(),
            employee_max=employee_max,
            sic_codes=fixed_params["sic_codes"],
            company_past_or_present="present" if fixed_params["current_only"] else "pastOrPresent",
            exclude_partial_profiles=True,
            required_fields=fixed_params["required_fields"],
            required_fields_operator=fixed_params["required_fields_operator"],
            contact_accuracy_score_min=accuracy_min,
            exclude_org_exported=fixed_params["exclude_org_exported"],
            management_levels=management_levels if management_levels else None,
        )

        return client.search_contacts_all_pages(params, max_pages=5)

    def process_contacts(contacts: list, location_type_tag: str = None) -> tuple[int, int]:
        """Add contacts to tracking dicts, return (new_contacts, new_companies).

        Args:
            contacts: List of contact dicts from API
            location_type_tag: Optional tag to add as _location_type field.
                When combined search is enabled, contacts get tagged:
                - "PersonAndHQ" = Contact's location AND company HQ match
                - "Person" = Only contact's location matches (branch office)
        """
        new_contacts = 0
        new_companies = 0
        for c in contacts:
            person_id = c.get("id") or c.get("personId")
            company_id = get_company_id(c)
            if person_id and person_id not in all_contacts:
                # Tag with location type if provided (for combined search demarcation)
                if location_type_tag:
                    c["_location_type"] = location_type_tag
                all_contacts[person_id] = c
                new_contacts += 1
                if company_id and company_id not in unique_companies:
                    unique_companies.add(company_id)
                    new_companies += 1
        return new_contacts, new_companies

    # Initial search
    log_progress(
        f"**Initial search:** {current_params['radius']}mi radius, "
        f"{current_params['accuracy_min']} accuracy, "
        f"{'/'.join(current_params['management_levels'])}",
        is_step=True
    )
    log_progress(f"Searching {len(zip_codes)} ZIP codes...")

    try:
        contacts = do_search(
            current_params["radius"],
            current_params["accuracy_min"],
            current_params["management_levels"],
            current_params["employee_max"],
        )
        searches_performed += 1

        # Tag contacts with location type when combined search is enabled
        location_tag = "PersonAndHQ" if include_person_only else None
        new_contacts, new_companies = process_contacts(contacts, location_type_tag=location_tag)
        log_progress(f"Found **{len(contacts)}** contacts → **{len(unique_companies)}** companies ({new_companies} new)")

        # Combined search: If include_person_only is enabled, run Person-only search and merge
        if include_person_only and fixed_params["location_type"] == "PersonAndHQ":
            time.sleep(0.5)  # Rate limit
            log_progress("**Combined search:** Adding Person-only results for maximum coverage...", is_step=True)

            try:
                person_only_contacts = do_search(
                    current_params["radius"],
                    current_params["accuracy_min"],
                    current_params["management_levels"],
                    current_params["employee_max"],
                    location_type_override="Person",
                )
                searches_performed += 1

                # Tag Person-only contacts (only new ones not already in PersonAndHQ results)
                person_new_contacts, person_new_companies = process_contacts(
                    person_only_contacts, location_type_tag="Person"
                )
                log_progress(
                    f"Person-only found **{len(person_only_contacts)}** contacts → "
                    f"**+{person_new_companies}** new companies (total: {len(unique_companies)})"
                )
            except Exception as e:
                log_progress(f"Person-only search failed: {e} (continuing with PersonAndHQ results)")
                logger.warning(f"Person-only combined search failed: {e}")

    except Exception as e:
        log_progress(f"Search failed: {e}")
        return {
            "target": target,
            "found": 0,
            "target_met": False,
            "steps_applied": 0,
            "final_params": current_params,
            "searches_performed": searches_performed,
            "contacts": [],
            "contacts_by_company": {},
            "error": str(e),
            "expansion_log": expansion_log,
        }

    # Check if target already met before expansion (target = unique companies, not contacts)
    if stop_early and len(unique_companies) >= target:
        log_progress(f"**Target met!** {len(unique_companies)} companies >= {target} (no expansion needed)")
        contacts_list = list(all_contacts.values())
        contacts_by_company = build_contacts_by_company(contacts_list)
        return {
            "target": target,
            "found": len(unique_companies),
            "found_contacts": len(all_contacts),
            "target_met": True,
            "steps_applied": 0,
            "final_params": current_params,
            "searches_performed": searches_performed,
            "contacts": contacts_list,
            "contacts_by_company": contacts_by_company,
            "expansion_log": expansion_log,
        }

    if len(unique_companies) < target:
        log_progress(f"Only {len(unique_companies)} companies of {target} target - starting expansion...")

    # Expansion loop
    total_expansion_steps = len(EXPANSION_STEPS)
    for step_index, step in enumerate(EXPANSION_STEPS):
        # Skip expansion steps that would REDUCE the search scope
        should_skip = False
        skip_reason = None

        if "radius" in step and step["radius"] <= current_params["radius"]:
            should_skip = True
            skip_reason = f"radius {step['radius']}mi <= current {current_params['radius']}mi"
        if "accuracy_min" in step and step["accuracy_min"] >= current_params["accuracy_min"]:
            should_skip = True
            skip_reason = f"accuracy {step['accuracy_min']} >= current {current_params['accuracy_min']}"
        if "management_levels" in step and len(step["management_levels"]) <= len(current_params["management_levels"]):
            should_skip = True
            skip_reason = "management levels not expanding"
        if "employee_max" in step:
            curr_max = current_params["employee_max"]
            step_max = step["employee_max"]
            if curr_max == 0:
                should_skip = True
                skip_reason = "employee_max already uncapped"
            elif step_max != 0 and step_max <= curr_max:
                should_skip = True
                skip_reason = f"employee_max {step_max} <= current {curr_max}"

        if should_skip:
            log_progress(f"Skipping expansion step: {skip_reason}")
            continue

        # Describe and apply expansion
        expansion_desc = []
        if "radius" in step:
            expansion_desc.append(f"radius → {step['radius']}mi")
            current_params["radius"] = step["radius"]
        if "accuracy_min" in step:
            expansion_desc.append(f"accuracy → {step['accuracy_min']}")
            current_params["accuracy_min"] = step["accuracy_min"]
        if "management_levels" in step:
            levels = "/".join(step["management_levels"])
            expansion_desc.append(f"management → {levels}")
            current_params["management_levels"] = list(step["management_levels"])
        if "employee_max" in step:
            if step["employee_max"] == 0:
                expansion_desc.append("employees → 50+ (no cap)")
            else:
                expansion_desc.append(f"employees → 50-{step['employee_max']:,}")
            current_params["employee_max"] = step["employee_max"]

        steps_applied += 1
        log_progress(f"**Expansion {steps_applied}/{total_expansion_steps}:** {', '.join(expansion_desc)}", is_step=True)

        # Rate limit delay
        time.sleep(0.5)

        # Search with new parameters
        try:
            contacts = do_search(
                current_params["radius"],
                current_params["accuracy_min"],
                current_params["management_levels"],
                current_params["employee_max"],
            )
            searches_performed += 1

            # Tag contacts with location type when combined search is enabled
            exp_location_tag = "PersonAndHQ" if include_person_only else None
            new_contacts, new_companies = process_contacts(contacts, location_type_tag=exp_location_tag)
            log_progress(f"Found {len(contacts)} contacts → **{len(unique_companies)}** companies (+{new_companies} new)")

            # Combined search: Run Person-only search during expansion too
            if include_person_only and fixed_params["location_type"] == "PersonAndHQ":
                time.sleep(0.5)  # Rate limit
                try:
                    person_only_contacts = do_search(
                        current_params["radius"],
                        current_params["accuracy_min"],
                        current_params["management_levels"],
                        current_params["employee_max"],
                        location_type_override="Person",
                    )
                    searches_performed += 1
                    person_new_contacts, person_new_companies = process_contacts(
                        person_only_contacts, location_type_tag="Person"
                    )
                    if person_new_companies > 0:
                        log_progress(f"Person-only expansion: +{person_new_companies} new companies")
                except Exception as e:
                    logger.warning(f"Person-only expansion search failed: {e}")

        except Exception as e:
            log_progress(f"Search failed: {e}")
            logger.warning(
                f"Expansion step {steps_applied} failed: {e}. "
                f"Returning {len(all_contacts)} contacts found so far."
            )
            break

        # Check if target met after this step
        if stop_early and len(unique_companies) >= target:
            log_progress(f"**Target met!** {len(unique_companies)} companies >= {target} (stopping expansion)")
            break

        # Show progress toward target
        remaining = target - len(unique_companies)
        if remaining > 0 and step_index < total_expansion_steps - 1:
            log_progress(f"Still need {remaining} more companies...")

    # Build final result
    contacts_list = list(all_contacts.values())
    contacts_by_company = build_contacts_by_company(contacts_list)
    company_count = len(contacts_by_company)

    # Final summary
    if company_count >= target:
        log_progress(f"**Complete:** {company_count} companies (target: {target}) with {len(all_contacts)} total contacts")
    else:
        log_progress(f"**Complete:** {company_count} of {target} target companies ({len(all_contacts)} contacts)")

    return {
        "target": target,
        "found": company_count,
        "found_contacts": len(all_contacts),
        "target_met": company_count >= target,
        "steps_applied": steps_applied,
        "final_params": current_params,
        "searches_performed": searches_performed,
        "contacts": contacts_list,
        "contacts_by_company": contacts_by_company,
        "expansion_log": expansion_log,
    }
