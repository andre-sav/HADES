"""
HADES - ZoomInfo Lead Pipeline
"""

import streamlit as st
import streamlit_shadcn_ui as ui
from datetime import datetime
from ui_components import (
    inject_base_styles,
    page_header,
    status_badge,
    last_run_indicator,
    metric_card,
    empty_state,
    labeled_divider,
    COLORS,
)

st.set_page_config(
    page_title="HADES",
    page_icon="◉",
    layout="wide",
)

# Apply design system styles
inject_base_styles()

from utils import require_auth
require_auth()

# --- Header ---
page_header("HADES", "ZoomInfo lead pipeline with ICP filtering and scoring")

# --- Initialize & Status ---
try:
    from turso_db import get_database
    db = get_database()
    connected = True
except Exception as e:
    connected = False
    st.error(f"Database connection failed: {e}")
    st.caption("Check `.streamlit/secrets.toml` configuration")
    st.stop()


# =============================================================================
# QUICK ACTIONS (focal point — what the user came here to do)
# =============================================================================
col1, col2, col3 = st.columns(3)

_quick_actions = [
    {"page": "pages/1_Intent_Workflow.py", "icon": "🎯", "title": "Intent Search", "desc": "Companies showing buying signals", "step": "Step 1", "col": col1},
    {"page": "pages/2_Geography_Workflow.py", "icon": "📍", "title": "Geography Search", "desc": "Contacts in a service territory", "step": "Step 1", "col": col2},
    {"page": "pages/4_CSV_Export.py", "icon": "📤", "title": "Export Leads", "desc": "Download VanillaSoft CSV", "step": "Step 2", "col": col3},
]

for qa in _quick_actions:
    with qa["col"]:
        st.caption(qa["step"].upper())
        st.page_link(qa["page"], label=f"{qa['icon']} {qa['title']}", use_container_width=True)
        st.caption(qa["desc"])


# =============================================================================
# STATUS ROW — staged leads + last runs (contextual, not dominant)
# =============================================================================
st.markdown("")

last_intent = db.get_last_query("intent")
last_geo = db.get_last_query("geography")
intent_staged = len(st.session_state.get("intent_export_leads", []) or [])
geo_staged = len(st.session_state.get("geo_export_leads", []) or [])
total_staged = intent_staged + geo_staged

status_col1, status_col2, status_col3, status_col4 = st.columns(4)

with status_col1:
    badge = status_badge("success", "Connected") if connected else status_badge("error", "Offline")
    st.markdown(badge, unsafe_allow_html=True)
    st.caption("Database")

with status_col2:
    if last_intent:
        try:
            _ts = last_intent.get("created_at", "")
            _dt = datetime.fromisoformat(_ts.replace("Z", "+00:00"))
            _hours = (datetime.now() - _dt.replace(tzinfo=None)).total_seconds() / 3600
            if _hours < 6:
                _freshness = status_badge("success", "Active", tooltip="Last run within 6 hours")
            else:
                _freshness = status_badge("warning", "Stale", tooltip=f"No queries in {int(_hours)}h — run a new search to refresh")
        except (ValueError, TypeError):
            _freshness = status_badge("neutral", "Unknown", tooltip="Could not determine last run time")
        st.markdown(_freshness, unsafe_allow_html=True)
    st.caption("Intent")
    last_run_indicator(last_intent)

with status_col3:
    if last_geo:
        try:
            _ts = last_geo.get("created_at", "")
            _dt = datetime.fromisoformat(_ts.replace("Z", "+00:00"))
            _hours = (datetime.now() - _dt.replace(tzinfo=None)).total_seconds() / 3600
            if _hours < 6:
                _freshness = status_badge("success", "Active", tooltip="Last run within 6 hours")
            else:
                _freshness = status_badge("warning", "Stale", tooltip=f"No queries in {int(_hours)}h — run a new search to refresh")
        except (ValueError, TypeError):
            _freshness = status_badge("neutral", "Unknown", tooltip="Could not determine last run time")
        st.markdown(_freshness, unsafe_allow_html=True)
    st.caption("Geography")
    last_run_indicator(last_geo)

with status_col4:
    if total_staged > 0:
        st.markdown(status_badge("info", f"{total_staged} staged"), unsafe_allow_html=True)
        st.caption("Ready to export")
    else:
        st.caption("No leads staged")


# =============================================================================
# METRICS — operational context, not hero content
# =============================================================================
labeled_divider("Metrics")

col1, col2, col3 = st.columns(3)

with col1:
    weekly_credits = db.get_weekly_usage()
    metric_card("Weekly Credits", weekly_credits, help_text="Since Monday")

with col2:
    recent = db.get_recent_queries(limit=100)
    total_leads = sum(q.get("leads_returned", 0) or 0 for q in recent)
    metric_card("Leads Found", total_leads, help_text="Last 100 queries")

with col3:
    operators = db.get_operators()
    metric_card("Operators", len(operators), help_text="Active records")


# =============================================================================
# RECENT RUNS
# =============================================================================
labeled_divider("Recent Runs")

recent_display = db.get_recent_queries(limit=10)

if recent_display:
    for q in recent_display:
        workflow = q["workflow_type"].title()
        leads = q.get("leads_returned", 0) or 0
        exported = q.get("leads_exported", 0) or 0
        created = q.get("created_at", "")[:16] if q.get("created_at") else ""
        export_tag = "exported" if exported > 0 else "not exported"
        params = q.get("query_params", {}) or {}

        header = f"{created} · **{workflow}** · {leads} leads · {export_tag}"
        with st.expander(header):
            if params:
                # Format query params as readable key-value pairs
                _display_keys = {
                    "zip_codes": "ZIP Codes",
                    "zip_count": "ZIP Count",
                    "radius_miles": "Radius (mi)",
                    "center_zip": "Center ZIP",
                    "location_mode": "Location Mode",
                    "states": "States",
                    "topic": "Topic",
                    "topics": "Topics",
                    "signal_strength": "Signal Strength",
                    "signal_strengths": "Signal Strengths",
                    "employee_range": "Employee Range",
                    "management_levels": "Management Levels",
                    "accuracy_min": "Min Accuracy",
                    "target_contacts": "Target Contacts",
                    "target_companies": "Target Companies",
                    "sic_codes": "SIC Codes",
                    "sic_codes_count": "SIC Codes Count",
                    "location_search_type": "Location Search",
                    "location_type": "Location Type",
                    "phone_fields": "Required Phone Fields",
                    "mode": "Workflow Mode",
                }
                for key, val in params.items():
                    label = _display_keys.get(key, key.replace("_", " ").title())
                    if isinstance(val, list):
                        val = ", ".join(str(v) for v in val)
                    st.markdown(f"**{label}:** {val}")
            else:
                st.caption("No query details recorded")
else:
    empty_state(
        "No recent activity",
        hint="Run an Intent or Geography search to get started.",
    )
