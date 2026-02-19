"""
Pipeline Health - Operational status indicators for API, cache, and database.
"""

import streamlit as st
from datetime import datetime

from turso_db import get_database
from ui_components import (
    inject_base_styles,
    page_header,
    status_badge,
    metric_card,
    styled_table,
    empty_state,
    COLORS,
)

st.set_page_config(page_title="Pipeline Health", page_icon="🔧", layout="wide")

inject_base_styles()

from utils import require_auth
require_auth()


@st.cache_resource
def get_db():
    return get_database()


try:
    db = get_db()
except Exception as e:
    st.error(f"Failed to connect: {e}")
    st.stop()


# =============================================================================
# HELPERS
# =============================================================================

def time_ago(iso_str: str | None) -> str:
    """Convert ISO timestamp to 'X minutes/hours/days ago' string."""
    if not iso_str:
        return "Never"
    try:
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


def health_indicator(label: str, status: str, detail: str, timestamp: str | None = None):
    """Render a health indicator card with green/yellow/red status."""
    color_map = {
        "green": COLORS.get("success", "#22c55e"),
        "yellow": "#eab308",
        "red": COLORS.get("error", "#ef4444"),
        "gray": COLORS.get("text_secondary", "#64748b"),
    }
    dot_color = color_map.get(status, color_map["gray"])
    status_label = {"green": "Healthy", "yellow": "Stale", "red": "Critical", "gray": "Unknown"}.get(status, "Unknown")

    ts_html = f'<span style="color: {COLORS["text_secondary"]}; font-size: 0.8rem;">{timestamp}</span>' if timestamp else ""

    st.markdown(f'''
    <div style="
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 8px;
    ">
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px;">
            <span style="
                display: inline-block; width: 10px; height: 10px;
                border-radius: 50%; background: {dot_color};
                box-shadow: 0 0 6px {dot_color};
            "></span>
            <strong style="color: {COLORS['text_primary']};">{label}</strong>
            <span style="color: {COLORS['text_secondary']}; font-size: 0.85rem; margin-left: auto;">{status_label}</span>
        </div>
        <div style="color: {COLORS['text_secondary']}; font-size: 0.9rem;">
            {detail} {ts_html}
        </div>
    </div>
    ''', unsafe_allow_html=True)


# =============================================================================
# HEADER
# =============================================================================
def refresh_health():
    st.cache_resource.clear()
    if "health_checked" in st.session_state:
        del st.session_state["health_checked"]
    st.rerun()


page_header(
    "Pipeline Health",
    "System status and diagnostics",
    action_label="Refresh Status",
    action_callback=refresh_health,
)


# =============================================================================
# HEALTH CHECKS
# =============================================================================

# 1. Last Successful Query
last_intent = db.get_last_query("intent")
last_geo = db.get_last_query("geography")

# Pick the most recent
last_query = None
if last_intent and last_geo:
    last_query = last_intent if (last_intent.get("created_at", "") >= last_geo.get("created_at", "")) else last_geo
elif last_intent:
    last_query = last_intent
elif last_geo:
    last_query = last_geo

if last_query:
    ts = last_query.get("created_at", "")
    ago = time_ago(ts)
    wf = last_query.get('workflow_type', 'unknown').title()
    leads = last_query.get('leads_returned', 0)
    # Determine staleness — thresholds: <1h green, <6h yellow, >6h red
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        minutes = (now - dt).total_seconds() / 60
        if minutes < 60:
            q_status = "green"
            q_detail = f"{wf} · {leads} leads returned"
        elif minutes < 360:  # 6 hours
            q_status = "yellow"
            q_detail = f"{wf} · {leads} leads returned · No queries in over {int(minutes / 60)}h"
        else:
            q_status = "red"
            hours = int(minutes / 60)
            q_detail = f"{wf} · {leads} leads returned · No queries in {hours}h (threshold: 6h)"
    except (ValueError, TypeError):
        q_status = "gray"
        q_detail = f"{wf} · {leads} leads returned"

    health_indicator(
        "Last Query",
        q_status,
        q_detail,
        timestamp=ago,
    )
else:
    health_indicator("Last Query", "gray", "No queries executed yet")


# 2. Cache Freshness
cache_stats = db.get_cache_stats()
if cache_stats["total"] > 0:
    active = cache_stats["active"]
    total = cache_stats["total"]
    newest = cache_stats.get("newest")
    cache_status = "green" if active > 0 else "yellow"
    health_indicator(
        "Cache",
        cache_status,
        f"{active} active / {total} total entries",
        timestamp=f"Latest: {time_ago(newest)}" if newest else None,
    )
else:
    health_indicator("Cache", "gray", "No cached results")


# 3. Turso Database Connection
try:
    db.execute("SELECT 1")
    health_indicator("Database", "green", "Turso connection active")
except Exception as e:
    health_indicator("Database", "red", f"Connection failed: {str(e)[:80]}")


# 4. ZoomInfo API Status
try:
    from zoominfo_client import get_zoominfo_client
    client = get_zoominfo_client()
    if client.access_token:
        health_indicator(
            "ZoomInfo API",
            "green",
            "Authenticated with valid token",
        )
    else:
        health_indicator("ZoomInfo API", "yellow", "No active token — will authenticate on next query")
except Exception as e:
    health_indicator("ZoomInfo API", "red", f"Client error: {str(e)[:80]}")


# =============================================================================
# RECENT ERRORS
# =============================================================================
st.markdown("---")
st.caption("Recent Pipeline Runs")

# Check pipeline_runs for errors
try:
    intent_runs = db.get_pipeline_runs("intent", limit=10)
    geo_runs = db.get_pipeline_runs("geography", limit=10)
    all_runs = sorted(
        intent_runs + geo_runs,
        key=lambda r: r.get("created_at", ""),
        reverse=True,
    )[:10]

    if all_runs:
        run_rows = []
        for run in all_runs:
            status = run.get("status", "unknown")
            error_msg = run.get("error_message")
            ts = run.get("created_at", "")[:16].replace("T", " ") if run.get("created_at") else "—"

            if status == "completed":
                pill_status = "success"
            elif status == "failed":
                pill_status = "error"
            else:
                pill_status = "muted"

            detail = ""
            if error_msg:
                detail = error_msg[:60]
            elif run.get("leads_exported"):
                detail = f"{run['leads_exported']} leads exported"
            elif run.get("credits_used"):
                detail = f"{run['credits_used']} credits"

            run_rows.append({
                "time": ts,
                "workflow": run.get("workflow_type", "—").title(),
                "trigger": (run.get("trigger") or "manual").title(),
                "status": status.title(),
                "detail": detail or "—",
            })

        styled_table(
            rows=run_rows,
            columns=[
                {"key": "time", "label": "Time", "mono": True},
                {"key": "workflow", "label": "Workflow"},
                {"key": "trigger", "label": "Trigger"},
                {"key": "status", "label": "Status", "pill": {
                    "Completed": "success",
                    "Failed": "error",
                    "Running": "warning",
                    "Pending": "muted",
                }},
                {"key": "detail", "label": "Detail"},
            ],
        )

        # Count errors
        error_count = sum(1 for r in all_runs if r.get("status") == "failed")
        if error_count > 0:
            st.caption(f"{error_count} failed run(s) in recent history")
    else:
        empty_state(
            "No pipeline runs recorded",
            hint="Pipeline runs are logged by the automated intent poller and manual searches.",
        )
except Exception:
    st.caption("Pipeline runs table not available")


# =============================================================================
# QUERY HISTORY SUMMARY
# =============================================================================
st.markdown("---")
st.caption("Recent Query Activity")

queries = db.get_recent_queries(limit=5)
if queries:
    for q in queries:
        ts = q.get("created_at", "")[:16].replace("T", " ") if q.get("created_at") else "—"
        wf = q.get("workflow_type", "unknown").title()
        leads = q.get("leads_returned", 0)
        exported = q.get("leads_exported", 0)
        exp_text = f" · {exported} exported" if exported else ""
        st.caption(f"{ts} — {wf} · {leads} leads{exp_text}")
else:
    st.caption("No queries recorded yet")
