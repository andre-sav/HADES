"""
Pipeline Health - Operational status indicators for API, cache, and database.
"""

import html
import logging

import streamlit as st
from datetime import datetime

from turso_db import get_database
from ui_components import (
    inject_base_styles,
    page_header,
    styled_table,
    empty_state,
    labeled_divider,
    COLORS,
    SPACING,
    FONT_SIZES,
)

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Pipeline Health", page_icon="🔧", layout="wide")

inject_base_styles()

from utils import require_auth, time_ago
require_auth()


@st.cache_resource
def get_db():
    return get_database()


try:
    db = get_db()
except Exception as e:
    logger.error(f"Failed to connect: {e}")
    st.error("Failed to connect. Please try again.")
    st.stop()


# =============================================================================
# HELPERS
# =============================================================================


# time_ago imported from utils


def health_indicator(label: str, status: str, detail: str, timestamp: str | None = None):
    """Render a health indicator card with green/yellow/red status."""
    color_map = {
        "green": COLORS["success"],
        "yellow": COLORS["warning"],
        "red": COLORS["error"],
        "gray": COLORS["text_secondary"],
    }
    dot_color = color_map.get(status, color_map["gray"])
    status_label = {"green": "Healthy", "yellow": "Stale", "red": "Critical", "gray": "Unknown"}.get(status, "Unknown")

    ts_html = (
        f'<span style="color:{COLORS["text_secondary"]};font-size:{FONT_SIZES["xs"]};">{timestamp}</span>'
        if timestamp else ""
    )

    st.markdown(f'''
    <div style="
        background:{COLORS['bg_secondary']};
        border:1px solid {COLORS['border']};
        border-radius:var(--radius);
        padding:{SPACING['md']};
        margin-bottom:{SPACING['sm']};
        box-shadow:var(--card-shadow);
        transition:border-color var(--transition);
    ">
        <div style="display:flex;align-items:center;gap:{SPACING['sm']};margin-bottom:{SPACING['xs']};">
            <span style="
                display:inline-block;width:10px;height:10px;
                border-radius:50%;background:{dot_color};
                box-shadow:0 0 6px {dot_color};
            "></span>
            <strong style="color:{COLORS['text_primary']};">{label}</strong>
            <span style="color:{COLORS['text_secondary']};font-size:{FONT_SIZES['sm']};margin-left:auto;">{status_label}</span>
        </div>
        <div style="color:{COLORS['text_secondary']};font-size:{FONT_SIZES['sm']};">
            {html.escape(str(detail))} {ts_html}
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

# Collect health statuses for critical alert
_health_statuses = []


def _track_health(label, status, detail):
    """Track status for critical alert banner."""
    _health_statuses.append({"label": label, "status": status, "detail": detail})


# 1. Last Activity (manual queries OR automated pipeline runs)
last_intent = db.get_last_query("intent")
last_geo = db.get_last_query("geography")

# Also check pipeline_runs (automated runs log there, not query_history)
_intent_runs = db.get_pipeline_runs("intent", limit=1)
_last_intent_run = _intent_runs[0] if _intent_runs else None

# Pick the most recent activity from any source
_candidates = []
if last_intent:
    _candidates.append(("query", last_intent))
if last_geo:
    _candidates.append(("query", last_geo))
if _last_intent_run:
    # Normalize pipeline_run to look like a query for the staleness check
    _candidates.append(("run", {
        "workflow_type": _last_intent_run["workflow_type"],
        "leads_returned": _last_intent_run.get("leads_exported", 0),
        "created_at": _last_intent_run.get("completed_at") or _last_intent_run.get("created_at", ""),
    }))

last_query = None
if _candidates:
    last_query = max(_candidates, key=lambda c: c[1].get("created_at", ""))[1]

# Compute all health statuses first
if last_query:
    ts = last_query.get("created_at", "")
    ago = time_ago(ts)
    wf = last_query.get('workflow_type', 'unknown').title()
    leads = last_query.get('leads_returned', 0)
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        minutes = (now - dt).total_seconds() / 60
        if minutes < 60:
            q_status = "green"
            q_detail = f"{wf} · {leads} leads returned"
        elif minutes < 1560:
            q_status = "yellow"
            hours = int(minutes / 60)
            q_detail = f"{wf} · {leads} leads returned · No queries in {hours}h"
        else:
            q_status = "red"
            hours = int(minutes / 60)
            q_detail = f"{wf} · {leads} leads returned · No queries in {hours}h (threshold: 26h)"
    except (ValueError, TypeError):
        q_status = "gray"
        q_detail = f"{wf} · {leads} leads returned"
    _track_health("Last Query", q_status, q_detail)
else:
    q_status, q_detail, ago = "gray", "No queries executed yet", None
    _track_health("Last Query", q_status, q_detail)

cache_stats = db.get_cache_stats()
if cache_stats["total"] > 0:
    active = cache_stats["active"]
    total = cache_stats["total"]
    newest = cache_stats.get("newest")
    cache_status = "green" if active > 0 else "yellow"
    cache_detail = f"{active} active / {total} total entries"
    _track_health("Cache", cache_status, cache_detail)
else:
    cache_status, cache_detail, newest = "gray", "No cached results", None
    _track_health("Cache", cache_status, cache_detail)

try:
    db.execute("SELECT 1")
    db_status, db_detail = "green", "Turso connection active"
except Exception as e:
    db_status, db_detail = "red", f"Connection failed: {str(e)[:80]}"
_track_health("Database", db_status, db_detail)

try:
    from zoominfo_client import get_zoominfo_client
    client = get_zoominfo_client()
    if client.access_token:
        zi_status, zi_detail = "green", "Authenticated with valid token"
    else:
        zi_status, zi_detail = "green", "Ready — will authenticate on next query"
except Exception as e:
    zi_status, zi_detail = "red", f"Client error: {str(e)[:80]}"
_track_health("ZoomInfo API", zi_status, zi_detail)

# P1: Critical alert at top when any subsystem is red
_critical = [h for h in _health_statuses if h["status"] == "red"]
for _c in _critical:
    st.error(f"Critical: {_c['label']} needs attention — {_c['detail']}")

# P2: 2x2 grid layout for health indicators
_h_col1, _h_col2 = st.columns(2)

with _h_col1:
    health_indicator("Last Query", q_status, q_detail, timestamp=ago if last_query else None)
    health_indicator("Database", db_status, db_detail)

with _h_col2:
    health_indicator(
        "Cache", cache_status, cache_detail,
        timestamp=f"Latest: {time_ago(newest)}" if cache_stats["total"] > 0 and newest else None,
    )
    health_indicator("ZoomInfo API", zi_status, zi_detail)


# =============================================================================
# RUN HISTORY
# =============================================================================
labeled_divider("Run History")

_wf_filter = st.radio(
    "Workflow", ["All", "Intent", "Geography"],
    horizontal=True, label_visibility="collapsed",
)

try:
    if _wf_filter == "All":
        _runs = db.get_all_pipeline_runs(limit=20)
    else:
        _runs = db.get_pipeline_runs(_wf_filter.lower(), limit=20)

    if _runs:
        for run in _runs:
            _status = run.get("status", "unknown")
            _summary = run.get("summary", {})
            _log_events = _summary.get("log_events", [])
            _duration = _summary.get("duration_seconds")
            _ts = run.get("started_at", "")
            _ago = time_ago(_ts) if _ts else "—"
            _wf = run.get("workflow_type", "—").title()
            _trigger = (run.get("trigger") or "manual").title()
            _leads = run.get("leads_exported", 0) or 0
            _credits = run.get("credits_used", 0) or 0
            _error = run.get("error_message")

            # Status icon
            if _status in ("completed", "success"):
                _icon = "✅"
            elif _status == "failed":
                _icon = "❌"
            elif _status == "running":
                _icon = "🔄"
            elif _status == "skipped":
                _icon = "⏭️"
            elif _status == "cancelled":
                _icon = "🚫"
            else:
                _icon = "•"

            # Summary line
            _parts = [f"**{_wf}** · {_trigger}"]
            if _leads:
                _parts.append(f"{_leads} leads")
            if _credits:
                _parts.append(f"{_credits} credits")
            if _duration:
                _parts.append(f"{_duration}s")
            if _error:
                _parts.append(f"⚠️ {_error[:60]}")
            _summary_line = " · ".join(_parts)

            with st.expander(f"{_icon} {_ago} — {_summary_line}"):
                # Detail tier: log events timeline
                if _log_events:
                    for evt in _log_events:
                        _lvl = evt.get("level", "info")
                        _badge = {"info": "ℹ️", "warn": "⚠️", "error": "🔴"}.get(_lvl, "•")
                        _evt_ts = evt.get("ts", "")[:19].replace("T", " ")
                        st.markdown(f"`{_evt_ts}` {_badge} {html.escape(evt.get('msg', ''))}")
                        if evt.get("detail"):
                            st.code(evt["detail"], language="text")
                else:
                    st.caption("No detailed log events recorded for this run.")

                # Run config
                _config = run.get("config")
                if _config:
                    with st.popover("Run Config"):
                        st.json(_config)
    else:
        empty_state(
            "No pipeline runs recorded",
            hint="Runs are logged by automated pipelines and manual workflow searches.",
        )
except Exception:
    logger.exception("Failed to load run history")
    st.caption("Run history not available")


# =============================================================================
# QUERY HISTORY SUMMARY
# =============================================================================
labeled_divider("Recent Query Activity")

queries = db.get_recent_queries(limit=5)
if queries:
    _activity_rows = []
    for q in queries:
        ts = q.get("created_at", "")[:16].replace("T", " ") if q.get("created_at") else "—"
        wf = q.get("workflow_type", "unknown").title()
        leads = q.get("leads_returned", 0)
        exported = q.get("leads_exported", 0)
        _activity_rows.append({
            "time": ts,
            "workflow": wf,
            "leads": leads,
            "exported": exported,
        })

    styled_table(
        rows=_activity_rows,
        columns=[
            {"key": "time", "label": "Time", "mono": True},
            {"key": "workflow", "label": "Workflow", "pill": {"Intent": "info", "Geography": "success"}},
            {"key": "leads", "label": "Leads", "align": "right", "mono": True},
            {"key": "exported", "label": "Exported", "align": "right", "mono": True},
        ],
    )
else:
    st.caption("No queries recorded yet")


# =============================================================================
# ERROR LOG
# =============================================================================
labeled_divider("Recent Errors")
try:
    _recent_errors = db.get_recent_errors(limit=20)
    if _recent_errors:
        for err in _recent_errors:
            _icon = "\U0001f534" if not err["recoverable"] else "\U0001f7e1"
            with st.expander(f"{_icon} {err['error_type']} — {err['workflow_type']} \u00b7 {err['created_at']}"):
                st.write(err["user_message"])
                if err["technical_message"]:
                    st.code(err["technical_message"], language="text")
                if err["context_json"]:
                    st.json(err["context_json"])
    else:
        st.caption("No errors logged")
except Exception:
    logger.exception("Failed to load error log")
    st.caption("Error log not available")
