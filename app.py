"""
HADES - ZoomInfo Lead Pipeline
"""

import logging

import streamlit as st
from datetime import datetime
from ui_components import (
    inject_base_styles,
    page_header,
    status_badge,
    metric_card,
    empty_state,
    labeled_divider,
    COLORS,
    SPACING,
    FONT_SIZES,
)

logger = logging.getLogger(__name__)

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
    logger.error(f"Database connection failed: {e}")
    st.error("Database connection failed. Please try again.")
    st.caption("Check `.streamlit/secrets.toml` configuration")
    st.stop()


# =============================================================================
# QUICK ACTIONS (focal point — what the user came here to do)
# =============================================================================
_quick_actions = [
    {"page": "pages/1_Intent_Workflow.py", "icon": "🎯", "title": "Intent Search", "desc": "Companies showing buying signals"},
    {"page": "pages/2_Geography_Workflow.py", "icon": "📍", "title": "Geography Search", "desc": "Contacts in a service territory"},
    {"page": "pages/4_CSV_Export.py", "icon": "📤", "title": "Export Leads", "desc": "Download VanillaSoft CSV"},
]

cols = st.columns(3)
for i, qa in enumerate(_quick_actions):
    with cols[i]:
        st.markdown(
            f'<div class="quick-action">'
            f'<div class="icon">{qa["icon"]}</div>'
            f'<div class="title">{qa["title"]}</div>'
            f'<div class="desc">{qa["desc"]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.page_link(qa["page"], label=f"Open {qa['title']}", use_container_width=True)


# =============================================================================
# STATUS ROW — system health at a glance
# =============================================================================
st.markdown("")

last_intent = db.get_last_query("intent")
last_geo = db.get_last_query("geography")
intent_staged = len(st.session_state.get("intent_export_leads", []) or [])
geo_staged = len(st.session_state.get("geo_export_leads", []) or [])
total_staged = intent_staged + geo_staged


def _freshness_badge(last_query):
    """Compute freshness badge from last query timestamp."""
    if not last_query:
        return status_badge("neutral", "No runs")
    try:
        ts = last_query.get("created_at", "")
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        delta = datetime.now() - dt.replace(tzinfo=None)
        if delta.days > 0:
            ago = f"{delta.days}d ago"
        elif delta.seconds >= 3600:
            ago = f"{delta.seconds // 3600}h ago"
        else:
            ago = "Just now"
        return status_badge("neutral", ago)
    except (ValueError, TypeError):
        return status_badge("neutral", "Unknown")


def _detail_text(last_query):
    """Show lead count from last run."""
    if not last_query:
        return ""
    leads = last_query.get("leads_returned", 0)
    return f"{leads} leads" if leads else ""


# Build status items as a single unified HTML row
# Last automation run
_last_automation_runs = db.get_pipeline_runs("intent", limit=1)
_last_auto = _last_automation_runs[0] if _last_automation_runs else None


def _auto_badge(run):
    """Badge for last automation run."""
    if not run:
        return status_badge("neutral", "No runs")
    st_map = {"completed": "success", "failed": "error", "running": "info"}
    badge_type = st_map.get(run.get("status", ""), "neutral")
    return status_badge(badge_type, run.get("status", "unknown").title())


def _auto_detail(run):
    """Detail line for last automation run."""
    if not run:
        return ""
    parts = []
    leads = run.get("leads_exported", 0)
    if leads:
        parts.append(f"{leads} leads")
    ts = run.get("completed_at") or run.get("started_at") or ""
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            delta = datetime.now() - dt.replace(tzinfo=None)
            if delta.days > 0:
                parts.append(f"{delta.days}d ago")
            elif delta.seconds >= 3600:
                parts.append(f"{delta.seconds // 3600}h ago")
            else:
                parts.append("Just now")
        except (ValueError, TypeError):
            pass
    return " · ".join(parts)


_status_items = [
    {
        "label": "Database",
        "badge": status_badge("success", "Connected") if connected else status_badge("error", "Offline"),
        "detail": "",
    },
    {
        "label": "Intent",
        "badge": _freshness_badge(last_intent),
        "detail": _detail_text(last_intent),
    },
    {
        "label": "Geography",
        "badge": _freshness_badge(last_geo),
        "detail": _detail_text(last_geo),
    },
    {
        "label": "Automation",
        "badge": _auto_badge(_last_auto),
        "detail": _auto_detail(_last_auto),
    },
    {
        "label": "Staged Leads",
        "badge": status_badge("info", f"{total_staged} staged") if total_staged > 0
        else status_badge("neutral", "None"),
        "detail": "Go to CSV Export to download or push" if total_staged > 0 else "Run a workflow to generate leads",
    },
]

_status_cells = ""
for item in _status_items:
    detail_html = (
        f'<div style="font-size:{FONT_SIZES["xs"]};color:{COLORS["text_muted"]};margin-top:4px;">'
        f'{item["detail"]}</div>'
    ) if item["detail"] else ""
    _status_cells += (
        f'<div style="display:flex;flex-direction:column;gap:4px;">'
        f'{item["badge"]}'
        f'<span style="font-size:{FONT_SIZES["xs"]};color:{COLORS["text_secondary"]};'
        f'text-transform:uppercase;letter-spacing:0.04em;font-weight:500;">{item["label"]}</span>'
        f'{detail_html}'
        f'</div>'
    )

st.markdown(
    f'<div style="display:flex;gap:{SPACING["xl"]};padding:{SPACING["md"]} {SPACING["lg"]};'
    f'background:{COLORS["bg_secondary"]};border:1px solid {COLORS["border"]};'
    f'border-radius:10px;margin-bottom:{SPACING["md"]};">'
    f'{_status_cells}'
    f'</div>',
    unsafe_allow_html=True,
)


# =============================================================================
# METRICS — operational context, not hero content
# =============================================================================
labeled_divider("Metrics")

col1, col2, col3 = st.columns(3)

with col1:
    weekly_credits = db.get_weekly_usage()
    metric_card("Weekly Credits", weekly_credits, help_text="ZoomInfo API credits used since Monday. Resets weekly.")

with col2:
    recent = db.get_recent_queries(limit=100)
    total_leads = sum(q.get("leads_returned", 0) or 0 for q in recent)
    metric_card("Leads Found", total_leads, help_text="Total leads returned across your last 100 searches")

with col3:
    operators = db.get_operators()
    metric_card("Operators", len(operators), help_text="Sales team members available for lead assignment")


# =============================================================================
# RECENT RUNS
# =============================================================================
labeled_divider("Recent Runs")

# Merge manual queries and automation pipeline runs
recent_display = db.get_recent_queries(limit=10)
_auto_runs = db.get_pipeline_runs("intent", limit=5)

# Show automation runs first if any exist
if _auto_runs:
    with st.expander(f"Automation Runs ({len(_auto_runs)})", expanded=False):
        for run in _auto_runs:
            status = run.get("status", "unknown")
            leads = run.get("leads_exported", 0) or 0
            credits = run.get("credits_used", 0) or 0
            trigger = run.get("trigger", "manual")
            ts = (run.get("completed_at") or run.get("started_at") or "")[:16]
            error = run.get("error_message", "")

            status_icon = {"completed": "✓", "failed": "✗", "running": "◉"}.get(status, "?")
            header = f"{ts} · {status_icon} {status.title()} · {leads} leads · {credits} credits · {trigger}"
            if error:
                st.markdown(f"{header}")
                st.caption(f"Error: {error}")
            else:
                st.markdown(header)

if recent_display:
    for q in recent_display:
        workflow = q["workflow_type"].title()
        leads = q.get("leads_returned", 0) or 0
        exported = q.get("leads_exported", 0) or 0
        created = q.get("created_at", "")[:16] if q.get("created_at") else ""
        params = q.get("query_params", {}) or {}

        header = f"{created} · **{workflow}** · {leads} {'lead' if leads == 1 else 'leads'}"
        if exported > 0:
            header += " · exported"
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
