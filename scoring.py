"""
Lead scoring engine for Intent and Geography workflows.
"""

from datetime import datetime, date
from typing import Any

from utils import (
    get_scoring_weights,
    get_signal_strength_score,
    get_freshness_multiplier,
    get_onsite_likelihood_score,
    get_employee_scale_score,
    get_proximity_score,
    get_authority_score,
    get_authority_title_keywords,
)


def _calculate_authority_score(contact: dict) -> int:
    """
    Calculate authority score based on management level and title keywords.

    Management level base score (from config):
        C-Level=100, VP=85, Director=75, Manager=60, Non-Manager=30

    Title keyword bonus: +10 for vending-relevant keywords (facilities,
    operations, vending, food service, etc.), capped at 100.

    Args:
        contact: Contact dict with 'managementLevel' and 'jobTitle' fields

    Returns:
        Authority score 0-100
    """
    mgmt_level = contact.get("managementLevel", "")
    # Enrich API may return list instead of string
    if isinstance(mgmt_level, list):
        mgmt_level = mgmt_level[0] if mgmt_level else ""
    base_score = get_authority_score(mgmt_level)

    # Title keyword bonus
    title = (contact.get("jobTitle") or "").lower()
    if title:
        keywords = get_authority_title_keywords()
        if any(kw in title for kw in keywords):
            base_score = min(100, base_score + 10)

    return base_score


def calculate_intent_score(lead: dict) -> dict:
    """
    Calculate composite score for an intent lead.

    Args:
        lead: Lead data from ZoomInfo Intent API containing:
            - intentStrength: "High", "Medium", or "Low"
            - intentDate: Date string of intent signal
            - sicCode: SIC code for on-site likelihood

    Returns:
        Dict with score details:
            - score: Composite score 0-100
            - signal_score: Signal strength component
            - onsite_score: On-site likelihood component
            - freshness_score: Freshness component
            - freshness_label: "Hot", "Warm", "Cooling", or "Stale"
            - age_days: Age of intent signal in days
            - excluded: True if lead should be excluded (stale)
    """
    weights = get_scoring_weights("intent")

    # Signal strength score — prefer numeric signalScore for differentiation
    signal_score_raw = lead.get("signalScore")
    if signal_score_raw and isinstance(signal_score_raw, (int, float)) and signal_score_raw > 0:
        signal_score = min(100, int(signal_score_raw))
    else:
        strength = lead.get("intentStrength", "Low")
        signal_score = get_signal_strength_score(strength)

    # On-site likelihood score
    sic_code = lead.get("sicCode", "")
    onsite_score = get_onsite_likelihood_score(sic_code)

    # Freshness score
    intent_date = lead.get("intentDate")
    age_days = calculate_age_days(intent_date)
    freshness_multiplier, freshness_label = get_freshness_multiplier(age_days)

    # If stale, exclude the lead
    if freshness_multiplier == 0:
        return {
            "score": 0,
            "signal_score": signal_score,
            "onsite_score": onsite_score,
            "freshness_score": 0,
            "freshness_label": freshness_label,
            "age_days": age_days,
            "excluded": True,
        }

    # Calculate freshness score (base 100 * multiplier)
    freshness_score = int(100 * freshness_multiplier)

    # Audience strength bonus (0-10 points)
    audience = lead.get("audienceStrength", "")
    audience_bonus = {"A": 10, "B": 7, "C": 4, "D": 2}.get(audience, 0)

    # Employee scale bonus (0-5 points) — larger companies = more machines
    employees = lead.get("employees") or 0
    if isinstance(employees, str):
        employees = int(employees) if employees.isdigit() else 0
    employee_bonus = min(5, employees // 200) if employees else 0

    # Calculate weighted composite score
    composite = (
        signal_score * weights["signal_strength"]
        + onsite_score * weights["onsite_likelihood"]
        + freshness_score * weights["freshness"]
        + audience_bonus + employee_bonus
    )

    return {
        "score": min(100, round(composite)),
        "signal_score": signal_score,
        "onsite_score": onsite_score,
        "freshness_score": freshness_score,
        "freshness_label": freshness_label,
        "age_days": age_days,
        "excluded": False,
    }


def calculate_geography_score(lead: dict, target_zip: str = None) -> dict:
    """
    Calculate composite score for a geography lead.

    Args:
        lead: Lead data from ZoomInfo Company Search API containing:
            - distance: Distance in miles from search center (if available)
            - sicCode: SIC code for on-site likelihood
            - employees: Employee count
        target_zip: Primary target zip code (for reference)

    Returns:
        Dict with score details:
            - score: Composite score 0-100
            - proximity_score: Proximity component
            - onsite_score: On-site likelihood component
            - employee_score: Employee scale component
            - distance_miles: Distance from target (if available)
    """
    weights = get_scoring_weights("geography")

    # Proximity score
    distance = lead.get("distance")
    if distance is not None:
        try:
            distance_miles = float(distance)
        except (ValueError, TypeError):
            # Handle non-numeric strings like "5.0 miles"
            import re
            nums = re.findall(r"[\d.]+", str(distance))
            distance_miles = float(nums[0]) if nums else 15.0
        proximity_score = get_proximity_score(distance_miles)
    else:
        # Default: assume ~15mi (mid-range tier) when distance unknown
        proximity_score = get_proximity_score(15.0)
        distance_miles = 15.0

    # On-site likelihood score
    sic_code = lead.get("sicCode", "")
    onsite_score = get_onsite_likelihood_score(sic_code)

    # Employee scale score
    employees = lead.get("employees") or lead.get("employeeCount") or 50
    try:
        employee_count = int(employees)
    except (ValueError, TypeError):
        employee_count = 50
    employee_score = get_employee_scale_score(employee_count)

    # Authority score
    authority_score = _calculate_authority_score(lead)

    # Calculate weighted composite score
    composite = (
        proximity_score * weights.get("proximity", 0.40)
        + onsite_score * weights.get("onsite_likelihood", 0.25)
        + authority_score * weights.get("authority", 0.15)
        + employee_score * weights.get("employee_scale", 0.20)
    )

    return {
        "score": min(100, round(composite)),
        "proximity_score": proximity_score,
        "onsite_score": onsite_score,
        "authority_score": authority_score,
        "employee_score": employee_score,
        "distance_miles": distance_miles,
    }


def score_intent_leads(leads: list[dict]) -> list[dict]:
    """
    Score a list of intent leads and filter out stale ones.

    Args:
        leads: List of leads from ZoomInfo Intent API

    Returns:
        List of leads with score data added, excluding stale leads.
        Sorted by score descending.
    """
    scored_leads = []

    for lead in leads:
        score_data = calculate_intent_score(lead)

        # Skip excluded (stale) leads
        if score_data["excluded"]:
            continue

        # Add score data to lead
        scored_lead = {
            **lead,
            "_score": score_data["score"],
            "_signal_score": score_data["signal_score"],
            "_onsite_score": score_data["onsite_score"],
            "_freshness_score": score_data["freshness_score"],
            "_freshness_label": score_data["freshness_label"],
            "_age_days": score_data["age_days"],
        }
        scored_leads.append(scored_lead)

    # Sort by score descending
    scored_leads.sort(key=lambda x: x["_score"], reverse=True)

    return scored_leads


def score_geography_leads(leads: list[dict], target_zip: str = None) -> list[dict]:
    """
    Score a list of geography leads.

    Args:
        leads: List of leads from ZoomInfo Company Search API
        target_zip: Primary target zip code

    Returns:
        List of leads with score data added, sorted by score descending.
    """
    scored_leads = []

    for lead in leads:
        score_data = calculate_geography_score(lead, target_zip)

        # Add score data to lead
        scored_lead = {
            **lead,
            "_score": score_data["score"],
            "_proximity_score": score_data["proximity_score"],
            "_onsite_score": score_data["onsite_score"],
            "_authority_score": score_data["authority_score"],
            "_employee_score": score_data["employee_score"],
            "_distance_miles": score_data["distance_miles"],
        }
        scored_leads.append(scored_lead)

    # Sort by score descending
    scored_leads.sort(key=lambda x: x["_score"], reverse=True)

    return scored_leads


def get_score_breakdown_intent(lead: dict) -> str:
    """Get human-readable score breakdown for intent lead."""
    return (
        f"Score: {lead.get('_score', 0)} "
        f"(Signal: {lead.get('_signal_score', 0)}, "
        f"On-site: {lead.get('_onsite_score', 0)}, "
        f"Fresh: {lead.get('_freshness_score', 0)})"
    )


def get_score_breakdown_geography(lead: dict) -> str:
    """Get human-readable score breakdown for geography lead."""
    return (
        f"Score: {lead.get('_score', 0)} "
        f"(Proximity: {lead.get('_proximity_score', 0)}, "
        f"On-site: {lead.get('_onsite_score', 0)}, "
        f"Authority: {lead.get('_authority_score', 0)}, "
        f"Size: {lead.get('_employee_score', 0)})"
    )


def calculate_age_days(date_str: str | None) -> int:
    """Calculate age in days from a date string."""
    if not date_str:
        return 999  # Unknown date treated as very old

    try:
        # Handle various date formats
        date_s = str(date_str).strip()
        if "T" in date_s:
            # ISO format with time: 2026-01-24T00:00:00Z
            intent_date = datetime.fromisoformat(date_s.replace("Z", "+00:00")).date()
        elif "/" in date_s:
            # US format from legacy API: 1/24/2026 12:00 AM or 1/24/2026
            date_part = date_s.split(" ")[0]  # Strip time portion
            intent_date = datetime.strptime(date_part, "%m/%d/%Y").date()
        else:
            # Date only: 2026-01-24
            intent_date = datetime.strptime(date_s[:10], "%Y-%m-%d").date()

        age = (date.today() - intent_date).days
        return max(0, age)  # Don't return negative days

    except (ValueError, TypeError):
        return 999  # Parse error treated as very old


def score_intent_contacts(
    contacts: list[dict],
    company_scores: dict[str, dict],
) -> list[dict]:
    """
    Score contacts found at intent companies.

    Combines the company's intent score with individual contact quality.

    Weights (from config intent_contact):
        - Company intent score: 60%
        - Authority: 15%
        - Contact accuracy: 15%
        - Phone availability: 10%

    Args:
        contacts: List of contact dicts from Contact Search
        company_scores: Dict mapping company_id -> {"_score": int, "intentTopic": str, ...}

    Returns:
        List of contacts with scoring fields added, sorted by score descending.
    """
    weights = get_scoring_weights("intent_contact")
    scored = []

    for contact in contacts:
        co = contact.get("company") if isinstance(contact.get("company"), dict) else {}
        company_id = (
            contact.get("companyId")
            or co.get("id")
            or ""
        )
        company_data = company_scores.get(str(company_id), {})
        company_intent_score = company_data.get("_score", 50)

        # Accuracy component (0-100)
        raw_accuracy = contact.get("contactAccuracyScore", 0) or 0
        try:
            accuracy = int(raw_accuracy)
        except (ValueError, TypeError):
            # Handle strings like "95%" or "N/A"
            import re
            nums = re.findall(r"\d+", str(raw_accuracy))
            accuracy = int(nums[0]) if nums else 0
        if accuracy >= 95:
            accuracy_score = 100
        elif accuracy >= 85:
            accuracy_score = 70
        else:
            accuracy_score = 40

        # Phone availability component (0-100)
        has_mobile = bool(contact.get("mobilePhone"))
        has_any_phone = bool(
            contact.get("mobilePhone")
            or contact.get("directPhone")
            or contact.get("phone")
        )
        if has_mobile:
            phone_score = 100
        elif has_any_phone:
            phone_score = 70
        else:
            phone_score = 0

        # Authority component (0-100)
        authority_score = _calculate_authority_score(contact)

        # Weighted composite
        composite = (
            company_intent_score * weights.get("company_intent", 0.60)
            + authority_score * weights.get("authority", 0.15)
            + accuracy_score * weights.get("accuracy", 0.15)
            + phone_score * weights.get("phone", 0.10)
        )

        scored_contact = {
            **contact,
            "_score": round(composite),
            "_company_intent_score": company_intent_score,
            "_authority_score": authority_score,
            "_accuracy_score": accuracy_score,
            "_phone_score": phone_score,
            "_intent_topic": company_data.get("intentTopic", ""),
            "_intent_age_days": calculate_age_days(company_data.get("intentDate")),
        }

        # Carry company-level fields from intent data onto contact if missing
        # Contact Search/Enrich may not include sicCode, employees, or industry
        for field in ("sicCode", "employees", "industry"):
            if not scored_contact.get(field) and company_data.get(field):
                scored_contact[field] = company_data[field]
        scored.append(scored_contact)

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored


def get_score_breakdown_intent_contact(lead: dict) -> str:
    """Get human-readable score breakdown for intent contact."""
    return (
        f"Score: {lead.get('_score', 0)} "
        f"(Intent: {lead.get('_company_intent_score', 0)}, "
        f"Authority: {lead.get('_authority_score', 0)}, "
        f"Accuracy: {lead.get('_accuracy_score', 0)}, "
        f"Phone: {lead.get('_phone_score', 0)})"
    )


def get_priority_label(score: int) -> str:
    """Get priority label based on score."""
    if score >= 80:
        return "High"
    elif score >= 60:
        return "Medium"
    elif score >= 40:
        return "Low"
    else:
        return "Very Low"


def get_priority_action(score: int) -> str:
    """Get actionable call-to-action phrase based on score."""
    if score >= 80:
        return "Call first — strong match"
    elif score >= 60:
        return "Good prospect — review details"
    else:
        return "Lower fit — call if capacity allows"


def generate_score_summary(lead: dict, workflow_type: str) -> str:
    """Generate a plain-English summary sentence from component scores.

    Returns unescaped text — callers rendering as HTML must apply html.escape().
    """
    from utils import SIC_CODE_DESCRIPTIONS

    if workflow_type == "geography":
        prox = lead.get("_proximity_score", 0)
        onsite = lead.get("_onsite_score", 0)

        # Proximity phrase
        dist = lead.get("_distance_miles")
        try:
            dist_display = f"{float(dist):.0f}" if dist is not None else None
        except (TypeError, ValueError):
            dist_display = str(dist) if dist else None
        if prox >= 70:
            prox_phrase = f"Nearby ({dist_display} mi)" if dist_display else "Nearby"
        elif prox >= 40:
            prox_phrase = f"Moderate distance ({dist_display} mi)" if dist_display else "Moderate distance"
        else:
            prox_phrase = f"Far ({dist_display} mi)" if dist_display else "Far from target"

        # Authority phrase
        mgmt = lead.get("managementLevel", "")
        if isinstance(mgmt, list):
            mgmt = mgmt[0] if mgmt else ""
        auth_phrase = mgmt.lower() if mgmt else "contact"

        # Industry phrase
        sic = lead.get("sicCode", "")
        sic_name = SIC_CODE_DESCRIPTIONS.get(sic, "")
        if onsite >= 70:
            ind_phrase = f"strong industry fit ({sic_name})" if sic_name else "strong industry fit"
        elif onsite >= 40:
            ind_phrase = f"moderate industry fit ({sic_name})" if sic_name else "moderate industry fit"
        else:
            ind_phrase = f"low industry fit ({sic_name})" if sic_name else "low industry fit"

        # Company size phrase
        emps = lead.get("employees") or lead.get("employeeCount") or 0
        if isinstance(emps, str):
            emps = int(emps) if emps.isdigit() else 0
        size_phrase = f"{emps:,} employees" if emps else ""

        parts = [prox_phrase, auth_phrase, size_phrase, ind_phrase]
        return " · ".join(p for p in parts if p)

    elif workflow_type == "intent":
        intent = lead.get("_company_intent_score", 0)

        # Signal phrase
        if intent >= 70:
            sig_phrase = "Strong intent signal"
        elif intent >= 40:
            sig_phrase = "Moderate intent signal"
        else:
            sig_phrase = "Weak intent signal"

        # Authority
        mgmt = lead.get("managementLevel", "")
        if isinstance(mgmt, list):
            mgmt = mgmt[0] if mgmt else ""
        auth_phrase = mgmt.lower() if mgmt else "contact"

        parts = [sig_phrase, auth_phrase]
        return " · ".join(p for p in parts if p)

    return ""
