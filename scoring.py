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
)


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

    # Signal strength score
    strength = lead.get("intentStrength", "Low")
    signal_score = get_signal_strength_score(strength)

    # On-site likelihood score
    sic_code = lead.get("sicCode", "")
    onsite_score = get_onsite_likelihood_score(sic_code)

    # Freshness score
    intent_date = lead.get("intentDate")
    age_days = _calculate_age_days(intent_date)
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

    # Calculate weighted composite score
    composite = (
        signal_score * weights["signal_strength"]
        + onsite_score * weights["onsite_likelihood"]
        + freshness_score * weights["freshness"]
    )

    return {
        "score": round(composite),
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
        proximity_score = get_proximity_score(float(distance))
        distance_miles = float(distance)
    else:
        # Default to medium proximity if distance not provided
        proximity_score = 70
        distance_miles = None

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

    # Calculate weighted composite score
    composite = (
        proximity_score * weights["proximity"]
        + onsite_score * weights["onsite_likelihood"]
        + employee_score * weights["employee_scale"]
    )

    return {
        "score": round(composite),
        "proximity_score": proximity_score,
        "onsite_score": onsite_score,
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
        f"Size: {lead.get('_employee_score', 0)})"
    )


def _calculate_age_days(date_str: str | None) -> int:
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

    Weights:
        - Company intent score: 70%
        - Contact accuracy: 20%
        - Phone availability: 10%

    Args:
        contacts: List of contact dicts from Contact Search
        company_scores: Dict mapping company_id -> {"_score": int, "intentTopic": str, ...}

    Returns:
        List of contacts with scoring fields added, sorted by score descending.
    """
    scored = []

    for contact in contacts:
        company_id = (
            contact.get("companyId")
            or contact.get("company", {}).get("id")
            or ""
        )
        company_data = company_scores.get(str(company_id), {})
        company_intent_score = company_data.get("_score", 50)

        # Accuracy component (0-100)
        accuracy = contact.get("contactAccuracyScore", 0) or 0
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

        # Weighted composite
        composite = (
            company_intent_score * 0.70
            + accuracy_score * 0.20
            + phone_score * 0.10
        )

        scored_contact = {
            **contact,
            "_score": round(composite),
            "_company_intent_score": company_intent_score,
            "_accuracy_score": accuracy_score,
            "_phone_score": phone_score,
            "_intent_topic": company_data.get("intentTopic", ""),
        }
        scored.append(scored_contact)

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored


def get_score_breakdown_intent_contact(lead: dict) -> str:
    """Get human-readable score breakdown for intent contact."""
    return (
        f"Score: {lead.get('_score', 0)} "
        f"(Intent: {lead.get('_company_intent_score', 0)}, "
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
