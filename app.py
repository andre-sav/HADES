"""
HADES - ZoomInfo Lead Pipeline
"""

import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
from ui_components import (
    inject_base_styles,
    page_header,
    status_badge,
    last_run_indicator,
    metric_card,
    styled_table,
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
        st.markdown(
            f"""<div class="quick-action">
                <div class="qa-step">{qa['step']}</div>
                <div class="icon">{qa['icon']}</div>
                <div class="title">{qa['title']}</div>
                <div class="desc">{qa['desc']}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.page_link(qa["page"], label=f"Open {qa['title']}", use_container_width=True)


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
        from datetime import datetime
        try:
            _ts = last_intent.get("created_at", "")
            _dt = datetime.fromisoformat(_ts.replace("Z", "+00:00"))
            _hours = (datetime.now() - _dt.replace(tzinfo=None)).total_seconds() / 3600
            _freshness = status_badge("success", "Active") if _hours < 6 else status_badge("warning", "Stale")
        except (ValueError, TypeError):
            _freshness = status_badge("neutral", "Unknown")
        st.markdown(_freshness, unsafe_allow_html=True)
    st.caption("Intent")
    last_run_indicator(last_intent)

with status_col3:
    if last_geo:
        try:
            _ts = last_geo.get("created_at", "")
            _dt = datetime.fromisoformat(_ts.replace("Z", "+00:00"))
            _hours = (datetime.now() - _dt.replace(tzinfo=None)).total_seconds() / 3600
            _freshness = status_badge("success", "Active") if _hours < 6 else status_badge("warning", "Stale")
        except (ValueError, TypeError):
            _freshness = status_badge("neutral", "Unknown")
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
    st.caption("Recent runs")

    table_data = []
    for q in recent_display:
        workflow = q["workflow_type"].title()
        leads = q.get("leads_returned", 0) or 0
        exported = q.get("leads_exported", 0) or 0
        created = q.get("created_at", "")[:16] if q.get("created_at") else ""
        export_status = "Exported" if exported > 0 else "Not exported"

        table_data.append({
            "time": created,
            "workflow": workflow,
            "leads": leads,
            "exported": exported,
            "status": export_status,
        })

    styled_table(
        rows=table_data,
        columns=[
            {"key": "time", "label": "Time"},
            {"key": "workflow", "label": "Workflow"},
            {"key": "leads", "label": "Leads", "align": "right", "mono": True},
            {"key": "exported", "label": "Exported", "align": "right", "mono": True},
            {"key": "status", "label": "Status", "pill": {"Exported": "success", "Not exported": "muted"}},
        ],
    )
else:
    empty_state(
        "No recent activity",
        hint="Run an Intent or Geography search to get started.",
    )
