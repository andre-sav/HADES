"""
Utility functions for the ZoomInfo Lead Pipeline.
Includes config loading, phone cleaning, and column mapping.
"""

import hmac
import re
import time
from pathlib import Path
from functools import lru_cache

import streamlit as st
import yaml


# --- Authentication Gate ---

def require_auth() -> None:
    """Block page rendering unless the user has entered the correct password.

    Uses ``APP_PASSWORD`` from Streamlit secrets.  If the secret is not
    configured, the gate is skipped so local development works without a
    password.  Once authenticated, the flag persists in session state for
    the browser session.
    """
    password = st.secrets.get("APP_PASSWORD")
    if not password:
        return  # no secret configured — skip gate (local dev)

    if st.session_state.get("authenticated"):
        return

    st.markdown(
        "<div style='max-width:380px;margin:4rem auto;'>",
        unsafe_allow_html=True,
    )
    st.markdown("### Sign in to HADES")
    entered = st.text_input("Password", type="password", key="_auth_pw")
    # Rate limiting: progressive delay after failed attempts
    failed_attempts = st.session_state.get("_auth_failed", 0)
    locked_until = st.session_state.get("_auth_locked_until", 0)
    now = time.time()

    if now < locked_until:
        remaining = int(locked_until - now) + 1
        st.warning(f"Too many attempts. Try again in {remaining}s.")
        st.button("Enter", type="primary", use_container_width=True, disabled=True)
    elif st.button("Enter", type="primary", use_container_width=True):
        if hmac.compare_digest(entered, password):
            st.session_state["authenticated"] = True
            st.session_state.pop("_auth_failed", None)
            st.session_state.pop("_auth_locked_until", None)
            st.rerun()
        else:
            failed_attempts += 1
            st.session_state["_auth_failed"] = failed_attempts
            # Progressive lockout: 2s, 4s, 8s, 16s, 30s max
            if failed_attempts >= 3:
                delay = min(2 ** (failed_attempts - 2), 30)
                st.session_state["_auth_locked_until"] = now + delay
            st.error("Incorrect password")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


def safe_company(lead: dict) -> dict:
    """Return the 'company' field as a dict, guarding against list/None from messy API data."""
    co = lead.get("company")
    return co if isinstance(co, dict) else {}


# --- Configuration Loading ---

@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load ICP configuration from YAML file.

    Cached for the process lifetime — restart the app to pick up YAML changes.
    """
    config_path = Path(__file__).parent / "config" / "icp.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_hard_filters() -> dict:
    """Get hard ICP filters for API queries."""
    config = load_config()
    return config.get("hard_filters", {})


def get_scoring_weights(workflow_type: str) -> dict:
    """Get scoring weights for a workflow type ('intent' or 'geography')."""
    config = load_config()
    return config.get("scoring", {}).get(workflow_type, {})


def get_call_center_agents() -> list[str]:
    """Get call center agent emails for round-robin Contact Owner assignment."""
    config = load_config()
    return config.get("call_center_agents", [])


def get_signal_strength_score(strength: str) -> int:
    """Get score for intent signal strength."""
    config = load_config()
    scores = config.get("signal_strength_scores", {})
    return scores.get(strength, 0)


def get_freshness_multiplier(age_days: int) -> tuple[float, str]:
    """Get freshness multiplier and label for intent age in days."""
    config = load_config()
    freshness = config.get("freshness", {})

    for tier in ["hot", "warm", "cooling", "stale"]:
        tier_config = freshness.get(tier, {})
        if age_days <= tier_config.get("max_days", 0):
            return tier_config.get("multiplier", 0), tier_config.get("label", "")

    return 0.0, "Stale"


def get_onsite_likelihood_score(sic_code: str) -> int:
    """Get on-site likelihood score for a SIC code.

    Looks up per-SIC scores derived from HLM delivery data.
    Falls back to default score for unknown SICs.
    """
    config = load_config()
    onsite = config.get("onsite_likelihood", {})
    sic_scores = onsite.get("sic_scores", {})
    return sic_scores.get(sic_code, onsite.get("default", 40))


def get_employee_scale_score(employee_count: int) -> int:
    """Get employee scale score for geography workflow."""
    config = load_config()
    scales = config.get("employee_scale", [])

    for scale in scales:
        if scale.get("min", 0) <= employee_count <= scale.get("max", 999999):
            return scale.get("score", 40)

    return 40


def get_proximity_score(distance_miles: float) -> int:
    """Get proximity score based on distance from target zip."""
    config = load_config()
    proximity = config.get("proximity", [])

    for tier in proximity:
        if distance_miles <= tier.get("max_miles", 100):
            return tier.get("score", 30)

    return 30


def get_authority_score(management_level: str) -> int:
    """Get authority score for a management level."""
    config = load_config()
    scores = config.get("authority_scores", {})
    return scores.get(management_level, scores.get("default", 40))


def get_authority_title_keywords() -> list[str]:
    """Get title keywords that indicate vending-relevant authority."""
    config = load_config()
    return config.get("authority_title_keywords", [])


def get_budget_config(workflow_type: str) -> dict:
    """Get budget configuration for a workflow type."""
    config = load_config()
    return config.get("budget", {}).get(workflow_type, {})


def get_cache_config() -> dict:
    """Get cache configuration."""
    config = load_config()
    return config.get("cache", {"ttl_days": 7, "enabled": True})


def get_automation_config(workflow_type: str) -> dict:
    """Get automation config for a workflow type ('intent')."""
    config = load_config()
    return config.get("automation", {}).get(workflow_type, {})


def get_intent_topics() -> dict:
    """Get available intent topics."""
    config = load_config()
    return config.get("intent_topics", {"primary": ["Vending"], "expansion": []})


def get_sic_codes() -> list[str]:
    """Get list of whitelisted SIC codes."""
    config = load_config()
    return config.get("hard_filters", {}).get("sic_codes", [])


# SIC code descriptions for UI display (25 target codes)
SIC_CODE_DESCRIPTIONS = {
    "3531": "Construction Machinery",
    "3599": "Industrial Machinery NEC",
    "3999": "Manufacturing Industries NEC",
    "4213": "Trucking, Except Local",
    "4225": "General Warehousing and Storage",
    "4231": "Terminal and Joint Terminal Maintenance",
    "4581": "Services to Air Transportation",
    "4731": "Freight Transportation Arrangement",
    "5511": "Motor Vehicle Dealers (New and Used)",
    "7011": "Hotels and Motels",
    "7021": "Rooming and Boarding Houses",
    "7033": "Recreational Vehicle Parks",
    "7359": "Equipment Rental and Leasing NEC",
    "7991": "Physical Fitness Facilities",
    "8051": "Skilled Nursing Care Facilities",
    "8059": "Nursing and Personal Care NEC",
    "8062": "General Medical and Surgical Hospitals",
    "8211": "Elementary and Secondary Schools",
    "8221": "Colleges and Universities",
    "8322": "Individual and Family Social Services",
    "8331": "Job Training and Vocational Rehab",
    "8361": "Residential Care",
    "9223": "Correctional Institutions",
    "9229": "Public Order and Safety NEC",
    "9711": "National Security",
}


def get_sic_codes_with_descriptions() -> list[tuple[str, str]]:
    """Get list of whitelisted SIC codes with descriptions.

    Returns:
        List of (code, description) tuples
    """
    codes = get_sic_codes()
    return [(code, SIC_CODE_DESCRIPTIONS.get(code, "Unknown")) for code in codes]


def get_employee_minimum() -> int:
    """Get minimum employee count filter."""
    config = load_config()
    return config.get("hard_filters", {}).get("employee_count", {}).get("minimum", 50)


def get_employee_maximum() -> int:
    """Get maximum employee count filter."""
    config = load_config()
    return config.get("hard_filters", {}).get("employee_count", {}).get("maximum", 5000)


def get_search_defaults() -> dict:
    """Get search defaults (single source of truth for UI and expansion)."""
    config = load_config()
    return config.get("search_defaults", {})


def get_default_accuracy() -> int:
    """Get default contact accuracy score minimum."""
    return get_search_defaults().get("accuracy_min", 95)


def get_default_management_levels() -> list[str]:
    """Get default management level filter."""
    return get_search_defaults().get("management_levels", ["Manager", "Director", "VP Level Exec"])


def get_default_phone_fields() -> list[str]:
    """Get default required phone fields."""
    return get_search_defaults().get("phone_fields", ["mobilePhone", "directPhone", "phone"])


def get_default_target_contacts() -> int:
    """Get default target contact count for search."""
    return get_search_defaults().get("target_contacts", 25)


def get_default_radius() -> float:
    """Get default search radius in miles."""
    return get_search_defaults().get("radius_miles", 15)


# ZIP code prefix to state mapping (first 3 digits)
ZIP_PREFIX_TO_STATE = {
    # Alabama (350-369)
    **{str(i): "AL" for i in range(350, 370)},
    # Alaska (995-999)
    **{str(i): "AK" for i in range(995, 1000)},
    # Arizona (850-865)
    **{str(i): "AZ" for i in range(850, 866)},
    # Arkansas (716-729)
    **{str(i): "AR" for i in range(716, 730)},
    # California (900-961)
    **{str(i): "CA" for i in range(900, 962)},
    # Colorado (800-816)
    **{str(i): "CO" for i in range(800, 817)},
    # Connecticut (060-069)
    **{f"{i:03d}": "CT" for i in range(60, 70)},
    # Delaware (197-199)
    **{str(i): "DE" for i in range(197, 200)},
    # Florida (320-349)
    **{str(i): "FL" for i in range(320, 350)},
    # Georgia (300-319, 398-399)
    **{str(i): "GA" for i in range(300, 320)},
    **{str(i): "GA" for i in range(398, 400)},
    # Hawaii (967-968)
    **{str(i): "HI" for i in range(967, 969)},
    # Idaho (832-838)
    **{str(i): "ID" for i in range(832, 839)},
    # Illinois (600-629)
    **{str(i): "IL" for i in range(600, 630)},
    # Indiana (460-479)
    **{str(i): "IN" for i in range(460, 480)},
    # Iowa (500-528)
    **{str(i): "IA" for i in range(500, 529)},
    # Kansas (660-679)
    **{str(i): "KS" for i in range(660, 680)},
    # Kentucky (400-427)
    **{str(i): "KY" for i in range(400, 428)},
    # Louisiana (700-714)
    **{str(i): "LA" for i in range(700, 715)},
    # Maine (039-049)
    **{f"{i:03d}": "ME" for i in range(39, 50)},
    # Maryland (206-219)
    **{str(i): "MD" for i in range(206, 220)},
    # Massachusetts (010-027)
    **{f"{i:03d}": "MA" for i in range(10, 28)},
    # Michigan (480-499)
    **{str(i): "MI" for i in range(480, 500)},
    # Minnesota (550-567)
    **{str(i): "MN" for i in range(550, 568)},
    # Mississippi (386-397)
    **{str(i): "MS" for i in range(386, 398)},
    # Missouri (630-658)
    **{str(i): "MO" for i in range(630, 659)},
    # Montana (590-599)
    **{str(i): "MT" for i in range(590, 600)},
    # Nebraska (680-693)
    **{str(i): "NE" for i in range(680, 694)},
    # Nevada (889-898)
    **{str(i): "NV" for i in range(889, 899)},
    # New Hampshire (030-038)
    **{f"{i:03d}": "NH" for i in range(30, 39)},
    # New Jersey (070-089)
    **{f"{i:03d}": "NJ" for i in range(70, 90)},
    # New Mexico (870-884)
    **{str(i): "NM" for i in range(870, 885)},
    # New York (100-149)
    **{str(i): "NY" for i in range(100, 150)},
    # North Carolina (270-289)
    **{str(i): "NC" for i in range(270, 290)},
    # North Dakota (580-588)
    **{str(i): "ND" for i in range(580, 589)},
    # Ohio (430-459)
    **{str(i): "OH" for i in range(430, 460)},
    # Oklahoma (730-749)
    **{str(i): "OK" for i in range(730, 750)},
    # Oregon (970-979)
    **{str(i): "OR" for i in range(970, 980)},
    # Pennsylvania (150-196)
    **{str(i): "PA" for i in range(150, 197)},
    # Rhode Island (028-029)
    **{f"{i:03d}": "RI" for i in range(28, 30)},
    # South Carolina (290-299)
    **{str(i): "SC" for i in range(290, 300)},
    # South Dakota (570-577)
    **{str(i): "SD" for i in range(570, 578)},
    # Tennessee (370-385)
    **{str(i): "TN" for i in range(370, 386)},
    # Texas (750-799)
    **{str(i): "TX" for i in range(750, 800)},
    # Utah (840-847)
    **{str(i): "UT" for i in range(840, 848)},
    # Vermont (050-059)
    **{f"{i:03d}": "VT" for i in range(50, 60)},
    # Virginia (220-246)
    **{str(i): "VA" for i in range(220, 247)},
    # Washington (980-994)
    **{str(i): "WA" for i in range(980, 995)},
    # West Virginia (247-268)
    **{str(i): "WV" for i in range(247, 269)},
    # Wisconsin (530-549)
    **{str(i): "WI" for i in range(530, 550)},
    # Wyoming (820-831)
    **{str(i): "WY" for i in range(820, 832)},
    # DC (200-205)
    **{str(i): "DC" for i in range(200, 206)},
}


def time_ago(iso_str: str | None) -> str:
    """Convert ISO timestamp to human-readable relative time string.

    Returns 'Just now', 'Xm ago', 'Xh ago', 'Xd ago', 'Never', or 'Unknown'.
    """
    if not iso_str:
        return "Never"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = now - dt
        minutes = diff.total_seconds() / 60
        if minutes < 1:
            return "Just now"
        if minutes < 60:
            return f"{int(minutes)}m ago"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)}h ago"
        days = hours / 24
        return f"{int(days)}d ago"
    except (ValueError, TypeError):
        return "Unknown"


def normalize_zip(raw) -> str | None:
    """Normalize a ZIP code to 5-digit string.

    Handles ZIP+4 (hyphen, space, no separator), leading-zero padding,
    Excel backtick/equals formatting, integer input, and whitespace.

    Returns:
        5-digit ZIP string, or None if input is empty/invalid.
    """
    if raw is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw))
    if len(digits) < 3:
        return None
    # Take first 5 digits (handles ZIP+4 variants)
    digits = digits[:5]
    # Pad with leading zeros (handles 4-digit CT/NJ/MA ZIPs)
    return digits.zfill(5)


def get_state_from_zip(zip_code: str) -> str | None:
    """Get state code from ZIP code."""
    cleaned = normalize_zip(zip_code)
    if not cleaned:
        return None
    prefix = cleaned[:3]
    return ZIP_PREFIX_TO_STATE.get(prefix)


# --- Phone Cleaning ---

def remove_phone_extension(phone: str) -> str:
    """Remove extension from phone number."""
    if not phone:
        return ""

    # Remove common extension patterns
    patterns = [
        r'\s*[xX]\s*\d+',           # x123, X 123
        r'\s*[eE][xX][tT]\.?\s*\d+', # ext123, EXT. 123
        r'\s*#\s*\d+',               # #123
    ]

    result = phone
    for pattern in patterns:
        result = re.sub(pattern, '', result)

    return result.strip()


def normalize_phone(phone: str) -> str:
    """Normalize phone number to digits only."""
    if not phone:
        return ""

    # Remove extension first
    phone = remove_phone_extension(phone)

    # Keep only digits
    digits = re.sub(r'\D', '', phone)

    # Handle country code
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]

    return digits


def format_phone(phone: str) -> str:
    """Format phone number as (XXX) XXX-XXXX."""
    digits = normalize_phone(phone)

    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

    return phone  # Return original if can't format


# --- VanillaSoft Column Mapping ---

VANILLASOFT_COLUMNS = [
    "List Source",
    "Last Name",
    "First Name",
    "Title",
    "Home",
    "Email",
    "Mobile",
    "Company",
    "Web site",
    "Business",
    "Number of Employees",
    "Primary SIC",
    "Primary Line of Business",
    "Address",
    "City",
    "State",
    "ZIP code",
    "Square Footage",
    "Contact Owner",
    "Lead Source",
    "Vending Business Name",
    "Operator Name",
    "Operator Phone #",
    "Operator Email Address",
    "Operator Zip Code",
    "Operator Website Address",
    "Best Appts Time",
    "Unavailable for appointments",
    "Team",
    "Call Priority",
    "Import Notes",
]


# Mapping from ZoomInfo API fields to VanillaSoft columns
# Field names verified against ZVDP/files/field_mapping.json
ZOOMINFO_TO_VANILLASOFT = {
    # Contact fields
    "lastName": "Last Name",
    "firstName": "First Name",
    "jobTitle": "Title",
    "email": "Email",
    "mobilePhone": "Mobile",
    "directPhone": "Business",
    # Company fields
    "companyName": "Company",
    "website": "Web site",
    "employeeCount": "Number of Employees",
    "sicCode": "Primary SIC",
    "industry": "Primary Line of Business",
    # Address fields
    "street": "Address",
    "city": "City",
    "state": "State",
    "zipCode": "ZIP code",
    # Company HQ phone → Home (per VSDP mapping)
    "companyHQPhone": "Home",
    # Fallback mappings (some APIs use different names)
    # NOTE: "phone" -> "Business" removed — it silently overwrote directPhone.
    # Fallback handled in export.py build_vanillasoft_row() instead.
    "employees": "Number of Employees",  # Fallback for employeeCount
    "zip": "ZIP code",             # Fallback for zipCode
    "address": "Address",          # Fallback for street
    # Enrich API uses different field names than Search API
    "companyWebsite": "Web site",       # Enrich returns companyWebsite, not website
    "companyPhone": "Home",             # Enrich returns companyPhone, not companyHQPhone
    "companyCity": "City",              # Enrich returns companyCity
    "companyState": "State",            # Enrich returns companyState
    "companyZipCode": "ZIP code",       # Enrich returns companyZipCode
    "companyStreet": "Address",         # Enrich returns companyStreet
}
