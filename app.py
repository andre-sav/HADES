"""
HADES - ZoomInfo Lead Pipeline
Superhuman-inspired: clean, focused, minimal.
"""

import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
from ui_components import inject_base_styles, page_header, status_badge, last_run_indicator, metric_card, styled_table

st.set_page_config(
    page_title="HADES",
    page_icon="◉",
    layout="wide",
)

# Apply design system styles
inject_base_styles()

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

# --- System Status Row ---
last_intent = db.get_last_query("intent")
last_geo = db.get_last_query("geography")

status_col1, status_col2, status_col3, status_col4 = st.columns(4)

with status_col1:
    badge = status_badge("success", "Connected") if connected else status_badge("error", "Offline")
    st.markdown(badge, unsafe_allow_html=True)
    st.caption("Database")

with status_col2:
    last_run_indicator(last_intent)

with status_col3:
    last_run_indicator(last_geo)

with status_col4:
    # Staged leads count
    intent_staged = len(st.session_state.get("intent_export_leads", []) or [])
    geo_staged = len(st.session_state.get("geo_export_leads", []) or [])
    total_staged = intent_staged + geo_staged
    if total_staged > 0:
        st.markdown(status_badge("info", f"{total_staged} staged"), unsafe_allow_html=True)
        st.caption("Ready to export")
    else:
        st.caption("No leads staged")

# --- Quick Stats ---
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    operators = db.get_operators()
    metric_card("Operators", len(operators))

with col2:
    weekly_credits = db.get_weekly_usage()
    metric_card("Weekly Credits", weekly_credits)

with col3:
    recent = db.get_recent_queries(limit=100)
    metric_card("Queries", len(recent))

with col4:
    total_leads = sum(q.get("leads_returned", 0) or 0 for q in recent)
    metric_card("Leads Found", total_leads)

# --- Quick Actions ---
st.markdown("---")

from ui_components import COLORS

col1, col2, col3 = st.columns(3)

_quick_actions = [
    {"page": "pages/1_Intent_Workflow.py", "icon": "🎯", "title": "Intent Search", "desc": "Find companies showing intent signals", "col": col1},
    {"page": "pages/2_Geography_Workflow.py", "icon": "📍", "title": "Geography Search", "desc": "Find companies by location", "col": col2},
    {"page": "pages/4_CSV_Export.py", "icon": "📤", "title": "Export Leads", "desc": "Download VanillaSoft CSV", "col": col3},
]

for qa in _quick_actions:
    with qa["col"]:
        st.markdown(
            f"""<div style="
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 1.25rem;
                text-align: center;
                transition: border-color 0.2s, box-shadow 0.2s;
                cursor: default;
            ">
                <div style="font-size: 1.75rem; margin-bottom: 0.4rem;">{qa['icon']}</div>
                <div style="font-weight: 600; color: {COLORS['text_primary']}; margin-bottom: 0.25rem;">{qa['title']}</div>
                <div style="font-size: 0.8rem; color: {COLORS['text_muted']};">{qa['desc']}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.page_link(qa["page"], label=f"Open {qa['title']}", use_container_width=True)

# --- Recent Runs Table ---
st.markdown("---")

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
    st.caption("No recent activity")
