"""Automation - Pipeline scheduling and run history."""

import html
import logging
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

from turso_db import get_database
from scoring import build_stale_guidance, score_intent_contacts, get_priority_label
from export import export_leads_to_csv
from utils import get_automation_config, get_budget_config, get_call_center_agents
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

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Automation", page_icon="⚙️", layout="wide")
inject_base_styles()

from utils import require_auth
require_auth()

try:
    db = get_database()
except Exception as e:
    logger.error(f"Failed to connect to database: {e}")
    st.error("Failed to connect to database. Please try again.")
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


_GH_REPO = st.secrets.get("GITHUB_REPO", "andre-sav/HADES")
_GH_WORKFLOW = "intent-poll.yml"


def _get_github_token() -> str | None:
    """Get GitHub token from Streamlit secrets."""
    try:
        return st.secrets.get("GITHUB_TOKEN")
    except Exception:
        return None


def _get_workflow_state(token: str) -> str | None:
    """Get GitHub Actions workflow state ('active' or 'disabled_manually').

    Returns None on API error.
    """
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{_GH_REPO}/actions/workflows/{_GH_WORKFLOW}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("state")
    except Exception:
        logger.debug("GitHub workflow state check failed", exc_info=True)
    return None


def _set_workflow_enabled(token: str, enable: bool) -> bool:
    """Enable or disable the GitHub Actions workflow. Returns True on success."""
    action = "enable" if enable else "disable"
    try:
        resp = requests.put(
            f"https://api.github.com/repos/{_GH_REPO}/actions/workflows/{_GH_WORKFLOW}/{action}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        return resp.status_code == 204
    except Exception:
        logger.debug("GitHub workflow %s failed", action, exc_info=True)
    return False


_STATUS_MAP = {
    "success": ("success", "Success"),
    "failed": ("error", "Failed"),
    "skipped": ("warning", "Skipped"),
    "running": ("info", "Running"),
}


def _friendly_error(msg: str) -> str:
    """Map raw error messages to user-friendly labels."""
    if not msg:
        return ""
    _patterns = {
        "unhashable type": "Data format error",
        "429": "Rate limit exceeded",
        "timeout": "Request timed out",
        "connection": "Connection error",
        "401": "Authentication failed",
        "403": "Access denied",
    }
    lower = msg.lower()
    for pattern, label in _patterns.items():
        if pattern in lower:
            return label
    # Truncate long raw messages and escape for HTML safety
    truncated = msg[:80] + "..." if len(msg) > 80 else msg
    return html.escape(truncated)


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
    context_html = ""
    if run.get("error_message"):
        friendly = _friendly_error(run["error_message"])
        context_html = (
            f'<div style="margin-top:{SPACING["xs"]};color:{COLORS["error_light"]};'
            f'font-size:{FONT_SIZES["xs"]};">{friendly}</div>'
        )
    elif status == "success" and leads == 0:
        context_html = (
            f'<div style="margin-top:{SPACING["xs"]};color:{COLORS["text_muted"]};'
            f'font-size:{FONT_SIZES["xs"]};">No new intent signals matched filters</div>'
        )

    return (
        f'<div style="display:flex;align-items:center;gap:{SPACING["md"]};'
        f'padding:{SPACING["sm"]} 0;border-bottom:1px solid {COLORS["border"]}40;">'
        f'<div style="flex:0 0 90px;">{badge}</div>'
        f'<div style="flex:1;min-width:0;">'
        f'<span style="color:{COLORS["text_primary"]};font-weight:500;">{trigger}</span>'
        f'<span style="color:{COLORS["text_muted"]};font-size:{FONT_SIZES["sm"]};margin-left:{SPACING["sm"]};">{time_str}</span>'
        f'{context_html}</div>'
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

# --- Schedule Toggle ---
_gh_token = _get_github_token()
_wf_state = _get_workflow_state(_gh_token) if _gh_token else None
if _gh_token and _wf_state is not None:
        _is_active = _wf_state == "active"
        _toggle_col1, _toggle_col2 = st.columns([1, 5])
        with _toggle_col1:
            _new_state = st.toggle(
                "Schedule enabled",
                value=_is_active,
                key="auto_schedule_toggle",
            )
        with _toggle_col2:
            if _is_active:
                st.caption("Daily pipeline runs Mon–Fri at 7:00 AM ET")
            else:
                st.caption("Schedule paused — only manual runs via Run Now")

        if _new_state != _is_active:
            if _set_workflow_enabled(_gh_token, _new_state):
                st.rerun()
            else:
                st.error("Failed to update workflow — check GITHUB_TOKEN permissions")


# --- Metrics Row ---
col1, col2, col3 = st.columns(3)

with col1:
    day_label, countdown = _next_scheduled_run()
    if _wf_state == "disabled_manually":
        metric_card("Next Run", "Paused", delta="Schedule disabled", delta_color="error")
    else:
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

@st.dialog("Confirm Pipeline Run")
def confirm_run_now_dialog(topics, target):
    st.write("Run intent pipeline now?")
    st.write(f"Search **{', '.join(topics)}** signals, find top **{target}** companies, enrich contacts, email CSV.")
    st.caption("Credits will be consumed from your weekly budget.")
    st.markdown("")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Run", type="primary", use_container_width=True):
            st.session_state["auto_run_confirmed"] = True
            st.rerun()
    with col_no:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


labeled_divider("Run Now")

# Show what will run
topics = auto_config.get("topics", [])
target = auto_config.get("target_companies", "?")

now_col1, now_col2, now_col3 = st.columns([5, 1, 1])
with now_col1:
    st.markdown(
        f"Search **{', '.join(topics)}** intent signals, select top **{target}** "
        f"companies, find contacts, enrich, and email CSV."
    )
with now_col2:
    dry_run = st.button(
        "Dry Run", use_container_width=True, key="auto_dry_run",
    )
with now_col3:
    run_now = st.button(
        "Run Now", type="primary", use_container_width=True, key="auto_run_now",
    )

# Execute dry run
if dry_run:
    try:
        with st.spinner("Running preview..."):
            from scripts.run_intent_pipeline import run_pipeline
            from scripts._credentials import load_credentials

            creds = load_credentials()
            result = run_pipeline(auto_config, creds, dry_run=True, db=db)

            if result["success"]:
                st.session_state["dry_run_result"] = result["summary"]
                st.rerun()
            else:
                st.error(f"Preview failed: {result.get('error', 'Unknown error')}")
    except Exception as e:
        logger.error(f"Dry run error: {e}")
        st.error("Preview failed. Please try again or check the logs.")

# Render dry-run preview
if "dry_run_result" in st.session_state:
    preview = st.session_state["dry_run_result"]

    st.markdown("")
    st.markdown(
        f'<div style="background:{COLORS["bg_secondary"]};border:1px solid {COLORS["border"]};'
        f'border-radius:10px;padding:{SPACING["md"]};">',
        unsafe_allow_html=True,
    )

    st.markdown("**Preview Results**")

    p1, p2, p3, p4 = st.columns(4)
    with p1:
        metric_card("Intent Results", preview.get("intent_results", 0))
    with p2:
        metric_card("Scored (non-stale)", preview.get("scored_results", 0))
    with p3:
        metric_card("After Dedup", preview.get("scored_results", 0) - preview.get("dedup_filtered", 0))
    with p4:
        metric_card("Would Select", preview.get("companies_selected", 0))

    # Estimated credits
    est_credits = preview.get("companies_selected", 0)
    remaining = weekly_cap - weekly_used
    if est_credits > 0:
        credit_color = COLORS["error_light"] if est_credits > remaining else COLORS["text_muted"]
        st.markdown(
            f'<div style="color:{credit_color};font-size:{FONT_SIZES["sm"]};margin-top:{SPACING["xs"]};">'
            f'Estimated credits: ~{est_credits} of {remaining:,} remaining'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Stale guidance — shown when intent results exist but all scored out
    if preview.get("intent_results", 0) > 0 and preview.get("scored_results", 0) == 0:
        _stale_summ = preview.get("stale_summary", {})
        _guidance = build_stale_guidance(
            _stale_summ,
            preview.get("topics", []),
            preview.get("signal_strengths", []),
        )

        _n = preview["intent_results"]
        st.warning(f"All {_n} intent results are stale (>14 days old). No companies survived freshness scoring.")

        if _guidance:
            _items = "".join(
                f'<div style="padding:{SPACING["xs"]} 0;color:{COLORS["text_secondary"]};">'
                f'<span style="color:{COLORS["warning"]};margin-right:{SPACING["xs"]};">→</span>'
                f'{html.escape(g)}</div>'
                for g in _guidance
            )
            st.markdown(
                f'<div style="background:{COLORS["bg_tertiary"]};border-left:3px solid {COLORS["warning_dark"]};'
                f'border-radius:0 6px 6px 0;padding:{SPACING["sm"]} {SPACING["md"]};margin-top:{SPACING["xs"]};">'
                f'<div style="font-size:{FONT_SIZES["xs"]};color:{COLORS["text_muted"]};'
                f'text-transform:uppercase;letter-spacing:0.05em;margin-bottom:{SPACING["xs"]};">Try next</div>'
                f'{_items}</div>',
                unsafe_allow_html=True,
            )

    # Top companies table
    top_cos = preview.get("top_companies", [])
    if top_cos:
        st.markdown(f"**Top {len(top_cos)} Companies**")
        header = (
            f'<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:{SPACING["xs"]};'
            f'padding:{SPACING["xs"]} 0;border-bottom:1px solid {COLORS["border"]};'
            f'color:{COLORS["text_muted"]};font-size:{FONT_SIZES["xs"]};">'
            f'<div>Company</div><div>Score</div><div>Topic</div><div>Strength</div></div>'
        )
        rows = "".join(
            f'<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:{SPACING["xs"]};'
            f'padding:{SPACING["xs"]} 0;border-bottom:1px solid {COLORS["border"]}40;'
            f'font-size:{FONT_SIZES["sm"]};">'
            f'<div style="color:{COLORS["text_primary"]};">{html.escape(co.get("companyName", ""))}</div>'
            f'<div style="color:{COLORS["text_primary"]};font-family:\'IBM Plex Mono\',monospace;">'
            f'{co.get("_score", 0)}</div>'
            f'<div style="color:{COLORS["text_muted"]};">{html.escape(co.get("intentTopic", ""))}</div>'
            f'<div>{status_badge("success" if co.get("intentStrength") == "High" else "warning", co.get("intentStrength", ""))}</div>'
            f'</div>'
            for co in top_cos[:5]
        )
        st.markdown(header + rows, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Action buttons
    act1, act2, _ = st.columns([1, 1, 4])
    with act1:
        if st.button("Run Full Pipeline", type="primary", key="dry_run_proceed"):
            del st.session_state["dry_run_result"]
            confirm_run_now_dialog(topics, target)
    with act2:
        if st.button("Dismiss", key="dry_run_dismiss"):
            del st.session_state["dry_run_result"]
            st.rerun()

# Open dialog on button click
if run_now:
    confirm_run_now_dialog(topics, target)

# Execute pipeline only after dialog confirmation
if st.session_state.pop("auto_run_confirmed", False) and not st.session_state.get("auto_run_triggered"):
    st.session_state["auto_run_triggered"] = True
    try:
        with st.spinner("Running intent pipeline..."):
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
        logger.error(f"Pipeline error: {e}")
        st.error("Pipeline error. Please try again or check the logs.")
    finally:
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
                    _detail_leads = run.get('leads_exported', 0)
                    st.markdown(f"**Leads:** {_detail_leads}")
                    if run["status"] == "success" and _detail_leads == 0:
                        st.caption("No new intent signals matched filters")
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

                # Re-export button for successful runs with a batch ID
                if run["status"] == "success" and run.get("batch_id") and run.get("leads_exported", 0) > 0:
                    if st.button(
                        f"Re-export {run['leads_exported']} leads",
                        key=f"reexport_{run['id']}",
                    ):
                        st.session_state["_reexport_batch_id"] = run["batch_id"]
                        st.session_state["_reexport_run_id"] = run["id"]
                        st.rerun()

                st.divider()

    # Show more indicator
    if len(runs) > 10:
        st.caption(f"{len(runs) - 10} older runs not shown")

# --- Re-export execution ---
_reexport_batch = st.session_state.pop("_reexport_batch_id", None)
st.session_state.pop("_reexport_run_id", None)
if _reexport_batch:
    st.markdown("---")
    outcomes = db.get_outcomes_by_batch(_reexport_batch)
    person_ids = [o["person_id"] for o in outcomes if o.get("person_id")]

    if not person_ids:
        st.error(f"No person IDs found for batch {_reexport_batch}")
    else:
        with st.status(f"Re-enriching {len(person_ids)} contacts from batch {_reexport_batch}...", expanded=True) as reexport_status:
            try:
                from zoominfo_client import get_zoominfo_client, DEFAULT_ENRICH_OUTPUT_FIELDS

                st.write(f"Found {len(person_ids)} person IDs in lead_outcomes")
                client = get_zoominfo_client()
                enriched = client.enrich_contacts_batch(
                    person_ids=person_ids,
                    output_fields=DEFAULT_ENRICH_OUTPUT_FIELDS,
                )
                st.write(f"Enriched {len(enriched)} contacts")

                # Restore scores and metadata from lead_outcomes
                outcome_by_pid = {o["person_id"]: o for o in outcomes}
                for contact in enriched:
                    pid = str(contact.get("id") or contact.get("personId") or "")
                    outcome = outcome_by_pid.get(pid, {})
                    contact["_score"] = outcome.get("hades_score", 50)
                    contact["_priority"] = get_priority_label(contact["_score"])
                    contact["_lead_source"] = f"ZoomInfo Intent (re-export {_reexport_batch})"
                    # Restore fields enrichment may not return
                    if not contact.get("sicCode") and outcome.get("sic_code"):
                        contact["sicCode"] = outcome["sic_code"]
                    if not contact.get("employees") and outcome.get("employee_count"):
                        contact["employees"] = outcome["employee_count"]

                # Stage for CSV Export page
                db.save_staged_export(
                    workflow_type="intent",
                    leads=enriched,
                    query_params={"re_export_batch": _reexport_batch},
                )
                staged_rows = db.get_staged_exports(limit=1)
                if staged_rows:
                    db.mark_staged_exported(staged_rows[0]["id"], _reexport_batch)

                st.write(f"Staged {len(enriched)} leads for export")
                reexport_status.update(
                    label=f"Re-exported {len(enriched)} leads — go to CSV Export to download",
                    state="complete",
                )
                st.page_link("pages/4_CSV_Export.py", label="Open CSV Export", icon="📤")

            except Exception as e:
                reexport_status.update(label="Re-export failed", state="error")
                logger.exception("Re-export failed")
                st.error("Re-export failed. Check application logs for details.")


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
