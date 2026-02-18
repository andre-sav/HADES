"""
Usage - Credit usage and query history.
Superhuman-inspired: clean metrics, scannable tables.
"""

import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

from turso_db import get_database
from cost_tracker import CostTracker
from zoominfo_client import get_zoominfo_client
from ui_components import (
    inject_base_styles,
    page_header,
    colored_progress_bar,
    metric_card,
    empty_state,
    labeled_divider,
    COLORS,
)

st.set_page_config(page_title="Usage", page_icon="📊", layout="wide")

# Apply design system styles
inject_base_styles()

from utils import require_auth
require_auth()


# Initialize
@st.cache_resource
def get_services():
    db = get_database()
    return db, CostTracker(db)


def fetch_zoominfo_usage():
    """Fetch usage data from ZoomInfo API. Only called on explicit user request."""
    try:
        client = get_zoominfo_client()
        return client.get_usage()
    except Exception as e:
        return {"error": str(e)}


try:
    db, cost_tracker = get_services()
except Exception as e:
    st.error(f"Failed to initialize: {e}")
    st.stop()


# =============================================================================
# HEADER
# =============================================================================
def refresh_data():
    st.cache_resource.clear()
    st.rerun()


page_header(
    "Usage",
    "Credit usage and query history",
    action_label="Refresh",
    action_callback=refresh_data,
)


# =============================================================================
# ZOOMINFO API USAGE
# =============================================================================
col1, col2 = st.columns([3, 1])
with col1:
    st.caption("ZoomInfo API Usage")
with col2:
    if ui.button(text="Fetch ZoomInfo Usage", variant="default", key="usage_fetch_btn"):
        with st.spinner("Fetching usage data from ZoomInfo..."):
            zi_usage = fetch_zoominfo_usage()
            st.session_state["zi_usage_data"] = zi_usage

# Display cached data if available
if "zi_usage_data" in st.session_state:
    zi_usage = st.session_state["zi_usage_data"]

    if "error" in zi_usage:
        st.warning(f"Could not fetch ZoomInfo usage: {zi_usage['error']}")
        st.caption("Check ZoomInfo credentials in .streamlit/secrets.toml")
    else:
        # Parse the usage array format from the API
        usage_data = zi_usage.get("usage", [])

        # Extract metrics from usage array
        metrics = {}
        for item in usage_data:
            limit_type = item.get("limitType", "")
            metrics[limit_type] = {
                "used": item.get("currentUsage", 0),
                "limit": item.get("totalLimit", 0),
                "remaining": item.get("usageRemaining", 0),
                "description": item.get("description", ""),
            }

        col1, col2, col3 = st.columns(3)

        # Request Limit
        with col1:
            req = metrics.get("requestLimit", {})
            used = req.get("used", 0)
            limit = req.get("limit", 0)
            if limit > 0:
                metric_card("API Requests", f"{used:,} / {limit:,}")
                pct = (used / limit * 100) if limit > 0 else 0
                colored_progress_bar(pct)
            else:
                metric_card("API Requests", f"{used:,}")

        # Record Limit
        with col2:
            rec = metrics.get("recordLimit", {})
            used = rec.get("used", 0)
            limit = rec.get("limit", 0)
            if limit > 0:
                metric_card("Records", f"{used:,} / {limit:,}")
                pct = (used / limit * 100) if limit > 0 else 0
                colored_progress_bar(pct)
            else:
                metric_card("Records", f"{used:,}")

        # Unique ID Limit
        with col3:
            uid = metrics.get("uniqueIdLimit", {})
            used = uid.get("used", 0)
            limit = uid.get("limit", 0)
            if limit > 0:
                metric_card("Unique IDs", f"{used:,} / {limit:,}")
                pct = (used / limit * 100) if limit > 0 else 0
                colored_progress_bar(pct)
            else:
                metric_card("Unique IDs", f"{used:,}")

        # Show raw data in debug mode
        with st.expander("Raw Response", expanded=False):
            st.json(zi_usage)

labeled_divider("Details")


# =============================================================================
# TABBED CONTENT
# =============================================================================
_usage_active = ui.tabs(options=["Weekly", "By Period", "Recent Queries"], default_value="Weekly", key="usage_main_tabs")

# --- WEEKLY TAB ---
if _usage_active == "Weekly":
    weekly = cost_tracker.get_weekly_usage_by_workflow()
    total = sum(weekly.values())

    col1, col2, col3 = st.columns(3)

    with col1:
        metric_card("This Week", total)

    with col2:
        intent = weekly.get("intent", 0)
        budget = cost_tracker.format_budget_display("intent")
        if budget["has_cap"]:
            metric_card("Intent", f"{intent:,} / {budget['cap']:,}")
            colored_progress_bar(budget["percent"])
        else:
            metric_card("Intent", intent)

    with col3:
        geo = weekly.get("geography", 0)
        metric_card("Geography", geo)

    # Weekly context info
    budget = cost_tracker.format_budget_display("intent")
    if budget["has_cap"] and budget["percent"] > 0:
        remaining = budget["remaining"]
        st.caption(f"Intent budget: {remaining:,} credits remaining this week ({100 - budget['percent']:.0f}% available)")
    elif total == 0:
        empty_state(
            "No credits used this week",
            hint="Run an Intent or Geography search to get started.",
        )

# --- BY PERIOD TAB ---
elif _usage_active == "By Period":
    col1, col2 = st.columns([1, 3])

    with col1:
        days = st.selectbox(
            "Period",
            [7, 14, 30, 90],
            format_func=lambda x: f"{x} days",
            label_visibility="collapsed",
        )

    summary = cost_tracker.get_usage_summary(days=days)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        metric_card("Credits", summary.total_credits)

    with col2:
        metric_card("Leads", summary.total_leads)

    with col3:
        metric_card("Queries", summary.total_queries)

    with col4:
        if summary.total_credits > 0 and summary.total_leads > 0:
            efficiency = summary.total_leads / summary.total_credits
            metric_card("Leads/Credit", f"{efficiency:.2f}")
        else:
            metric_card("Leads/Credit", "—")

    # By workflow breakdown
    if summary.by_workflow:
        st.markdown("---")

        data = []
        for wf, stats in summary.by_workflow.items():
            data.append({
                "Workflow": wf.title(),
                "Credits": stats["credits"],
                "Leads": stats["leads"],
                "Queries": stats["queries"],
            })

        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)

# --- RECENT QUERIES TAB ---
elif _usage_active == "Recent Queries":
    # Date range filter
    today = datetime.now().date()
    col_range, col_wf = st.columns([2, 1])

    with col_range:
        range_option = st.selectbox(
            "Date range",
            ["This Week", "This Month", "Last 30 Days", "Custom"],
            label_visibility="collapsed",
            key="query_date_range",
        )

    with col_wf:
        wf_filter = st.selectbox(
            "Workflow",
            ["All", "Intent", "Geography"],
            label_visibility="collapsed",
            key="query_wf_filter",
        )

    # Determine date range
    if range_option == "This Week":
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif range_option == "This Month":
        start_date = today.replace(day=1)
        end_date = today
    elif range_option == "Last 30 Days":
        start_date = today - timedelta(days=30)
        end_date = today
    else:
        col_s, col_e = st.columns(2)
        with col_s:
            start_date = st.date_input("From", value=today - timedelta(days=7), key="query_start")
        with col_e:
            end_date = st.date_input("To", value=today, key="query_end")

    wf_type = wf_filter.lower() if wf_filter != "All" else None

    queries = db.get_queries_by_date_range(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        workflow_type=wf_type,
    )

    if not queries:
        st.caption(f"No queries found for {range_option.lower()}")
    else:
        data = []
        for q in queries:
            params = q["query_params"]
            if q["workflow_type"] == "intent":
                topics = params.get("topics", [])
                desc = ", ".join(topics[:2]) if topics else "Intent"
            else:
                zips = params.get("zip_codes", [])
                desc = ", ".join(zips[:2]) if zips else "Geography"

            data.append({
                "Time": q["created_at"][:16].replace("T", " ") if q["created_at"] else "—",
                "Workflow": q["workflow_type"].title(),
                "Query": desc[:30],
                "Leads": q["leads_returned"],
                "Exported": q["leads_exported"] or 0,
            })

        df = pd.DataFrame(data)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Time": st.column_config.TextColumn("Time", width="medium"),
                "Workflow": st.column_config.TextColumn("Type", width="small"),
                "Query": st.column_config.TextColumn("Query", width="large"),
                "Leads": st.column_config.NumberColumn("Leads", width="small"),
                "Exported": st.column_config.NumberColumn("Exported", width="small"),
            },
        )
        st.caption(f"{len(queries)} queries")
