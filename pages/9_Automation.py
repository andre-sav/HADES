"""Automation - Pipeline scheduling and run history."""

from datetime import datetime, timedelta, timezone

import streamlit as st

from turso_db import get_database
from utils import get_automation_config, get_budget_config
from ui_components import (
    inject_base_styles,
    page_header,
    metric_card,
    status_badge,
    colored_progress_bar,
    labeled_divider,
    empty_state,
    COLORS,
    FONT_SIZES,
    SPACING,
)

st.set_page_config(page_title="Automation", page_icon="⚙️", layout="wide")
inject_base_styles()

from utils import require_auth
require_auth()

try:
    db = get_database()
except Exception as e:
    st.error(f"Failed to connect to database: {e}")
    st.stop()


# --- Helpers ---

def _next_scheduled_run() -> tuple[str, str]:
    """Compute next weekday at 7:00 AM ET. Returns (short_label, countdown)."""
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except ImportError:
        et = timezone(timedelta(hours=-5))

    now = datetime.now(et)
    candidate = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)

    delta = candidate - now
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)

    day_label = candidate.strftime("%a %b %-d · 7 AM ET")  # "Mon Feb 17 · 7 AM ET"
    if hours < 24:
        countdown = f"{hours}h {minutes}m"
    else:
        countdown = f"{hours // 24}d {hours % 24}h"
    return day_label, countdown


_STATUS_MAP = {
    "success": ("success", "Success"),
    "failed": ("error", "Failed"),
    "skipped": ("warning", "Skipped"),
    "running": ("info", "Running"),
}


def _badge_html(status: str) -> str:
    """Return status badge HTML string."""
    badge_type, label = _STATUS_MAP.get(status, ("neutral", status))
    return status_badge(badge_type, label)


def _run_card_html(run: dict) -> str:
    """Build an HTML summary card for a single pipeline run."""
    status = run["status"]
    badge = _badge_html(status)
    trigger = "Scheduled" if run["trigger"] == "scheduled" else "Manual"
    time_str = run.get("completed_at") or run.get("started_at") or ""
    leads = run.get("leads_exported", 0)
    credits = run.get("credits_used", 0)
    error_html = ""
    if run.get("error_message"):
        error_html = (
            f'<div style="margin-top:{SPACING["xs"]};color:{COLORS["error_light"]};'
            f'font-size:{FONT_SIZES["xs"]};">{run["error_message"]}</div>'
        )

    return (
        f'<div style="display:flex;align-items:center;gap:{SPACING["md"]};'
        f'padding:{SPACING["sm"]} 0;border-bottom:1px solid {COLORS["border"]}40;">'
        f'<div style="flex:0 0 90px;">{badge}</div>'
        f'<div style="flex:1;min-width:0;">'
        f'<span style="color:{COLORS["text_primary"]};font-weight:500;">{trigger}</span>'
        f'<span style="color:{COLORS["text_muted"]};font-size:{FONT_SIZES["sm"]};margin-left:{SPACING["sm"]};">{time_str}</span>'
        f'{error_html}</div>'
        f'<div style="flex:0 0 auto;text-align:right;font-family:\'IBM Plex Mono\',monospace;'
        f'font-size:{FONT_SIZES["sm"]};font-variant-numeric:tabular-nums;">'
        f'<span style="color:{COLORS["text_primary"]};">{leads}</span>'
        f'<span style="color:{COLORS["text_muted"]};"> leads</span>'
        f'<span style="color:{COLORS["text_muted"]};margin:0 {SPACING["xs"]};">·</span>'
        f'<span style="color:{COLORS["text_primary"]};">{credits}</span>'
        f'<span style="color:{COLORS["text_muted"]};"> credits</span>'
        f'</div></div>'
    )


# --- Data ---
runs = db.get_pipeline_runs("intent", limit=50)
auto_config = get_automation_config("intent")
budget_config = get_budget_config("intent")
weekly_cap = budget_config.get("weekly_cap", 500)
weekly_used = db.get_weekly_usage("intent")
budget_pct = min(100, (weekly_used / weekly_cap * 100)) if weekly_cap else 0


# --- Header ---
page_header("Automation", "Daily intent polling · Mon–Fri 7:00 AM ET")


# --- Metrics Row ---
col1, col2, col3 = st.columns(3)

with col1:
    day_label, countdown = _next_scheduled_run()
    metric_card("Next Run", countdown, delta=day_label, delta_color="neutral")

with col2:
    if runs:
        last = runs[0]
        last_time = last.get("completed_at") or last.get("started_at") or "—"
        # Trim to just date + time, drop seconds
        if isinstance(last_time, str) and len(last_time) > 16:
            last_time = last_time[:16]
        st.markdown(_badge_html(last["status"]), unsafe_allow_html=True)
        metric_card("Last Run", last_time)
    else:
        metric_card("Last Run", "—", delta="No runs yet", delta_color="neutral")

with col3:
    metric_card(
        "Weekly Credits",
        f"{weekly_used:,} / {weekly_cap:,}",
        delta=f"{budget_pct:.0f}%",
        delta_color="error" if budget_pct > 80 else "neutral",
    )
    colored_progress_bar(budget_pct)


# --- Run Now ---
labeled_divider("Run Now")

# Show what will run
topics = auto_config.get("topics", [])
target = auto_config.get("target_companies", "?")

now_col1, now_col2 = st.columns([5, 2])
with now_col1:
    st.markdown(
        f"Search **{', '.join(topics)}** intent signals, select top **{target}** "
        f"companies, find contacts, enrich, and email CSV."
    )
with now_col2:
    run_now = st.button(
        "Run Now", type="primary", use_container_width=True, key="auto_run_now",
    )

if run_now and not st.session_state.get("auto_run_triggered"):
    st.session_state["auto_run_triggered"] = True
    with st.spinner("Running intent pipeline..."):
        try:
            from scripts.run_intent_pipeline import run_pipeline
            from scripts._credentials import load_credentials

            creds = load_credentials()
            result = run_pipeline(auto_config, creds, trigger="manual", db=db)

            if result["success"]:
                exported = result.get("summary", {}).get("contacts_exported", 0)
                st.success(f"Pipeline complete — {exported} leads exported.")
                if result.get("batch_id"):
                    st.caption(f"Batch {result['batch_id']}")
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
        hint="Runs appear here after the first scheduled or manual execution.",
    )
else:
    # Render compact run list as HTML for scannable overview
    recent = runs[:10]
    cards_html = "".join(_run_card_html(r) for r in recent)
    st.markdown(
        f'<div style="background:{COLORS["bg_secondary"]};border:1px solid {COLORS["border"]};'
        f'border-radius:10px;padding:{SPACING["sm"]} {SPACING["md"]};">'
        f"{cards_html}</div>",
        unsafe_allow_html=True,
    )

    # Expandable details for each run
    if len(runs) > 0:
        st.markdown("")  # breathing room
        with st.expander(f"Run details ({len(recent)} shown)"):
            for run in recent:
                st.markdown(f"### Run #{run['id']}")
                st.markdown(_badge_html(run["status"]), unsafe_allow_html=True)

                d1, d2 = st.columns(2)
                with d1:
                    st.markdown(f"**Trigger:** {run['trigger']}")
                    if run.get("batch_id"):
                        st.markdown(f"**Batch:** `{run['batch_id']}`")
                    if run.get("error_message"):
                        st.markdown(f"**Error:** `{run['error_message']}`")
                with d2:
                    st.markdown(f"**Credits:** {run.get('credits_used', 0)}")
                    st.markdown(f"**Leads:** {run.get('leads_exported', 0)}")
                    st.markdown(f"**Started:** {run.get('started_at', '—')}")
                    st.markdown(f"**Completed:** {run.get('completed_at', '—')}")

                if run.get("summary"):
                    summary = run["summary"]
                    if isinstance(summary, dict):
                        _kv_parts = []
                        for _k in ("contacts_exported", "credits_used", "companies_found", "errors"):
                            if _k in summary:
                                _kv_parts.append(f"**{_k.replace('_', ' ').title()}:** {summary[_k]}")
                        if _kv_parts:
                            st.markdown(" · ".join(_kv_parts))
                        else:
                            st.json(summary)
                    else:
                        st.json(summary)
                st.divider()

    # Show more indicator
    if len(runs) > 10:
        st.caption(f"{len(runs) - 10} older runs not shown")


# --- Configuration ---
labeled_divider("Configuration")

if not auto_config:
    st.warning("No automation config in `config/icp.yaml` under `automation.intent`")
else:
    with st.expander("Pipeline Configuration (read-only)", expanded=False):
        st.caption("Edit config/icp.yaml to change")

        cfg1, cfg2, cfg3 = st.columns(3)
        with cfg1:
            metric_card("Topics", ", ".join(auto_config.get("topics", [])))
        with cfg2:
            metric_card("Target Companies", auto_config.get("target_companies", "—"))
        with cfg3:
            strengths = auto_config.get("signal_strengths", [])
            metric_card("Signal Strengths", ", ".join(strengths))

        cfg4, cfg5, cfg6 = st.columns(3)
        with cfg4:
            levels = auto_config.get("management_levels", [])
            metric_card("Management Levels", ", ".join(levels))
        with cfg5:
            metric_card("Accuracy Min", auto_config.get("accuracy_min", "—"))
        with cfg6:
            metric_card("Dedup Days", auto_config.get("dedup_days_back", 180))
