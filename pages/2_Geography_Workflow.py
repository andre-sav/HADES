"""
Geography Workflow - Find contacts in an operator's service territory.
Features: Autopilot vs Manual Review modes, visible API parameters, contact selection.
"""

import json
import logging

import streamlit as st

# Configure logging
logger = logging.getLogger(__name__)
import pandas as pd
from datetime import datetime

from turso_db import get_database
from zoominfo_client import (
    get_zoominfo_client,
    ContactQueryParams,
    ContactEnrichParams,
    ZoomInfoError,
    DEFAULT_ENRICH_OUTPUT_FIELDS,
)
from scoring import score_geography_leads, get_priority_label
from dedup import dedupe_leads
from cost_tracker import CostTracker
from utils import (
    get_sic_codes,
    get_sic_codes_with_descriptions,
    get_employee_minimum,
    get_employee_maximum,
    get_state_from_zip,
)
from geo import get_zips_in_radius, get_states_from_zips, get_state_counts_from_zips
from expand_search import (
    expand_search,
    build_contacts_by_company,
    EXPANSION_STEPS,
    DEFAULT_TARGET_CONTACTS,
    DEFAULT_START_RADIUS,
    DEFAULT_START_ACCURACY,
    DEFAULT_START_MANAGEMENT,
    DEFAULT_START_EMPLOYEE_MAX,
)
from ui_components import (
    inject_base_styles,
    step_indicator,
    status_badge,
    paginate_items,
    pagination_controls,
    COLORS,
)

st.set_page_config(page_title="Geography", page_icon="📍", layout="wide")


def generate_team_name(operator_name: str, operator_zip: str) -> str:
    """Generate team name from operator name and ZIP code.

    Format: "{Name} ({State})"
    Example: "Chris Carrillo (FL)" from name "Chris Carrillo" and ZIP "33542"
    """
    if not operator_name:
        return ""

    state = get_state_from_zip(operator_zip) if operator_zip else None
    if state:
        return f"{operator_name} ({state})"
    return operator_name


# Apply design system styles
inject_base_styles()


# Initialize services
@st.cache_resource
def get_services():
    db = get_database()
    return db, CostTracker(db)


try:
    db, cost_tracker = get_services()
except Exception as e:
    st.error(f"Failed to initialize: {e}")
    st.stop()


# --- Session State ---
defaults = {
    "geo_operator": None,
    "geo_results": None,
    "geo_query_params": None,
    "geo_mode": "manual",  # Default to manual for two-step workflow
    "geo_test_mode": False,  # Test mode: skip actual enrichment, use mock data
    # Step 1: Search (preview)
    "geo_preview_contacts": None,  # Preview contacts from search (no credits used)
    "geo_contacts_by_company": None,  # Grouped by company
    "geo_selected_contacts": {},  # company_id -> selected contact (preview)
    "geo_search_executed": False,
    "geo_selection_confirmed": False,
    # Step 2: Enrich (uses credits)
    "geo_enriched_contacts": None,  # Enriched contacts (credits used)
    "geo_enrichment_done": False,
    "geo_usage_logged": False,  # Prevent double-logging on refresh
    # API Request confirmation
    "geo_request_previewed": False,  # Whether user has seen the full request
    "geo_pending_search_params": None,  # Stored params awaiting confirmation
    # Target contacts expansion
    "geo_expansion_result": None,  # Stores expansion strategy results
}
for key, default in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default


# =============================================================================
# HEADER
# =============================================================================
col1, col2 = st.columns([3, 1])
with col1:
    st.title("Geography")
    st.caption("Find contacts within an operator's service territory")
with col2:
    st.markdown("")  # Add spacing to align with title
    weekly_usage = cost_tracker.get_weekly_usage_by_workflow()
    credits = weekly_usage.get("geography", 0)
    st.markdown(status_badge("info", f"{credits:,} credits"), unsafe_allow_html=True)
    st.caption("This week")

st.markdown("---")

# =============================================================================
# STEP INDICATOR
# =============================================================================
# Calculate current step based on session state
def get_current_step() -> int:
    """Determine current workflow step (1-4)."""
    if st.session_state.geo_enrichment_done:
        return 4  # Results
    if st.session_state.geo_selection_confirmed:
        return 4  # Enriching/Results
    if st.session_state.geo_contacts_by_company:
        return 3  # Review & Select
    if st.session_state.geo_operator:
        return 2  # Configure Search
    return 1  # Select Operator


current_step = get_current_step()

# Show step indicator based on mode
if st.session_state.geo_mode == "autopilot":
    step_indicator(current_step, 3, ["Select Operator", "Configure & Search", "Results"])
else:
    step_indicator(current_step, 4, ["Select Operator", "Configure Search", "Review & Select", "Results"])


# =============================================================================
# MODE SELECTOR
# =============================================================================
mode_col1, mode_col2, mode_col3 = st.columns([1, 2, 1])
with mode_col1:
    st.session_state.geo_mode = st.radio(
        "Workflow Mode",
        ["manual", "autopilot"],
        format_func=lambda x: "Manual Review" if x == "manual" else "Autopilot",
        horizontal=True,
        help="Manual: Review preview, select contacts, then enrich. Autopilot: Auto-select and enrich.",
    )

with mode_col2:
    if st.session_state.geo_mode == "autopilot":
        st.info("**Autopilot**: Search → Auto-select best per company → Enrich → Export (uses credits)", icon="🤖")
    else:
        st.info("**Manual Review**: Search (free preview) → Select contacts (1 per company) → Enrich selected (uses credits) → Export", icon="👤")

with mode_col3:
    st.session_state.geo_test_mode = st.checkbox(
        "🧪 Test Mode",
        value=st.session_state.geo_test_mode,
        help="Skip actual enrichment API calls - uses mock data. No credits consumed.",
    )
    if st.session_state.geo_test_mode:
        st.caption("⚠️ Using mock data")


# =============================================================================
# OPERATOR SELECTION
# =============================================================================
st.markdown("---")
st.subheader("1. Operator")

operator_mode = st.radio(
    "Operator",
    ["Select existing", "Enter manually"],
    horizontal=True,
    label_visibility="collapsed",
)

if operator_mode == "Select existing":
    operators = db.get_operators()

    if not operators:
        st.info("No operators saved yet. Use manual entry or add operators in the Operators page.")
        st.session_state.geo_operator = None
    else:
        operator_options = {
            f"{op['operator_name']}  ·  {op.get('vending_business_name') or 'N/A'}": op
            for op in operators
        }

        selected = st.selectbox(
            "Select operator",
            options=[""] + list(operator_options.keys()),
            format_func=lambda x: x if x else "Choose an operator...",
            label_visibility="collapsed",
        )

        if selected:
            st.session_state.geo_operator = operator_options[selected]
            op = st.session_state.geo_operator

            # Auto-generate team name if not set
            team_value = op.get('team') or ''
            if not team_value:
                team_value = generate_team_name(op.get('operator_name', ''), op.get('operator_zip', ''))
                # Store the auto-generated team back to the operator
                st.session_state.geo_operator['team'] = team_value

            # Show operator details in same format as manual entry (disabled inputs)
            col1, col2 = st.columns(2)
            with col1:
                st.text_input("Operator name", value=op.get('operator_name') or '', disabled=True)
                st.text_input("ZIP code", value=op.get('operator_zip') or '', disabled=True)
                st.text_input("Phone", value=op.get('operator_phone') or '', disabled=True)
                st.text_input("Website", value=op.get('operator_website') or '', disabled=True)
            with col2:
                st.text_input("Business name", value=op.get('vending_business_name') or '', disabled=True)
                st.text_input("Team", value=team_value, disabled=True)
                st.text_input("Email", value=op.get('operator_email') or '', disabled=True)
        else:
            st.session_state.geo_operator = None

else:
    col1, col2 = st.columns(2)
    with col1:
        manual_name = st.text_input("Operator name", placeholder="John Smith")
        manual_zip = st.text_input("ZIP code", placeholder="75201")
        manual_phone = st.text_input("Phone", placeholder="(555) 123-4567")
        manual_website = st.text_input("Website", placeholder="https://abcvending.com")

    # Auto-generate team suggestion based on name and ZIP
    auto_team = generate_team_name(manual_name, manual_zip) if manual_name else ""

    with col2:
        manual_business = st.text_input("Business name", placeholder="ABC Vending")
        manual_team = st.text_input(
            "Team",
            value=auto_team,
            placeholder="John Smith (TX)",
            help="Auto-generated from name and ZIP. Edit if needed.",
        )
        manual_email = st.text_input("Email", placeholder="john@abc.com")

    if manual_name:
        st.session_state.geo_operator = {
            "operator_name": manual_name,
            "vending_business_name": manual_business,
            "operator_phone": manual_phone,
            "operator_email": manual_email,
            "operator_zip": manual_zip,
            "operator_website": manual_website,
            "team": manual_team or auto_team,
        }
    else:
        st.session_state.geo_operator = None


# =============================================================================
# SEARCH PARAMETERS
# =============================================================================
has_operator = st.session_state.geo_operator is not None

if has_operator:
    st.markdown("---")
    st.subheader("2. Search Parameters")

    default_zip = st.session_state.geo_operator.get("operator_zip", "")

    # Auto-detect state from operator ZIP
    default_state = ""
    if default_zip:
        detected_state = get_state_from_zip(default_zip)
        if detected_state:
            default_state = detected_state

    # Location mode selector
    location_mode = st.radio(
        "Location Search Mode",
        ["radius", "manual"],
        format_func=lambda x: "Radius from ZIP (recommended)" if x == "radius" else "Manual ZIP list",
        horizontal=True,
        help="Radius: Enter center ZIP + radius. Manual: Paste specific ZIP codes.",
    )

    if location_mode == "radius":
        # Radius-based search
        col1, col2 = st.columns([2, 1])

        with col1:
            center_zip = st.text_input(
                "Center ZIP",
                value=default_zip,
                placeholder="Enter center ZIP code",
                help="All ZIP codes within the radius will be searched",
            )

        with col2:
            RADIUS_OPTIONS = {
                10.0: "10 miles",
                12.5: "12.5 miles",
                15.0: "15 miles (Recommended)",
                "custom": "Custom...",
            }
            radius_choice = st.selectbox(
                "Radius",
                options=list(RADIUS_OPTIONS.keys()),
                index=2,  # Default 15 mi (Recommended)
                format_func=lambda x: RADIUS_OPTIONS[x],
            )

        # Custom radius input
        if radius_choice == "custom":
            radius = st.number_input(
                "Custom radius (miles)",
                min_value=1.0,
                max_value=50.0,
                value=20.0,
                step=0.5,
            )
        else:
            radius = radius_choice

        # Calculate ZIPs in radius
        center_zip_clean = (center_zip or "").strip()
        is_valid_zip = center_zip_clean.isdigit() and len(center_zip_clean) == 5

        if is_valid_zip:
            calculated_zips = get_zips_in_radius(center_zip_clean, radius)
            zip_codes = [z["zip"] for z in calculated_zips]
            states = get_states_from_zips(calculated_zips)
            state_counts = get_state_counts_from_zips(calculated_zips)

            # Display ZIP count and states
            if calculated_zips:
                state_display = ", ".join(f"{s} ({state_counts[s]})" for s in states)
                st.success(f"📍 **{len(zip_codes)}** ZIP codes in radius  ·  States: {state_display}")

                # Optional: show ZIP list in expander
                with st.expander("Show ZIP codes"):
                    zip_list_display = ", ".join(zip_codes[:100])
                    if len(zip_codes) > 100:
                        zip_list_display += f"... and {len(zip_codes) - 100} more"
                    st.code(zip_list_display)
            else:
                st.warning("No ZIP codes found. Check that the center ZIP is valid.")
                zip_codes = []
                states = []
        else:
            zip_codes = []
            states = []
            calculated_zips = []

    else:
        # Manual ZIP list mode
        manual_zips = st.text_area(
            "ZIP Codes (paste from freemaptools.com or similar)",
            placeholder="94116,94122,94132,94127,94131,94121,94114,94112,94117...",
            help="Paste comma-separated ZIP codes.",
            height=100,
        )

        # Parse inputs for manual mode
        raw_zips = [z.strip() for z in manual_zips.replace("\n", ",").split(",") if z.strip()]
        zip_codes = [z for z in raw_zips if z.isdigit() and len(z) == 5]
        radius = 0  # No radius for manual ZIP list
        center_zip_clean = None  # Not applicable in manual mode
        is_valid_zip = False  # Not applicable in manual mode

        # Derive states from manual ZIPs
        if zip_codes:
            # Build ZIP dicts for state extraction
            from geo import load_zip_centroids
            centroids = load_zip_centroids()
            calculated_zips = []
            for z in zip_codes:
                if z in centroids:
                    lat, lng, state = centroids[z]
                    calculated_zips.append({"zip": z, "state": state, "lat": lat, "lng": lng, "distance_miles": 0})

            states = get_states_from_zips(calculated_zips)
            state_counts = get_state_counts_from_zips(calculated_zips)

            state_display = ", ".join(f"{s} ({state_counts[s]})" for s in states) if states else "Unknown"
            st.caption(f"{len(zip_codes)} ZIP codes entered  ·  States: {state_display}")
        else:
            states = []
            calculated_zips = []

    # Quality Filters (expandable)
    with st.expander("Quality Filters", expanded=False):
        qf_col1, qf_col2, qf_col3, qf_col4 = st.columns(4)

        with qf_col1:
            accuracy_min = st.number_input(
                "Min Accuracy Score",
                min_value=0,
                max_value=100,
                value=95,
                help="Minimum contact accuracy score (0-100)",
            )

        with qf_col2:
            location_type_options = {
                "Person AND HQ (Default)": "PersonAndHQ",
                "Person Only": "Person",
                "Person OR HQ": "PersonOrHQ",
                "HQ Only": "HQ",
            }
            location_type_display = st.selectbox(
                "Location Type",
                options=list(location_type_options.keys()),
                index=0,
                help=(
                    "**Person AND HQ** = Both contact AND company HQ must be in area (local businesses, direct authority)\n\n"
                    "**Person Only** = Contact works at a site in the area (finds branch offices of national chains)"
                ),
            )
            location_type = location_type_options[location_type_display]

            # Toggle for combined search (Person AND HQ + Person)
            include_person_only = st.checkbox(
                "Include Person-only results",
                value=False,
                help=(
                    "Run an additional search with Person-only filter and merge results. "
                    "Finds branch offices of national chains (more contacts, but some may lack local authority)."
                ),
                disabled=(location_type != "PersonAndHQ"),
            )
            # Only applicable when base is PersonAndHQ
            if location_type != "PersonAndHQ":
                include_person_only = False

        with qf_col3:
            current_only = st.checkbox(
                "Current employees only",
                value=True,
                help="Exclude past employees",
            )

        with qf_col4:
            exclude_org_exported = st.checkbox(
                "Exclude previously exported",
                value=True,
                help="Skip contacts your org has already exported",
            )

        # Required phone fields (second row)
        st.markdown("---")
        phone_col1, phone_col2 = st.columns([3, 1])

        with phone_col1:
            PHONE_FIELD_OPTIONS = {
                "mobilePhone": "Mobile Phone",
                "directPhone": "Direct Phone",
                "phone": "Phone",
            }
            required_fields = st.multiselect(
                "Required Phone Fields",
                options=list(PHONE_FIELD_OPTIONS.keys()),
                default=["mobilePhone", "directPhone", "phone"],
                format_func=lambda x: PHONE_FIELD_OPTIONS.get(x, x),
                help="Contact must have at least one of these phone types (OR logic)",
            )

        with phone_col2:
            required_fields_operator = st.radio(
                "Operator",
                options=["or", "and"],
                index=0,
                format_func=lambda x: "OR (any)" if x == "or" else "AND (all)",
                horizontal=True,
                help="OR = any field present, AND = all fields required",
            )

        # Management Level filter (third row)
        st.markdown("---")
        mgmt_col1, mgmt_col2 = st.columns([2, 2])

        with mgmt_col1:
            # Valid ZoomInfo values: Board Member, C Level Exec, VP Level Exec, Director, Manager, Non Manager
            MANAGEMENT_LEVELS = ["Manager", "Director", "VP Level Exec", "C Level Exec", "Board Member", "Non Manager"]
            management_levels = st.multiselect(
                "Management Level",
                options=MANAGEMENT_LEVELS,
                default=["Manager"],
                help="Filter by job title/role level. Manager targets facility managers and operations managers.",
            )

        with mgmt_col2:
            st.caption("💡 **Manager** targets facility managers, operations managers, and similar roles who can authorize vending services.")

    # Industry Filters
    with st.expander("Industry Filters", expanded=False):
        st.caption(f"Employees: {get_employee_minimum():,} - {get_employee_maximum():,}")

        default_sic_codes = get_sic_codes()
        sic_options = get_sic_codes_with_descriptions()
        sic_display = {f"{code} · {desc}": code for code, desc in sic_options}

        if "geo_selected_sics" not in st.session_state:
            st.session_state.geo_selected_sics = list(sic_display.keys())

        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("All", use_container_width=True, key="sic_all"):
                st.session_state.geo_selected_sics = list(sic_display.keys())
                st.rerun()
        with col2:
            if st.button("None", use_container_width=True, key="sic_none"):
                st.session_state.geo_selected_sics = []
                st.rerun()

        selected_sic_display = st.multiselect(
            "Industries",
            options=list(sic_display.keys()),
            default=st.session_state.geo_selected_sics,
            label_visibility="collapsed",
        )
        st.session_state.geo_selected_sics = selected_sic_display
        selected_sic_codes = [sic_display[d] for d in selected_sic_display]

        st.caption(f"{len(selected_sic_codes)} of {len(default_sic_codes)} industries selected")

    # Target Companies (1 contact per company = 1 lead)
    st.markdown("---")
    target_col1, target_col2 = st.columns([1, 1])

    with target_col1:
        target_contacts = st.number_input(
            "Target companies",
            min_value=5,
            max_value=100,
            value=DEFAULT_TARGET_CONTACTS,
            step=5,
            help="Number of unique companies to find (1 contact per company). System auto-expands if target not met.",
        )

    with target_col2:
        # Default based on workflow mode
        default_stop_early = st.session_state.geo_mode == "autopilot"
        stop_early = st.checkbox(
            "Stop early if target met",
            value=default_stop_early,
            help="Stop expanding once target companies reached",
        )

    st.caption(f"Starting: {DEFAULT_START_RADIUS}mi radius, {DEFAULT_START_ACCURACY} accuracy, Manager level, 50-{DEFAULT_START_EMPLOYEE_MAX:,} employees")

    # Build the full API request body for preview (showing actual format sent to API)
    full_request_body = {
        "state": states if states else [],
        "zipCode": zip_codes,
        "locationSearchType": location_type,
        "employeeRangeMin": get_employee_minimum(),
        "employeeRangeMax": get_employee_maximum(),
        "sicCodes": selected_sic_codes,
        "contactAccuracyScoreMin": accuracy_min,
        "excludePartialProfiles": True,
        "companyPastOrPresent": "present" if current_only else "pastOrPresent",
    }
    if management_levels:
        full_request_body["managementLevel"] = management_levels
    if required_fields:
        full_request_body["requiredFields"] = required_fields

    # Store pending search params
    pending_params = {
        "zip_codes": zip_codes,
        "states": states,
        "location_type": location_type,
        "include_person_only": include_person_only,
        "selected_sic_codes": selected_sic_codes,
        "current_only": current_only,
        "required_fields": required_fields,
        "required_fields_operator": required_fields_operator,
        "accuracy_min": accuracy_min,
        "exclude_org_exported": exclude_org_exported,
        "management_levels": management_levels,
        "radius": radius if location_mode == "radius" else 0,
        "center_zip": center_zip_clean if location_mode == "radius" else None,
        "location_mode": location_mode,
        "target_contacts": target_contacts,
        "stop_early": stop_early,
    }

    # Preview Request Button
    st.markdown("")
    preview_col1, preview_col2, preview_col3 = st.columns([1, 1, 2])

    with preview_col1:
        can_preview = bool(zip_codes and states and selected_sic_codes)
        if st.button("👁️ Preview Request", type="secondary", use_container_width=True, disabled=not can_preview):
            st.session_state.geo_request_previewed = True
            st.session_state.geo_pending_search_params = pending_params
            st.rerun()

    with preview_col2:
        if st.session_state.geo_preview_contacts or st.session_state.geo_request_previewed:
            if st.button("🔄 Clear / Reset", use_container_width=True):
                st.session_state.geo_preview_contacts = None
                st.session_state.geo_contacts_by_company = None
                st.session_state.geo_selected_contacts = {}
                st.session_state.geo_search_executed = False
                st.session_state.geo_selection_confirmed = False
                st.session_state.geo_enriched_contacts = None
                st.session_state.geo_enrichment_done = False
                st.session_state.geo_results = None
                st.session_state.geo_request_previewed = False
                st.session_state.geo_pending_search_params = None
                st.session_state.geo_expansion_result = None
                st.rerun()

    # --- API Request Preview (after clicking Preview) ---
    if st.session_state.geo_request_previewed and not st.session_state.geo_search_executed:
        st.markdown("---")
        st.subheader("Review API Request")

        if location_mode == "radius" and center_zip_clean:
            mode_note = f"Calculated {len(zip_codes)} ZIPs within {radius} miles of {center_zip_clean}"
        else:
            mode_note = f"{len(zip_codes)} ZIP codes (explicit list)"

        st.caption(mode_note)
        st.markdown("**POST** `https://api.zoominfo.com/search/contact`")

        # Show request with truncated ZIP list for readability
        display_request = full_request_body.copy()
        if len(zip_codes) > 10:
            display_request["zipCode"] = display_request["zipCode"][:10]
            display_request["_note"] = f"Showing 10 of {len(zip_codes)} ZIP codes"

        st.code(json.dumps(display_request, indent=2), language="json")

        if len(zip_codes) > 10:
            st.caption(f"📋 Full request includes all {len(zip_codes)} ZIP codes")

        st.info("📋 **Search is free** - no credits used. Credits are only used when enriching contacts.")

        # Confirm & Search button
        confirm_col1, confirm_col2 = st.columns([1, 3])
        with confirm_col1:
            search_clicked = st.button("✅ Confirm & Search", type="primary", use_container_width=True)
    else:
        search_clicked = False

    # --- Execute Search (after confirmation) ---
    if search_clicked:
        # Use stored params from preview
        sp = st.session_state.geo_pending_search_params
        if not sp:
            st.error("No search parameters found. Please preview the request first.")
            st.stop()

        search_zip_codes = sp["zip_codes"]
        search_states = sp["states"]
        search_location_type = sp["location_type"]
        search_include_person_only = sp.get("include_person_only", False)
        search_sic_codes = sp["selected_sic_codes"]
        search_current_only = sp["current_only"]
        search_required_fields = sp["required_fields"]
        search_required_fields_operator = sp["required_fields_operator"]
        search_accuracy_min = sp["accuracy_min"]
        search_exclude_org_exported = sp["exclude_org_exported"]
        search_management_levels = sp["management_levels"]
        search_radius = sp["radius"]
        search_center_zip = sp["center_zip"]
        search_location_mode = sp["location_mode"]

        target = sp.get("target_contacts", DEFAULT_TARGET_CONTACTS)
        stop_early_flag = sp.get("stop_early", True)

        # Create status container for real-time progress
        with st.status(f"🔍 Searching for {target} contacts...", expanded=True) as status:
            try:
                client = get_zoominfo_client()

                base_params = {
                    "radius": search_radius if search_radius else DEFAULT_START_RADIUS,
                    "accuracy_min": search_accuracy_min,
                    "management_levels": search_management_levels if search_management_levels else DEFAULT_START_MANAGEMENT,
                    "employee_max": get_employee_maximum(),
                    "location_type": search_location_type,
                    "include_person_only": search_include_person_only,
                    "current_only": search_current_only,
                    "required_fields": search_required_fields,
                    "required_fields_operator": search_required_fields_operator,
                    "exclude_org_exported": search_exclude_org_exported,
                    "sic_codes": search_sic_codes,
                    "center_zip": search_center_zip,
                }

                result = expand_search(
                    client=client,
                    base_params=base_params,
                    zip_codes=search_zip_codes,
                    states=search_states,
                    target=target,
                    stop_early=stop_early_flag,
                    status_container=status,
                )

                st.session_state.geo_expansion_result = result

                if result.get("error"):
                    status.update(label="❌ Search failed", state="error", expanded=True)
                    st.error(f"Search failed: {result['error']}")
                    st.session_state.geo_preview_contacts = None
                    st.session_state.geo_search_executed = True
                elif not result["contacts"]:
                    status.update(label="⚠️ No contacts found", state="complete", expanded=True)
                    st.warning("No contacts found matching your criteria. Try adjusting filters.")
                    st.session_state.geo_preview_contacts = None
                    st.session_state.geo_search_executed = True
                else:
                    # Update status with final result
                    # 'found' is now company count
                    companies_found = result['found']
                    contacts_found = result.get('found_contacts', len(result['contacts']))
                    if result["target_met"]:
                        status.update(
                            label=f"✅ Found {companies_found} companies (target: {target}) with {contacts_found} contacts",
                            state="complete",
                            expanded=False,
                        )
                    else:
                        status.update(
                            label=f"⚠️ Found {companies_found} of {target} target companies ({contacts_found} contacts)",
                            state="complete",
                            expanded=True,
                        )

                    st.session_state.geo_preview_contacts = result["contacts"]
                    st.session_state.geo_search_executed = True
                    st.session_state.geo_contacts_by_company = result["contacts_by_company"]

                    # Auto-select best contact per company
                    auto_selected = {}
                    for company_id, data in result["contacts_by_company"].items():
                        if data["contacts"]:
                            auto_selected[company_id] = data["contacts"][0]

                    st.session_state.geo_selected_contacts = auto_selected

                    # Store query params
                    st.session_state.geo_query_params = {
                        "zip_codes": search_zip_codes,
                        "zip_count": len(search_zip_codes),
                        "radius_miles": result["final_params"]["radius"],
                        "center_zip": search_center_zip,
                        "location_mode": sp.get("location_mode"),
                        "states": search_states,
                        "sic_codes_count": len(search_sic_codes),
                        "accuracy_min": result["final_params"]["accuracy_min"],
                        "location_type": search_location_type,
                    }

                    if st.session_state.geo_mode == "autopilot":
                        st.session_state.geo_selection_confirmed = True

                    st.rerun()

            except ZoomInfoError as e:
                status.update(label="❌ API Error", state="error", expanded=True)
                st.error(e.user_message)
            except Exception as e:
                status.update(label="❌ Search failed", state="error", expanded=True)
                st.error(f"Search failed: {str(e)}")


# =============================================================================
# MANUAL REVIEW - Contact Selection by Company (Preview - No Credits Used Yet)
# =============================================================================
if (
    st.session_state.geo_mode == "manual"
    and st.session_state.geo_contacts_by_company
    and not st.session_state.geo_selection_confirmed
):
    st.markdown("---")
    st.subheader("3. Review & Select Contacts")
    st.caption("📋 **Preview data** - no credits used yet. Select contacts to enrich.")

    contacts_by_company = st.session_state.geo_contacts_by_company
    total_contacts = sum(len(d["contacts"]) for d in contacts_by_company.values())
    total_companies = len(contacts_by_company)

    # Expansion summary
    exp_result = st.session_state.geo_expansion_result
    if exp_result:
        # 'found' is now company count, 'found_contacts' is total contacts
        found_companies = exp_result['found']
        found_contacts = exp_result.get('found_contacts', total_contacts)
        if exp_result["target_met"]:
            badge = status_badge("success", "Target met")
            st.markdown(f"{badge} **{found_companies} companies** (target: {exp_result['target']}) with {found_contacts} contacts", unsafe_allow_html=True)
        else:
            badge = status_badge("warning", f"{found_companies}/{exp_result['target']}")
            st.markdown(f"{badge} **{found_companies} of {exp_result['target']} target companies** ({found_contacts} contacts)", unsafe_allow_html=True)

        # Show expansion details
        if exp_result["steps_applied"] > 0:
            final = exp_result["final_params"]
            expansions = []
            # Display in expansion order: management, employee, accuracy, then radius (last resort)
            if final["management_levels"] != DEFAULT_START_MANAGEMENT:
                levels = "/".join(final["management_levels"])
                expansions.append(f"Management → {levels}")
            if final["employee_max"] == 0:
                expansions.append("Employee range → 50+")
            if final["accuracy_min"] < DEFAULT_START_ACCURACY:
                expansions.append(f"Accuracy → {final['accuracy_min']}")
            if final["radius"] > DEFAULT_START_RADIUS:
                expansions.append(f"Radius → {final['radius']}mi")

            if expansions:
                st.caption(f"Expansions applied: {', '.join(expansions)}")
            st.caption(f"Searches performed: {exp_result['searches_performed']}")
        else:
            st.caption("No expansions needed")
    else:
        # Fallback for old results without expansion data
        st.info(f"Found **{total_contacts}** contacts across **{total_companies}** companies")

    # Filters and pagination controls
    filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])
    with filter_col1:
        show_multi_only = st.checkbox(
            "Multiple contacts only",
            value=False,
            help="Focus on companies where you have choices",
        )
    with filter_col2:
        page_size = st.selectbox(
            "Per page",
            options=[5, 10, 20, 50],
            index=1,
            label_visibility="collapsed",
            help="Companies per page",
        )

    # Build filtered company list
    company_items = []
    for company_id, data in contacts_by_company.items():
        contacts = data["contacts"]
        if show_multi_only and len(contacts) == 1:
            continue
        company_items.append((company_id, data))

    if not company_items:
        st.info("No companies match the current filter. Uncheck the filter to see all.")
    else:
        # Paginate companies
        page_items, current_page, total_pages = paginate_items(
            company_items,
            page_size=page_size,
            page_key="geo_company_page"
        )

        # Show pagination info
        st.caption(f"Showing {len(page_items)} of {len(company_items)} companies (Page {current_page}/{total_pages})")

        # Display companies on current page
        for company_id, data in page_items:
            contacts = data["contacts"]
            company_name = data["company_name"]

            # Company card container
            with st.container():
                # Company header with contact count badge
                header_col1, header_col2 = st.columns([4, 1])
                with header_col1:
                    st.markdown(f"**{company_name}**")
                with header_col2:
                    contact_badge = status_badge("neutral", f"{len(contacts)} contact{'s' if len(contacts) > 1 else ''}")
                    st.markdown(contact_badge, unsafe_allow_html=True)

                # Build options for radio
                options = []
                for i, contact in enumerate(contacts):
                    name = f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or "Unknown"
                    title = contact.get("jobTitle", "")
                    score = contact.get("contactAccuracyScore", 0)
                    phone = contact.get("directPhone", "") or contact.get("phone", "")
                    contact_zip = contact.get("zipCode", "")

                    # Build structured label
                    label = f"{name}"
                    if title:
                        label += f" - {title}"
                    label += f" (Score: {score})"
                    if contact_zip:
                        label += f" | ZIP: {contact_zip}"
                    if phone:
                        label += f" | {phone}"

                    # Mark best pick
                    if i == 0:
                        label = "Best: " + label

                    options.append((label, contact))

                # Current selection
                current_selected = st.session_state.geo_selected_contacts.get(company_id)
                current_index = 0
                if current_selected:
                    for i, (_, contact) in enumerate(options):
                        contact_id = contact.get("id") or contact.get("personId")
                        selected_id = current_selected.get("id") or current_selected.get("personId")
                        if contact_id and contact_id == selected_id:
                            current_index = i
                            break

                # Radio selection
                selected_label = st.radio(
                    f"Select contact for {company_name}",
                    options=[opt[0] for opt in options],
                    index=current_index,
                    key=f"contact_select_{company_id}",
                    label_visibility="collapsed",
                    horizontal=False,
                )

                # Update selection
                for label, contact in options:
                    if label == selected_label:
                        st.session_state.geo_selected_contacts[company_id] = contact
                        break

                st.markdown("---")

        # Pagination controls at bottom
        if total_pages > 1:
            pagination_controls(current_page, total_pages, "geo_company_page")

    # Enrich Selected Button
    st.markdown("")
    confirm_col1, confirm_col2, confirm_col3 = st.columns([1, 1, 2])

    with confirm_col1:
        selected_count = len(st.session_state.geo_selected_contacts)
        if st.button(
            f"💎 Enrich Selected ({selected_count} contacts)",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.geo_selection_confirmed = True
            st.rerun()

    with confirm_col2:
        st.warning(f"⚡ Will use **{selected_count}** credits")


# =============================================================================
# ENRICHMENT STEP - After selection confirmed (both modes)
# =============================================================================
if st.session_state.geo_selection_confirmed and st.session_state.geo_selected_contacts and not st.session_state.geo_enrichment_done:
    st.markdown("---")

    if st.session_state.geo_mode == "manual":
        st.subheader("4. Enriching Contacts...")
    else:
        st.subheader("3. Enriching Contacts...")

    selected_contacts = list(st.session_state.geo_selected_contacts.values())
    person_ids = [c.get("personId") or c.get("id") for c in selected_contacts if c.get("personId") or c.get("id")]

    if person_ids:
        # TEST MODE: Use mock enrichment data (no API calls, no credits)
        if st.session_state.geo_test_mode:
            st.info("🧪 **Test Mode**: Using search data as mock enrichment (no credits used)")
            # Use the selected contacts directly as "enriched" data
            # Add any missing fields that enrichment would normally provide
            mock_enriched = []
            for contact in selected_contacts:
                enriched_contact = contact.copy()
                # Ensure key fields exist (mock enrichment would fill these)
                enriched_contact.setdefault("jobTitle", contact.get("jobTitle", "N/A"))
                enriched_contact.setdefault("email", contact.get("email", "test@example.com"))
                enriched_contact.setdefault("phone", contact.get("phone", "(555) 000-0000"))
                enriched_contact.setdefault("mobilePhone", contact.get("mobilePhone", ""))
                enriched_contact.setdefault("city", contact.get("city", contact.get("personCity", "")))
                enriched_contact.setdefault("state", contact.get("state", contact.get("personState", "")))
                enriched_contact["_test_mode"] = True  # Flag for test data
                mock_enriched.append(enriched_contact)

            st.session_state.geo_enriched_contacts = mock_enriched
            st.session_state.geo_enrichment_done = True
            st.rerun()
        else:
            # PRODUCTION MODE: Call actual ZoomInfo API
            with st.spinner(f"Enriching {len(person_ids)} contacts... (using credits)"):
                try:
                    client = get_zoominfo_client()
                    enriched = client.enrich_contacts_batch(
                        person_ids=person_ids,
                        output_fields=DEFAULT_ENRICH_OUTPUT_FIELDS,
                    )
                    st.session_state.geo_enriched_contacts = enriched
                    st.session_state.geo_enrichment_done = True
                    st.rerun()
                except ZoomInfoError as e:
                    st.error(f"Enrichment failed: {e.user_message}")
                except Exception as e:
                    st.error(f"Enrichment failed: {str(e)}")
    else:
        st.error("No valid person IDs found in selected contacts")


# =============================================================================
# FINAL RESULTS - After enrichment complete (both modes)
# =============================================================================
if st.session_state.geo_enrichment_done and st.session_state.geo_enriched_contacts:
    st.markdown("---")

    # Test mode banner
    if st.session_state.geo_test_mode:
        st.warning("🧪 **TEST MODE** - Data shown is from search preview, not actual enrichment. No credits were used.", icon="⚠️")

    if st.session_state.geo_mode == "manual":
        st.subheader("4. Enriched Contacts")
    else:
        st.subheader("3. Results")
        st.caption("Auto-selected and enriched highest-scored contact per company")

    enriched_contacts = st.session_state.geo_enriched_contacts

    # Score the enriched contacts
    scored = score_geography_leads(
        enriched_contacts,
        target_zip=st.session_state.geo_query_params.get("zip_codes", [""])[0],
    )

    # Add metadata
    for lead in scored:
        zip_codes = st.session_state.geo_query_params.get("zip_codes", [])
        radius = st.session_state.geo_query_params.get("radius_miles", 0)
        lead["_lead_source"] = f"ZoomInfo Contact · {zip_codes[0] if zip_codes else ''} · {radius}mi"
        lead["_priority"] = get_priority_label(lead.get("_score", 0))

    st.session_state.geo_results = scored

    # Log usage (credits used for enrichment) - skip in test mode
    if not st.session_state.get("geo_usage_logged"):
        if st.session_state.geo_test_mode:
            st.caption("🧪 Test mode: Usage not logged")
        else:
            cost_tracker.log_usage(
                workflow_type="geography",
                query_params=st.session_state.geo_query_params,
                credits_used=len(enriched_contacts),
                leads_returned=len(enriched_contacts),
            )
            db.log_query(
                workflow_type="geography",
                query_params=st.session_state.geo_query_params,
                leads_returned=len(enriched_contacts),
            )
        st.session_state.geo_usage_logged = True

    # Results summary
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        st.metric("Contacts Enriched", len(enriched_contacts))

    with col2:
        preview_count = len(st.session_state.geo_preview_contacts or [])
        st.metric("Preview Found", preview_count)

    with col3:
        companies = len(st.session_state.geo_contacts_by_company or {})
        st.metric("Companies", companies)

    # Results table
    display_data = []
    for lead in scored:
        display_data.append({
            "Name": f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip(),
            "Title": lead.get("jobTitle", ""),
            "Company": lead.get("companyName", "") or lead.get("company", {}).get("name", ""),
            "City": lead.get("city", "") or lead.get("personCity", ""),
            "State": lead.get("state", "") or lead.get("personState", ""),
            "Score": lead.get("_score", 0),
            "Accuracy": lead.get("contactAccuracyScore", 0),
            "Priority": lead.get("_priority", ""),
            "Phone": lead.get("directPhone", "") or lead.get("phone", ""),
            "Email": lead.get("email", ""),
        })

    df = pd.DataFrame(display_data)

    # Filters
    filter_col1, filter_col2 = st.columns([1, 1])

    with filter_col1:
        priorities = ["High", "Medium", "Low", "Very Low"]
        priority_filter = st.multiselect(
            "Priority",
            priorities,
            default=["High", "Medium", "Low"],
            label_visibility="collapsed",
        )

    with filter_col2:
        if not df.empty:
            states = sorted(df["State"].dropna().unique().tolist())
            if len(states) > 1:
                state_filter = st.multiselect("State", states, default=states, label_visibility="collapsed")
            else:
                state_filter = states
        else:
            state_filter = []

    # Apply filters
    if not df.empty:
        filtered_df = df[
            df["Priority"].isin(priority_filter) &
            df["State"].isin(state_filter)
        ]
    else:
        filtered_df = df

    # Display table
    st.dataframe(
        filtered_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Title": st.column_config.TextColumn("Title", width="medium"),
            "Company": st.column_config.TextColumn("Company", width="large"),
            "City": st.column_config.TextColumn("City", width="small"),
            "State": st.column_config.TextColumn("State", width="small"),
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width="small"),
            "Accuracy": st.column_config.NumberColumn("Accuracy", width="small"),
            "Priority": st.column_config.TextColumn("Priority", width="small"),
            "Phone": st.column_config.TextColumn("Phone", width="medium"),
            "Email": st.column_config.TextColumn("Email", width="medium"),
        },
    )

    # Export section
    st.markdown("---")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        if st.session_state.geo_operator:
            op = st.session_state.geo_operator
            st.caption(f"Export for: **{op.get('operator_name')}** · {op.get('vending_business_name') or 'N/A'}")

    with col2:
        csv = filtered_df.to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            data=csv,
            file_name=f"geo_contacts_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col3:
        st.page_link("pages/4_CSV_Export.py", label="Full Export", icon="📤", use_container_width=True)

    # Store for export page
    if len(filtered_df) > 0:
        filtered_indices = filtered_df.index.tolist()
        st.session_state.geo_export_leads = [scored[i] for i in filtered_indices]

    # Option to go back and revise (Manual mode)
    if st.session_state.geo_mode == "manual":
        st.markdown("---")
        if st.button("← Back to Contact Selection"):
            st.session_state.geo_selection_confirmed = False
            st.session_state.geo_enrichment_done = False
            st.session_state.geo_enriched_contacts = None
            st.session_state.geo_usage_logged = False
            st.rerun()
