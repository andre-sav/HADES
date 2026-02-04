"""
Usage - Credit usage and query history.
Superhuman-inspired: clean metrics, scannable tables.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from turso_db import get_database
from cost_tracker import CostTracker
from zoominfo_client import get_zoominfo_client, ZoomInfoError
from ui_components import (
    inject_base_styles,
    page_header,
    colored_progress_bar,
    COLORS,
)

st.set_page_config(page_title="Usage", page_icon="📊", layout="wide")

# Apply design system styles
inject_base_styles()


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
# ZOOMINFO API USAGE (from ZoomInfo directly)
# =============================================================================
with st.expander("ZoomInfo API Usage", expanded=False):
    st.caption("Fetch current usage data directly from ZoomInfo API")

    # Only fetch when user explicitly clicks
    if st.button("Fetch ZoomInfo Usage", use_container_width=True):
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
                    st.metric("API Requests", f"{used:,} / {limit:,}")
                    pct = (used / limit * 100) if limit > 0 else 0
                    colored_progress_bar(pct)
                else:
                    st.metric("API Requests", f"{used:,}")

            # Record Limit
            with col2:
                rec = metrics.get("recordLimit", {})
                used = rec.get("used", 0)
                limit = rec.get("limit", 0)
                if limit > 0:
                    st.metric("Records", f"{used:,} / {limit:,}")
                    pct = (used / limit * 100) if limit > 0 else 0
                    colored_progress_bar(pct)
                else:
                    st.metric("Records", f"{used:,}")

            # Unique ID Limit
            with col3:
                uid = metrics.get("uniqueIdLimit", {})
                used = uid.get("used", 0)
                limit = uid.get("limit", 0)
                if limit > 0:
                    st.metric("Unique IDs", f"{used:,} / {limit:,}")
                    pct = (used / limit * 100) if limit > 0 else 0
                    colored_progress_bar(pct)
                else:
                    st.metric("Unique IDs", f"{used:,}")

            # Show raw data in debug mode
            if st.checkbox("Show raw API response", key="zi_raw"):
                st.json(zi_usage)
    else:
        st.info("Click 'Fetch ZoomInfo Usage' to load current API usage from ZoomInfo")

st.markdown("---")

# =============================================================================
# WEEKLY OVERVIEW (Internal Tracking)
# =============================================================================
st.subheader("Internal Usage Tracking")
weekly = cost_tracker.get_weekly_usage_by_workflow()
total = sum(weekly.values())

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("This week", f"{total:,} credits")

with col2:
    intent = weekly.get("intent", 0)
    budget = cost_tracker.format_budget_display("intent")
    if budget["has_cap"]:
        st.metric("Intent", f"{intent:,} / {budget['cap']:,}")
        colored_progress_bar(budget["percent"])
    else:
        st.metric("Intent", f"{intent:,}")

with col3:
    geo = weekly.get("geography", 0)
    st.metric("Geography", f"{geo:,}")
    st.caption("No cap")


# =============================================================================
# PERIOD SUMMARY
# =============================================================================
st.markdown("---")

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
    st.metric("Credits", f"{summary.total_credits:,}")

with col2:
    st.metric("Leads", f"{summary.total_leads:,}")

with col3:
    st.metric("Queries", f"{summary.total_queries:,}")

with col4:
    if summary.total_credits > 0 and summary.total_leads > 0:
        efficiency = summary.total_leads / summary.total_credits
        st.metric("Leads/credit", f"{efficiency:.2f}")
    else:
        st.metric("Leads/credit", "—")


# =============================================================================
# BY WORKFLOW
# =============================================================================
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


# =============================================================================
# RECENT QUERIES
# =============================================================================
st.markdown("---")
st.subheader("Recent queries")

queries = db.get_recent_queries(limit=20)

if not queries:
    st.caption("No queries yet")
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
        },
    )
