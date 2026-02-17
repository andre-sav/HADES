"""
Automation - Pipeline scheduling and run history.
"""

from datetime import datetime, timedelta, timezone

import streamlit as st

from turso_db import get_database
from cost_tracker import CostTracker
from utils import get_automation_config
from ui_components import (
    inject_base_styles,
    page_header,
    metric_card,
    status_badge,
    labeled_divider,
    empty_state,
    COLORS,
)

st.set_page_config(page_title="Automation", page_icon="⚙️", layout="wide")
inject_base_styles()

# --- Initialize ---
try:
    db = get_database()
except Exception as e:
    st.error(f"Failed to connect to database: {e}")
    st.stop()


# --- Helpers ---

def _next_scheduled_run() -> str:
    """Compute next weekday at 7:00 AM ET from now."""
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except ImportError:
        et = timezone(timedelta(hours=-5))

    now = datetime.now(et)
    target_hour = 7

    candidate = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    # Skip Saturday and Sunday
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)

    delta = candidate - now
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)

    day_name = candidate.strftime("%A")
    if hours < 24:
        return f"{day_name} 7:00 AM ET ({hours}h {minutes}m)"
    return f"{day_name} 7:00 AM ET ({hours // 24}d {hours % 24}h)"


_STATUS_BADGE_MAP = {
    "success": ("success", "Success"),
    "failed": ("error", "Failed"),
    "skipped": ("warning", "Skipped"),
    "running": ("info", "Running"),
}


def _render_status_badge(status: str) -> None:
    """Render a status badge inline via st.markdown."""
    badge_type, label = _STATUS_BADGE_MAP.get(status, ("neutral", status))
    st.markdown(status_badge(badge_type, label), unsafe_allow_html=True)


def _format_trigger(trigger: str) -> str:
    """Format trigger value for display."""
    if trigger == "scheduled":
        return "Scheduled"
    if trigger == "manual":
        return "Manual"
    return trigger.title()


# --- Header ---
page_header(
    "Automation",
    "Automated intent polling schedule and run history",
)

# --- Metrics Row ---
runs = db.get_pipeline_runs("intent", limit=50)
cost_tracker = CostTracker(db)

col1, col2, col3 = st.columns(3)

with col1:
    metric_card("Next Scheduled Run", _next_scheduled_run())

with col2:
    if runs:
        last = runs[0]
        last_time = last.get("completed_at") or last.get("started_at") or "N/A"
        _render_status_badge(last["status"])
        metric_card("Last Run", last_time)
    else:
        metric_card("Last Run", "No runs yet")

with col3:
    weekly_credits = db.get_weekly_usage("intent")
    metric_card("Weekly Credits", weekly_credits)

# --- Manual Trigger ---
labeled_divider("Manual Trigger")

run_col1, run_col2 = st.columns([3, 1])
with run_col1:
    st.markdown("Run the intent pipeline manually with the current automation config.")
with run_col2:
    run_now = st.button(
        "Run Now", type="primary", use_container_width=True, key="auto_run_now",
    )

if run_now and not st.session_state.get("auto_run_triggered"):
    st.session_state["auto_run_triggered"] = True
    with st.spinner("Running intent pipeline..."):
        try:
            from scripts.run_intent_pipeline import run_pipeline
            from scripts._credentials import load_credentials

            config = get_automation_config("intent")
            creds = load_credentials()
            result = run_pipeline(config, creds, trigger="manual", db=db)

            if result["success"]:
                exported = result.get("summary", {}).get("contacts_exported", 0)
                st.success(f"Pipeline complete! {exported} leads exported.")
                if result.get("batch_id"):
                    st.info(f"Batch ID: {result['batch_id']}")
            else:
                st.error(f"Pipeline failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            st.error(f"Pipeline error: {e}")
    st.session_state["auto_run_triggered"] = False
    st.rerun()

# --- Run History ---
labeled_divider("Run History")

if not runs:
    empty_state(
        "No pipeline runs yet",
        hint="Runs will appear here after the first scheduled or manual execution.",
    )
else:
    for run in runs[:20]:
        trigger_label = _format_trigger(run["trigger"])
        time_str = run.get("completed_at") or run.get("started_at") or ""
        leads = run.get("leads_exported", 0)
        credits = run.get("credits_used", 0)

        # st.expander does not support HTML in labels, so use plain text
        expander_label = (
            f"{run['status'].title()} | {trigger_label} — {time_str} | "
            f"{leads} leads, {credits} credits"
        )

        with st.expander(expander_label):
            # Show badge inside the expander body
            _render_status_badge(run["status"])

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Status:** {run['status']}")
                st.markdown(f"**Trigger:** {run['trigger']}")
                if run.get("batch_id"):
                    st.markdown(f"**Batch ID:** {run['batch_id']}")
                if run.get("error_message"):
                    st.markdown(f"**Error:** `{run['error_message']}`")
            with col_b:
                st.markdown(f"**Credits Used:** {credits}")
                st.markdown(f"**Leads Exported:** {leads}")
                st.markdown(f"**Started:** {run.get('started_at', 'N/A')}")
                st.markdown(f"**Completed:** {run.get('completed_at', 'N/A')}")

            if run.get("summary"):
                st.markdown("**Summary:**")
                st.json(run["summary"])
            if run.get("config"):
                st.markdown("**Config:**")
                st.json(run["config"])

# --- Configuration Panel ---
labeled_divider("Automation Configuration")

config = get_automation_config("intent")
if not config:
    st.warning("No automation config found in `config/icp.yaml` under `automation.intent`")
else:
    st.markdown("*Read-only -- edit `config/icp.yaml` to change settings.*")
    st.json(config)
