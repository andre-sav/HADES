"""
Geography Workflow - Find contacts in an operator's service territory.
Features: Autopilot vs Manual Review modes, visible API parameters, contact selection.
"""

import hashlib
import json
import logging
import threading

import streamlit as st
import streamlit_shadcn_ui as ui

# Configure logging
logger = logging.getLogger(__name__)
import pandas as pd
from datetime import datetime


def compute_params_hash(params: dict) -> str:
    """Compute a hash of search parameters for stale detection."""
    # Sort keys for consistent hashing
    normalized = json.dumps(params, sort_keys=True, default=str)
    return hashlib.md5(normalized.encode()).hexdigest()[:12]

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
from export_dedup import apply_export_dedup
from cost_tracker import CostTracker
from utils import (
    get_sic_codes,
    get_sic_codes_with_descriptions,
    get_employee_minimum,
    get_employee_maximum,
    get_state_from_zip,
)
from geo import get_zips_in_radius, get_states_from_zips, get_state_counts_from_zips, load_zip_centroids, haversine_distance
from expand_search import (
    expand_search,
    build_contacts_by_company,
    SearchJob,
    EXPANSION_STEPS,
    DEFAULT_TARGET_CONTACTS,
    DEFAULT_START_RADIUS,
    DEFAULT_START_ACCURACY,
    DEFAULT_START_MANAGEMENT,
    DEFAULT_START_EMPLOYEE_MAX,
)
from ui_components import (
    inject_base_styles,
    page_header,
    step_indicator,
    status_badge,
    metric_card,
    labeled_divider,
    parameter_group,
    query_summary_bar,
    export_quality_warnings,
    review_controls_bar,
    score_breakdown,
    paginate_items,
    pagination_controls,
    workflow_run_state,
    action_bar,
    workflow_summary_strip,
    last_run_indicator,
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
    "geo_mode": "autopilot",  # Match Intent workflow default
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
    # Export tracking
    "geo_exported": False,
    # Cross-session export dedup
    "geo_include_exported": False,
    "geo_dedup_result": None,
    # Filter persistence (Phase 1 UX improvement)
    "geo_last_filters": {
        "radius": 15.0,
        "accuracy_min": 95,
        "location_type": "PersonAndHQ",
        "current_only": True,
        "management_levels": ["Manager", "Director", "VP Level Exec"],
        "target_contacts": 25,
        "stop_early": True,
    },
    # Query state tracking (Phase 2 UX - stale detection)
    "geo_params_hash": None,  # Hash of last search params
    "geo_last_search_params": {},  # Full params for comparison
    # Review controls (Phase 3 UX)
    "geo_review_sort": "score",  # score, company_name, contact_count
    "geo_review_filter": "all",  # all, multi_only, has_mobile, high_accuracy
    # Background search (stop button support)
    "geo_search_job": None,  # SearchJob instance while thread running
    "_geo_progress_log": None,  # Shared list for real-time progress from thread
}
for key, default in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default


# =============================================================================
# HEADER
# =============================================================================
weekly_usage = cost_tracker.get_weekly_usage_by_workflow()
credits = weekly_usage.get("geography", 0)
page_header(
    title="Geography",
    caption="Find contacts within an operator's service territory",
    right_content=(status_badge("info", f"{credits:,} credits"), "This week"),
)

# =============================================================================
# LAST RUN INDICATOR
# =============================================================================
_last_geo = db.get_last_query("geography")
last_run_indicator(_last_geo)


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
    _GEO_MODE_MAP = {"Autopilot": "autopilot", "Manual Review": "manual"}
    _GEO_MODE_REVERSE = {v: k for k, v in _GEO_MODE_MAP.items()}
    _geo_mode_tab = ui.tabs(
        options=list(_GEO_MODE_MAP.keys()),
        default_value=_GEO_MODE_REVERSE.get(st.session_state.geo_mode, "Autopilot"),
        key="geo_mode_tabs",
    )
    st.session_state.geo_mode = _GEO_MODE_MAP.get(_geo_mode_tab, st.session_state.geo_mode)

with mode_col2:
    if st.session_state.geo_mode == "autopilot":
        st.info("**Autopilot**: Search → Auto-select best per company → Enrich → Export (uses credits)", icon="🤖")
    else:
        st.info("**Manual Review**: Search (free preview) → Select contacts (1 per company) → Enrich selected (uses credits) → Export", icon="👤")

with mode_col3:
    _geo_test_sw = ui.switch(default_checked=st.session_state.geo_test_mode, label="Test Mode", key="geo_test_mode_switch")
    st.session_state.geo_test_mode = bool(_geo_test_sw) if _geo_test_sw is not None else st.session_state.geo_test_mode
    if st.session_state.geo_test_mode:
        st.caption("⚠️ Using mock data")


# =============================================================================
# ACTION BAR + SUMMARY STRIP (only shown after search)
# =============================================================================
_run_state = workflow_run_state("geo")

if _run_state != "idle":
    _ab_primary = None
    _ab_primary_key = None
    _ab_metrics = []

    if _run_state == "enriched" and st.session_state.geo_results:
        _ab_metrics = [{"label": "Leads", "value": len(st.session_state.geo_results)}]
        _ab_primary = "Export CSV"
        _ab_primary_key = "ab_geo_export"
    elif _run_state == "contacts_found":
        cbc = st.session_state.geo_contacts_by_company or {}
        _ab_metrics = [{"label": "Companies", "value": len(cbc)}]
    elif _run_state == "searched" and st.session_state.geo_preview_contacts:
        _ab_metrics = [{"label": "Contacts", "value": len(st.session_state.geo_preview_contacts)}]
    elif _run_state == "exported":
        _ab_metrics = [{"label": "Status", "value": "Exported"}]

    _ab_primary_clicked, _ = action_bar(
        _run_state,
        primary_label=_ab_primary,
        primary_key=_ab_primary_key,
        metrics=_ab_metrics,
    )

    if _ab_primary_clicked and _run_state == "enriched":
        st.switch_page("pages/4_CSV_Export.py")

    # Summary strip
    _strip_items = []
    _strip_items.append({"label": "Mode", "value": "Autopilot" if st.session_state.geo_mode == "autopilot" else "Manual"})
    if st.session_state.geo_operator:
        _strip_items.append({"label": "Operator", "value": st.session_state.geo_operator.get("operator_name", "")})
    if st.session_state.geo_contacts_by_company:
        _strip_items.append({"label": "Companies", "value": len(st.session_state.geo_contacts_by_company)})
    if st.session_state.geo_preview_contacts:
        _strip_items.append({"label": "Contacts", "value": len(st.session_state.geo_preview_contacts)})
    _strip_items.append({"label": "Credits", "value": credits})

    if len(_strip_items) > 1:
        workflow_summary_strip(_strip_items)


# =============================================================================
# OPERATOR SELECTION
# =============================================================================
labeled_divider("Step 1: Select Operator")

_OP_MODE_MAP = {"Existing Operator": "Select existing", "Enter Manually": "Enter manually"}
_op_mode_tab = ui.tabs(
    options=list(_OP_MODE_MAP.keys()),
    default_value="Existing Operator",
    key="geo_operator_mode_tabs",
)
operator_mode = _OP_MODE_MAP.get(_op_mode_tab, "Select existing")

if operator_mode == "Select existing":
    operators = db.get_operators()

    if not operators:
        st.info("No operators saved yet. Use manual entry or add operators in the Operators page.")
        st.session_state.geo_operator = None
    else:
        st.caption(f"{len(operators):,} operators available — select one to search their service territory")
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
    labeled_divider("Step 2: Configure Search")

    default_zip = st.session_state.geo_operator.get("operator_zip", "")

    # Auto-detect state from operator ZIP
    default_state = ""
    if default_zip:
        detected_state = get_state_from_zip(default_zip)
        if detected_state:
            default_state = detected_state

    # Location mode selector
    _LOC_MODE_MAP = {"Radius Search": "radius", "Manual ZIP List": "manual"}
    _LOC_MODE_REVERSE = {v: k for k, v in _LOC_MODE_MAP.items()}
    _loc_mode_tab = ui.tabs(
        options=list(_LOC_MODE_MAP.keys()),
        default_value="Radius Search",
        key="geo_location_mode_tabs",
    )
    location_mode = _LOC_MODE_MAP.get(_loc_mode_tab, "radius")

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
            # Get persisted radius, default to 15.0 if not in options
            last_radius = st.session_state.geo_last_filters.get("radius", 15.0)
            radius_options_list = list(RADIUS_OPTIONS.keys())
            try:
                default_idx = radius_options_list.index(last_radius) if last_radius in radius_options_list else 2
            except ValueError:
                default_idx = 2
            radius_choice = st.selectbox(
                "Radius",
                options=radius_options_list,
                index=default_idx,
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
    last_filters = st.session_state.geo_last_filters
    with st.expander("Quality Filters", expanded=False):
        qf_col1, qf_col2, qf_col3, qf_col4 = st.columns(4)

        with qf_col1:
            accuracy_min = st.number_input(
                "Min Accuracy Score",
                min_value=0,
                max_value=100,
                value=last_filters.get("accuracy_min", 95),
                help="Minimum contact accuracy score (0-100)",
            )

        with qf_col2:
            location_type_options = {
                "Person AND HQ (Default)": "PersonAndHQ",
                "Person Only": "Person",
                "Person OR HQ": "PersonOrHQ",
                "HQ Only": "HQ",
            }
            # Find index for persisted location type
            last_loc_type = last_filters.get("location_type", "PersonAndHQ")
            loc_type_values = list(location_type_options.values())
            loc_type_idx = loc_type_values.index(last_loc_type) if last_loc_type in loc_type_values else 0
            location_type_display = st.selectbox(
                "Location Type",
                options=list(location_type_options.keys()),
                index=loc_type_idx,
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
            _cur_emp_sw = ui.switch(default_checked=last_filters.get("current_only", True), label="Current Employees Only", key="geo_current_emp_switch")
            current_only = bool(_cur_emp_sw) if _cur_emp_sw is not None else last_filters.get("current_only", True)

        with qf_col4:
            st.caption("Previously exported companies are filtered in search results (last 180 days).")

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
            _PHONE_OP_MAP = {"Any Field (OR)": "or", "All Fields (AND)": "and"}
            _phone_op_tab = ui.tabs(
                options=list(_PHONE_OP_MAP.keys()),
                default_value="Any Field (OR)",
                key="geo_phone_operator_tabs",
            )
            required_fields_operator = _PHONE_OP_MAP.get(_phone_op_tab, "or")

        # Management Level filter (third row)
        st.markdown("---")
        mgmt_col1, mgmt_col2 = st.columns([2, 2])

        with mgmt_col1:
            # Valid ZoomInfo values: Board Member, C Level Exec, VP Level Exec, Director, Manager, Non Manager
            MANAGEMENT_LEVELS = ["Manager", "Director", "VP Level Exec", "C Level Exec", "Board Member", "Non Manager"]
            management_levels = st.multiselect(
                "Management Level",
                options=MANAGEMENT_LEVELS,
                default=last_filters.get("management_levels", ["Manager", "Director", "VP Level Exec"]),
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
            if ui.button(text="All", variant="secondary", key="sic_all_btn"):
                st.session_state.geo_selected_sics = list(sic_display.keys())
                st.rerun()
        with col2:
            if ui.button(text="None", variant="secondary", key="sic_none_btn"):
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
            value=last_filters.get("target_contacts", DEFAULT_TARGET_CONTACTS),
            step=5,
            help="Number of unique companies to find (1 contact per company). System auto-expands if target not met.",
        )

    with target_col2:
        # Default based on workflow mode
        default_stop_early = st.session_state.geo_mode == "autopilot"
        stop_early = st.checkbox(
            "Stop when target reached (faster)",
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
        "management_levels": management_levels,
        "radius": radius if location_mode == "radius" else 0,
        "center_zip": center_zip_clean if location_mode == "radius" else None,
        "location_mode": location_mode,
        "target_contacts": target_contacts,
        "stop_early": stop_early,
    }

    # Persist filter values for next session (Phase 1 UX)
    st.session_state.geo_last_filters = {
        "radius": radius if location_mode == "radius" else 15.0,
        "accuracy_min": accuracy_min,
        "location_type": location_type,
        "current_only": current_only,
        "management_levels": management_levels,
        "target_contacts": target_contacts,
        "stop_early": stop_early,
    }

    # Check if we can preview (need ZIP codes, states, and SIC codes)
    can_preview = bool(zip_codes and states and selected_sic_codes)

    # Compute params hash for stale detection (Phase 2 UX)
    current_params_hash = compute_params_hash(pending_params)

    # Determine query state
    if st.session_state.geo_search_executed:
        # Check if params changed since last search
        last_hash = st.session_state.geo_params_hash
        if last_hash and last_hash != current_params_hash:
            query_state = "stale"
        else:
            query_state = "executed"
    else:
        query_state = "ready"

    # Display query summary bar
    summary_params = {
        "zip_count": len(zip_codes),
        "radius": radius if location_mode == "radius" else None,
        "states": states,
        "accuracy_min": accuracy_min,
        "target_contacts": target_contacts,
    }

    if query_state == "executed":
        result_count = len(st.session_state.geo_contacts_by_company or {})
        query_summary_bar(summary_params, query_state, result_count=result_count)
    elif query_state == "stale":
        query_summary_bar(summary_params, query_state)
        st.caption("⚠️ Parameters changed since last search. Click Preview to search with new settings.")
    else:
        query_summary_bar(summary_params, query_state)

    # Preview Request Button
    st.markdown("")
    preview_col1, preview_col2, preview_col3 = st.columns([1, 1, 2])

    with preview_col1:
        if st.button("👁️ Preview Request", type="secondary", use_container_width=True, disabled=not can_preview):
            st.session_state.geo_request_previewed = True
            st.session_state.geo_pending_search_params = pending_params
            st.rerun()

    with preview_col2:
        if st.session_state.geo_preview_contacts or st.session_state.geo_request_previewed:
            if ui.button(text="Clear / Reset", variant="destructive", key="geo_reset_btn"):
                # Cancel any running search thread
                existing_job = st.session_state.get("geo_search_job")
                if existing_job and not existing_job.done.is_set():
                    existing_job.cancel.set()
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
                st.session_state.geo_search_job = None
                st.session_state._geo_progress_log = None
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
        search_management_levels = sp["management_levels"]
        search_radius = sp["radius"]
        search_center_zip = sp["center_zip"]
        search_location_mode = sp["location_mode"]

        target = sp.get("target_contacts", DEFAULT_TARGET_CONTACTS)
        stop_early_flag = sp.get("stop_early", True)

        # Cancel any existing search job before starting a new one
        existing_job = st.session_state.get("geo_search_job")
        if existing_job and not existing_job.done.is_set():
            existing_job.cancel.set()

        # Build params and client in main thread (thread-safe: main thread idles during search)
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
            "sic_codes": search_sic_codes,
            "center_zip": search_center_zip,
        }

        # Launch search in background thread
        job = SearchJob()
        progress_log = []  # Shared list — thread appends, fragment reads

        def _run_geo_search():
            try:
                result = expand_search(
                    client=client,
                    base_params=base_params,
                    zip_codes=search_zip_codes,
                    states=search_states,
                    target=target,
                    stop_early=stop_early_flag,
                    status_container=None,
                    cancelled_fn=job.cancel.is_set,
                    shared_log=progress_log,
                )
                job.result = result
            except Exception as e:
                job.error = str(e)
            job.done.set()

        job.thread = threading.Thread(target=_run_geo_search, daemon=True)
        job.thread.start()

        st.session_state.geo_search_job = job
        st.session_state._geo_progress_log = progress_log
        st.rerun()


    # -------------------------------------------------------------------------
    # Helper: store geo search results into session state
    # -------------------------------------------------------------------------
    def _store_geo_results(result: dict, sp: dict):
        """Process expand_search result and populate session state."""
        st.session_state.geo_expansion_result = result

        if result.get("error"):
            st.error(f"Search failed: {result['error']}")
            st.session_state.geo_preview_contacts = None
            st.session_state.geo_search_executed = True
        elif not result["contacts"]:
            st.warning("No contacts found matching your criteria. Try adjusting filters.")
            st.session_state.geo_preview_contacts = None
            st.session_state.geo_search_executed = True
        else:
            if result.get("stopped"):
                st.warning(f"Search stopped — showing {result['found']} companies ({result.get('found_contacts', 0)} contacts) found so far.")

            st.session_state.geo_preview_contacts = result["contacts"]
            st.session_state.geo_search_executed = True

            # Cross-session export dedup: filter previously exported companies
            include_exported = st.session_state.get("geo_include_exported", False)
            dedup_result = apply_export_dedup(
                result["contacts"], db, days_back=180, include_exported=include_exported,
            )
            st.session_state.geo_dedup_result = dedup_result

            # Rebuild contacts_by_company from filtered contacts
            if dedup_result["filtered_count"] > 0 and not include_exported:
                filtered_contacts = dedup_result["contacts"]
                contacts_by_company = build_contacts_by_company(filtered_contacts)
            else:
                contacts_by_company = result["contacts_by_company"]

            st.session_state.geo_contacts_by_company = contacts_by_company

            # Auto-select best contact per company
            auto_selected = {}
            for company_id, data in contacts_by_company.items():
                if data["contacts"]:
                    auto_selected[company_id] = data["contacts"][0]
            st.session_state.geo_selected_contacts = auto_selected

            # Store query params
            st.session_state.geo_query_params = {
                "zip_codes": sp["zip_codes"],
                "zip_count": len(sp["zip_codes"]),
                "radius_miles": result["final_params"]["radius"],
                "center_zip": sp.get("center_zip"),
                "location_mode": sp.get("location_mode"),
                "states": sp["states"],
                "sic_codes_count": len(sp.get("selected_sic_codes", [])),
                "accuracy_min": result["final_params"]["accuracy_min"],
                "location_type": sp.get("location_type"),
            }

            # Store params hash for stale detection
            st.session_state.geo_params_hash = compute_params_hash(sp)
            st.session_state.geo_last_search_params = sp

            if st.session_state.geo_mode == "autopilot":
                st.session_state.geo_selection_confirmed = True


    # -------------------------------------------------------------------------
    # Fragment poller: shows progress + stop button while search runs
    # -------------------------------------------------------------------------
    geo_job = st.session_state.get("geo_search_job")
    if geo_job is not None:
        geo_active = not geo_job.done.is_set()

        @st.fragment(run_every=0.5 if geo_active else None)
        def _geo_search_monitor():
            job = st.session_state.get("geo_search_job")
            if job is None:
                return

            log = st.session_state.get("_geo_progress_log") or []

            if job.done.is_set():
                # Thread finished — store results and trigger full page rerun
                sp = st.session_state.get("geo_pending_search_params") or {}
                if job.error:
                    st.error(f"Search failed: {job.error}")
                elif job.result:
                    _store_geo_results(job.result, sp)
                # Clean up job state
                st.session_state.geo_search_job = None
                st.session_state._geo_progress_log = None
                st.rerun()
                return

            # Show progress while running
            with st.container(border=True):
                if log:
                    for msg in log:
                        st.markdown(f"<small>{msg}</small>", unsafe_allow_html=True)
                else:
                    st.caption("Starting search...")

            # Stop button
            if st.button("Stop Search", type="secondary", key="geo_stop_btn"):
                job.cancel.set()
                st.toast("Stopping after current API call...")

        _geo_search_monitor()


# =============================================================================
# MANUAL REVIEW - Contact Selection by Company (Preview - No Credits Used Yet)
# =============================================================================
if (
    st.session_state.geo_mode == "manual"
    and st.session_state.geo_contacts_by_company
    and not st.session_state.geo_selection_confirmed
):
    labeled_divider("Step 3: Review & Select")
    st.caption("📋 **Preview data** - no credits used yet. Select contacts to enrich.")

    # Cross-session export dedup banner
    _geo_dedup = st.session_state.get("geo_dedup_result")
    if _geo_dedup and _geo_dedup["filtered_count"] > 0:
        _dedup_col1, _dedup_col2 = st.columns([3, 1])
        with _dedup_col1:
            if st.session_state.get("geo_include_exported"):
                st.info(f"Showing all results — {_geo_dedup['filtered_count']} previously exported companies marked (last {_geo_dedup['days_back']} days)")
            else:
                st.info(f"Filtered {_geo_dedup['filtered_count']} previously exported companies (last {_geo_dedup['days_back']} days)")
        with _dedup_col2:
            _prev_val = st.session_state.get("geo_include_exported", False)
            _new_val = st.checkbox(
                "Include previously exported",
                value=_prev_val,
                key="geo_include_exported_cb",
            )
            if _new_val != _prev_val:
                st.session_state.geo_include_exported = _new_val
                # Re-store results with new include_exported setting
                _exp_result = st.session_state.get("geo_expansion_result")
                _sp = st.session_state.get("geo_pending_search_params") or {}
                if _exp_result:
                    _store_geo_results(_exp_result, _sp)
                st.rerun()

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

    # Review controls bar (Phase 3 UX) - Sort and filter options
    sort_col, filter_col, page_col = st.columns([1, 1, 1])

    with sort_col:
        sort_options = {
            "score": "Best score",
            "company_name": "Company A-Z",
            "contact_count": "Most choices",
        }
        sort_value = st.selectbox(
            "Sort by",
            options=list(sort_options.keys()),
            format_func=lambda x: sort_options[x],
            key="geo_review_sort",
            label_visibility="collapsed",
        )

    with filter_col:
        filter_options = {
            "all": "All companies",
            "multi_only": "Multiple contacts",
            "has_mobile": "Has mobile phone",
            "high_accuracy": "95+ accuracy",
        }
        filter_value = st.selectbox(
            "Filter",
            options=list(filter_options.keys()),
            format_func=lambda x: filter_options[x],
            key="geo_review_filter",
            label_visibility="collapsed",
        )

    with page_col:
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

        # Apply filters
        if filter_value == "multi_only" and len(contacts) == 1:
            continue
        if filter_value == "has_mobile":
            # Check if any contact in company has mobile
            if not any(c.get("mobilePhone") for c in contacts):
                continue
        if filter_value == "high_accuracy":
            # Check if best contact has 95+ accuracy
            if contacts and (contacts[0].get("contactAccuracyScore") or 0) < 95:
                continue

        company_items.append((company_id, data))

    # Apply sorting
    if sort_value == "company_name":
        company_items.sort(key=lambda x: x[1]["company_name"].lower())
    elif sort_value == "contact_count":
        company_items.sort(key=lambda x: len(x[1]["contacts"]), reverse=True)
    # score is default (already sorted by best contact score)

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
                    # Show score breakdown for best contact (Phase 3 UX)
                    if contacts:
                        best_contact = contacts[0]
                        breakdown = score_breakdown(best_contact)
                        st.markdown(f"<small>{breakdown}</small>", unsafe_allow_html=True)
                        # Company context line: city/state, website, phone
                        ctx_parts = []
                        city = best_contact.get("companyCity", "")
                        state = best_contact.get("companyState", "")
                        if city and state:
                            ctx_parts.append(f"{city}, {state}")
                        elif city or state:
                            ctx_parts.append(city or state)
                        website = best_contact.get("companyWebsite", "")
                        if website:
                            # Strip protocol for cleaner display
                            display_url = website.replace("https://", "").replace("http://", "").rstrip("/")
                            ctx_parts.append(display_url)
                        co_phone = best_contact.get("companyPhone", "")
                        if co_phone:
                            ctx_parts.append(co_phone)
                        if ctx_parts:
                            st.markdown(f"<small style='color:#888'>{' · '.join(ctx_parts)}</small>", unsafe_allow_html=True)
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
                    location_type = contact.get("_location_type", "")

                    mgmt_level = contact.get("managementLevel", "")
                    email = contact.get("email", "")

                    # Build structured label
                    label = f"{name}"
                    if title:
                        label += f" - {title}"
                    if mgmt_level and mgmt_level.lower() not in (title or "").lower():
                        label += f" [{mgmt_level}]"
                    label += f" (Score: {score})"
                    if email:
                        label += f" | {email}"
                    if contact_zip:
                        label += f" | ZIP: {contact_zip}"
                    if phone:
                        label += f" | {phone}"
                    # Show location type demarcation when combined search is enabled
                    if location_type:
                        type_label = "HQ+Person" if location_type == "PersonAndHQ" else "Person-only"
                        label += f" | [{type_label}]"

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

    # Bulk selection actions (Phase 3 UX)
    st.markdown("")
    bulk_col1, bulk_col2, bulk_col3 = st.columns([1, 1, 2])

    with bulk_col1:
        if ui.button(text="Select all best", variant="secondary", key="geo_select_all_btn"):
            # Select best (first) contact for each company
            for company_id, data in contacts_by_company.items():
                if data["contacts"]:
                    st.session_state.geo_selected_contacts[company_id] = data["contacts"][0]
            st.rerun()

    with bulk_col2:
        if ui.button(text="Clear selections", variant="destructive", key="geo_clear_sel_btn"):
            st.session_state.geo_selected_contacts = {}
            st.rerun()

    # Enrich confirmation dialog
    @st.dialog("Confirm Enrichment")
    def confirm_geo_enrich(count):
        st.write(f"This will enrich **{count}** contacts.")
        st.write(f"**{count}** credits will be consumed.")
        st.caption("Geography workflow has no weekly cap.")
        st.markdown("")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Confirm", type="primary", use_container_width=True):
                st.session_state.geo_selection_confirmed = True
                st.rerun()
        with col_no:
            if st.button("Cancel", use_container_width=True):
                st.rerun()

    # Enrich Selected Button
    st.markdown("")
    confirm_col1, confirm_col2, confirm_col3 = st.columns([1, 1, 2])

    with confirm_col1:
        selected_count = len(st.session_state.geo_selected_contacts)
        if st.session_state.geo_test_mode:
            # Test mode: skip dialog
            if ui.button(text=f"Enrich Selected ({selected_count} contacts)", variant="default", key="geo_enrich_test_btn"):
                st.session_state.geo_selection_confirmed = True
                st.rerun()
        else:
            if ui.button(text=f"Enrich Selected ({selected_count} contacts)", variant="default", key="geo_enrich_btn"):
                confirm_geo_enrich(selected_count)

    with confirm_col2:
        if st.session_state.geo_test_mode:
            st.caption("🧪 Test mode: no credits used")


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
    # Test mode banner
    if st.session_state.geo_test_mode:
        st.warning("🧪 **TEST MODE** - Data shown is from search preview, not actual enrichment. No credits were used.", icon="⚠️")

    if st.session_state.geo_mode == "manual":
        labeled_divider("Step 4: Results")
    else:
        labeled_divider("Step 3: Results")
        st.caption("Auto-selected and enriched highest-scored contact per company")

    # Cross-session export dedup banner (Results section — shown for both modes)
    _geo_dedup_r = st.session_state.get("geo_dedup_result")
    if _geo_dedup_r and _geo_dedup_r["filtered_count"] > 0:
        if st.session_state.get("geo_include_exported"):
            st.caption(f"ℹ️ {_geo_dedup_r['filtered_count']} previously exported companies included (override active)")
        else:
            st.caption(f"ℹ️ {_geo_dedup_r['filtered_count']} previously exported companies filtered (last {_geo_dedup_r['days_back']} days)")

    enriched_contacts = st.session_state.geo_enriched_contacts

    # Merge pre-enrichment metadata (location_type) and compute distance
    # Enrichment replaces contact objects entirely, losing computed fields
    pre_enrichment = {}
    for company_id, contact in st.session_state.geo_selected_contacts.items():
        pid = str(contact.get("personId") or contact.get("id") or "")
        if pid:
            pre_enrichment[pid] = {
                "_location_type": contact.get("_location_type", ""),
                "personZip": contact.get("zipCode") or contact.get("personZip") or contact.get("companyZipCode", ""),
            }

    center_zip = st.session_state.geo_query_params.get("center_zip") or (
        st.session_state.geo_query_params.get("zip_codes", [""])[0]
    )
    centroids = load_zip_centroids()

    for contact in enriched_contacts:
        pid = str(contact.get("id") or contact.get("personId") or "")
        pre = pre_enrichment.get(pid, {})

        # Restore _location_type from pre-enrichment data
        if not contact.get("_location_type") and pre.get("_location_type"):
            contact["_location_type"] = pre["_location_type"]

        # Compute distance from contact ZIP to center ZIP
        contact_zip = (
            contact.get("zipCode")
            or contact.get("personZip")
            or contact.get("companyZipCode")
            or pre.get("personZip", "")
        )
        if contact_zip and center_zip and contact_zip in centroids and center_zip in centroids:
            c_lat, c_lng, _ = centroids[contact_zip]
            t_lat, t_lng, _ = centroids[center_zip]
            contact["distance"] = round(haversine_distance(c_lat, c_lng, t_lat, t_lng), 2)

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
    preview_count = len(st.session_state.geo_preview_contacts or [])
    companies = len(st.session_state.geo_contacts_by_company or {})

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        metric_card("Contacts Enriched", len(enriched_contacts))

    with col2:
        metric_card("Preview Found", preview_count)

    with col3:
        metric_card("Companies", companies)

    # Results table + filters (fragment for instant filter response)
    @st.fragment
    def geo_results_table(scored_leads):
        display_data = []
        for idx, lead in enumerate(scored_leads):
            loc_type = lead.get("_location_type", "")
            loc_type_display = ""
            if loc_type == "PersonAndHQ":
                loc_type_display = "HQ+Person"
            elif loc_type == "Person":
                loc_type_display = "Person-only"

            display_data.append({
                "_idx": idx,
                "Name": f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip(),
                "Title": lead.get("jobTitle", ""),
                "Company": lead.get("companyName", "") or lead.get("company", {}).get("name", ""),
                "City": lead.get("city", "") or lead.get("personCity", ""),
                "State": lead.get("state", "") or lead.get("personState", ""),
                "Loc Type": loc_type_display,
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
            filtered_df.drop(columns=["_idx"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Name": st.column_config.TextColumn("Name", width="medium"),
                "Title": st.column_config.TextColumn("Title", width="medium"),
                "Company": st.column_config.TextColumn("Company", width="large"),
                "City": st.column_config.TextColumn("City", width="small"),
                "State": st.column_config.TextColumn("State", width="small"),
                "Loc Type": st.column_config.TextColumn("Loc Type", width="small", help="HQ+Person = local HQ, Person-only = branch office"),
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width="small"),
                "Accuracy": st.column_config.NumberColumn("Accuracy", width="small"),
                "Priority": st.column_config.TextColumn("Priority", width="small"),
                "Phone": st.column_config.TextColumn("Phone", width="medium"),
                "Email": st.column_config.TextColumn("Email", width="medium"),
            },
        )

        # Export section
        st.markdown("---")

        export_quality_warnings(scored_leads)

        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            if st.session_state.geo_operator:
                op = st.session_state.geo_operator
                st.caption(f"Export for: **{op.get('operator_name')}** · {op.get('vending_business_name') or 'N/A'}")

        with col2:
            csv = filtered_df.drop(columns=["_idx"]).to_csv(index=False)
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
            filtered_indices = filtered_df["_idx"].tolist()
            st.session_state.geo_export_leads = [scored_leads[i] for i in filtered_indices]

            # Persist to DB for re-export after session loss
            if not st.session_state.get("geo_leads_staged"):
                op = st.session_state.get("geo_operator")
                db.save_staged_export(
                    "geography",
                    st.session_state.geo_export_leads,
                    query_params=st.session_state.get("geo_query_params"),
                    operator_id=op.get("id") if op else None,
                )
                st.session_state.geo_leads_staged = True

    geo_results_table(scored)

    # Option to go back and revise (Manual mode)
    if st.session_state.geo_mode == "manual":
        st.markdown("---")
        if ui.button(text="Back to Contact Selection", variant="outline", key="geo_back_btn"):
            st.session_state.geo_selection_confirmed = False
            st.session_state.geo_enrichment_done = False
            st.session_state.geo_enriched_contacts = None
            st.session_state.geo_usage_logged = False
            st.rerun()
