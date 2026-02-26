"""
Intent Workflow - Full pipeline: Find intent companies → Select → Find contacts → Export.

Pipeline: Intent Search → Select Companies → Resolve company IDs → Contact Search (ICP filters) → Enrich → Score → Export
Dual mode: Autopilot (auto-select) and Manual Review (user selects companies + contacts).
"""

import hashlib
import html
import json
import logging

import streamlit as st
import pandas as pd

# Configure logging for pipeline visibility
logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Also ensure library loggers are at INFO so their messages show
for _lib in ("scoring", "dedup", "expand_search", "zoominfo_client"):
    _lib_logger = logging.getLogger(_lib)
    if not _lib_logger.handlers:
        _lib_logger.addHandler(_handler)
        _lib_logger.setLevel(logging.INFO)
from datetime import datetime

from turso_db import get_database
from errors import PipelineError
from zoominfo_client import (
    get_zoominfo_client,
    IntentQueryParams,
    ContactQueryParams,
    DEFAULT_ENRICH_OUTPUT_FIELDS,
)
from scoring import (
    score_intent_leads,
    score_intent_contacts,
    get_priority_label,
    get_priority_action,
    calculate_age_days,
    compute_stale_summary,
    build_stale_guidance,
)
from dedup import dedupe_leads
from cost_tracker import CostTracker
from expand_search import build_contacts_by_company
from db._title_prefs import normalize_title
from utils import (
    get_intent_topics,
    get_sic_codes,
    get_sic_codes_with_descriptions,
    get_employee_minimum,
    get_employee_maximum,
    get_default_accuracy,
    get_default_management_levels,
    get_default_phone_fields,
)
from ui_components import (
    inject_base_styles,
    page_header,
    step_indicator,
    status_badge,
    metric_card,
    parameter_group,
    paginate_items,
    pagination_controls,
    export_quality_warnings,
    score_breakdown,
    workflow_run_state,
    action_bar,
    workflow_summary_strip,
    last_run_indicator,
    format_contact_label,
    destructive_button,
    outline_button,
    COLORS,
    FONT_SIZES,
    SPACING,
)

st.set_page_config(page_title="Intent", page_icon="🎯", layout="wide")

# Apply design system styles
inject_base_styles()

from utils import require_auth
require_auth()


# Initialize services
@st.cache_resource(ttl=3600)
def get_services():
    db = get_database()
    return db, CostTracker(db)


try:
    db, cost_tracker = get_services()
except Exception as e:
    logger.error(f"Failed to initialize: {e}")
    st.error("Failed to initialize. Please refresh the page.")
    st.stop()


# =============================================================================
# SESSION STATE
# =============================================================================
defaults = {
    "intent_mode": "autopilot",
    "intent_test_mode": False,
    # Step 1: Intent search
    "intent_companies": None,  # Scored company results
    "intent_search_executed": False,
    "intent_search_pending": False,  # Two-phase: set True → rerun → execute
    "intent_query_params": None,
    # Step 2: Company selection (Manual mode)
    "intent_selected_companies": {},  # company_id -> company_dict
    "intent_companies_confirmed": False,
    # Step 3: Contact search + enrichment
    "intent_contacts_by_company": None,
    "intent_selected_contacts": {},  # company_id -> selected_contact
    "intent_enrich_clicked": False,  # Gate for manual mode enrichment
    "intent_enriched_contacts": None,
    "intent_enrichment_done": False,
    "intent_usage_logged": False,
    "intent_leads_staged": False,
    # Step 4: Final results
    "intent_results": None,
    "intent_export_leads": None,
    # Export tracking
    "intent_exported": False,
    # Filters
    "intent_state_filter": [],
}
for key, default in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default


def _intent_cache_key(topics: list[str], signal_strengths: list[str]) -> str:
    """Generate a deterministic cache key from intent search parameters."""
    normalized = json.dumps(
        {"topics": sorted(topics), "signals": sorted(signal_strengths)},
        sort_keys=True,
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# =============================================================================
# HEADER
# =============================================================================
budget = cost_tracker.format_budget_display("intent")
if budget["has_cap"]:
    remaining = budget["remaining"]
    pct = budget["percent"]
    if pct >= 95:
        badge = status_badge("error", f"{remaining:,} left")
    elif pct >= 80:
        badge = status_badge("warning", f"{remaining:,} left")
    elif pct >= 50:
        badge = status_badge("neutral", f"{remaining:,} left")
    else:
        badge = status_badge("success", f"{remaining:,} left")
    page_header(
        title="Intent",
        caption="Find contacts at companies showing intent signals",
        right_content=(badge, f"{budget['display']}"),
    )
else:
    page_header(
        title="Intent",
        caption="Find contacts at companies showing intent signals",
    )


# =============================================================================
# LAST RUN INDICATOR
# =============================================================================
_last_intent = db.get_last_query("intent")
last_run_indicator(_last_intent)


# =============================================================================
# MODE SELECTOR
# =============================================================================
mode_col1, mode_col2, mode_col3 = st.columns([1, 2, 1])

with mode_col1:
    _MODE_MAP = {"Autopilot": "autopilot", "Manual Review": "manual"}
    _MODE_REVERSE = {v: k for k, v in _MODE_MAP.items()}
    _mode_tab = st.segmented_control(
        "Mode",
        options=list(_MODE_MAP.keys()),
        default=_MODE_REVERSE.get(st.session_state.intent_mode, "Autopilot"),
        key="intent_mode_tabs",
        label_visibility="collapsed",
    )
    if _mode_tab is not None:
        st.session_state.intent_mode = _MODE_MAP.get(_mode_tab, st.session_state.intent_mode)

with mode_col2:
    if st.session_state.intent_mode == "autopilot":
        st.info("**Autopilot**: Search → Auto-select top companies → Find best contacts → Export", icon="🤖")
    else:
        st.info("**Manual**: Search → Select companies → Review contacts → Export", icon="👤")

with mode_col3:
    st.session_state.intent_test_mode = st.toggle("Test Mode", value=st.session_state.intent_test_mode, key="intent_test_mode_switch")
    if st.session_state.intent_test_mode:
        st.caption("⚠️ Using mock data")


# =============================================================================
# ACTION BAR + SUMMARY STRIP (only shown after search)
# =============================================================================
_run_state = workflow_run_state("intent")

if _run_state != "idle":
    # Build contextual action bar
    _ab_primary = None
    _ab_primary_key = None
    _ab_secondary = None
    _ab_secondary_key = None
    _ab_metrics = []

    if _run_state == "enriched" and st.session_state.intent_results:
        _ab_metrics = [{"label": "Leads", "value": len(st.session_state.intent_results)}]
        _ab_primary = "Export CSV"
        _ab_primary_key = "ab_intent_export"
    elif _run_state == "contacts_found":
        cbc = st.session_state.intent_contacts_by_company or {}
        _ab_metrics = [{"label": "Companies", "value": len(cbc)}]
    elif _run_state == "searched" and st.session_state.intent_companies:
        _ab_metrics = [{"label": "Companies", "value": len(st.session_state.intent_companies)}]
    elif _run_state == "exported":
        _ab_metrics = [{"label": "Status", "value": "Exported"}]

    _ab_primary_clicked, _ab_secondary_clicked = action_bar(
        _run_state,
        primary_label=_ab_primary,
        primary_key=_ab_primary_key,
        secondary_label=_ab_secondary,
        secondary_key=_ab_secondary_key,
        metrics=_ab_metrics,
    )

    if _ab_primary_clicked and _run_state == "enriched":
        st.switch_page("pages/4_CSV_Export.py")

    # Summary strip
    _strip_items = []
    _strip_items.append({"label": "Mode", "value": "Autopilot" if st.session_state.intent_mode == "autopilot" else "Manual"})
    if st.session_state.intent_companies:
        _strip_items.append({"label": "Companies", "value": len(st.session_state.intent_companies)})
    if st.session_state.intent_enrichment_done and st.session_state.intent_results:
        _strip_items.append({"label": "Contacts", "value": len(st.session_state.intent_results)})
    elif st.session_state.intent_contacts_by_company:
        _total_contacts = sum(len(d["contacts"]) for d in st.session_state.intent_contacts_by_company.values())
        _strip_items.append({"label": "Contacts", "value": _total_contacts})
    if budget["has_cap"]:
        _strip_items.append({"label": "Budget", "value": budget["display"]})

    if len(_strip_items) > 1:
        workflow_summary_strip(_strip_items)


# =============================================================================
# STEP INDICATOR
# =============================================================================
def get_current_step() -> int:
    is_manual = st.session_state.intent_mode == "manual"
    total = 4 if is_manual else 3
    if st.session_state.intent_enrichment_done:
        return total + 1  # All steps completed
    if st.session_state.intent_contacts_by_company:
        return 3 if is_manual else 2
    if st.session_state.intent_companies_confirmed or (
        not is_manual and st.session_state.intent_selected_companies
    ):
        return 3 if is_manual else 2
    if st.session_state.intent_companies:
        return 2 if is_manual else 1
    return 1


current_step = get_current_step()

if st.session_state.intent_mode == "autopilot":
    step_indicator(current_step, 3, ["Search", "Find Contacts", "Results"])
else:
    step_indicator(current_step, 4, ["Search", "Select Companies", "Find Contacts", "Results"])


# =============================================================================
# STEP 1: SEARCH INTENT COMPANIES
# =============================================================================
# When results are showing, collapse earlier pipeline steps into a summary
_results_showing = st.session_state.intent_enrichment_done and st.session_state.intent_enriched_contacts

# Default variable values — used when form is hidden (results showing)
selected_topics = []
signal_strengths = []
intent_mgmt_levels = ["Manager"]
intent_accuracy_min = get_default_accuracy()
intent_phone_fields = get_default_phone_fields()
target_companies = 25
search_clicked = False
_is_pending = st.session_state.intent_search_pending

if _results_showing:
    _qp = st.session_state.get("intent_query_params") or {}
    _s1_topics = ", ".join(_qp.get("topics", []))
    _s1_signals = ", ".join(_qp.get("signal_strengths", []))
    _s1_count = len(st.session_state.intent_companies or [])
    _sel_count = len(st.session_state.intent_selected_companies)
    with st.expander(f"Pipeline: {_s1_topics} ({_s1_signals}) — {_s1_count} companies, {_sel_count} selected", expanded=False):
        st.caption(f"Topics: {_s1_topics} | Signal: {_s1_signals} | Found: {_s1_count} | Selected: {_sel_count}")
else:
    st.subheader("Step 1 — Search Intent Companies")

    col1, col2 = st.columns([3, 2])

    with col1:
        topics_config = get_intent_topics()
        available_topics = topics_config.get("primary", []) + topics_config.get("expansion", [])

        selected_topics = st.multiselect(
            "Topics",
            options=available_topics,
            default=["Vending Machines"] if "Vending Machines" in available_topics else [],
            placeholder="Select intent topics...",
        )

    with col2:
        signal_strengths = st.multiselect(
            "Signal Strength",
            options=["High", "Medium", "Low"],
            default=["High"],
            placeholder="Select signal strengths...",
        )

    # Intent Search Filters (read-only)
    _sic_count = len(get_sic_codes_with_descriptions())
    with parameter_group("Intent Search Filters", f"{get_employee_minimum():,}–{get_employee_maximum():,} employees · {_sic_count} SIC codes"):
        st.caption(f"Minimum employees: {get_employee_minimum():,}")
        st.caption(f"Maximum employees: {get_employee_maximum():,}")
        sic_with_names = get_sic_codes_with_descriptions()
        st.caption(f"SIC codes: {len(sic_with_names)} industries")
        with st.popover("View SIC codes"):
            for code, desc in sic_with_names:
                st.caption(f"**{code}** — {desc}")

    # Contact Search Filters (editable)
    with parameter_group("Contact Search Filters", "Manager+ · 95 accuracy · any phone"):
        intent_mgmt_levels = st.multiselect(
            "Management level",
            options=["Manager", "Director", "VP Level Exec", "C Level Exec"],
            default=get_default_management_levels(),
            key="intent_mgmt_levels",
        )
        intent_accuracy_min = st.number_input(
            "Accuracy minimum",
            min_value=0,
            max_value=100,
            value=get_default_accuracy(),
            step=5,
            key="intent_accuracy_min",
        )
        intent_phone_fields = st.multiselect(
            "Required phone fields",
            options=["mobilePhone", "directPhone", "phone"],
            default=get_default_phone_fields(),
            key="intent_phone_fields",
            help="Contact must have at least one selected phone type",
        )

    # Query Preview (shown when parameters are selected)
    can_query = len(selected_topics) > 0 and len(signal_strengths) > 0
    if can_query:
        _strength_to_score_preview = {"High": 90, "Medium": 75, "Low": 60}
        _min_score = min(_strength_to_score_preview.get(s, 60) for s in signal_strengths)
        _preview_parts = [
            f"<strong>Topics</strong>: {html.escape(', '.join(selected_topics))}",
            f"<strong>Signal</strong>: {html.escape(', '.join(signal_strengths))} (score >= {_min_score})",
            f"<strong>Employees</strong>: {get_employee_minimum():,}–{get_employee_maximum():,}",
            f"<strong>Industries</strong>: {len(get_sic_codes())} SIC codes",
        ]
        st.markdown(
            f'<p style="font-size:0.875rem;color:#8b929e;margin:0;">{" · ".join(_preview_parts)}</p>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # Target companies input
    _is_pending = st.session_state.intent_search_pending
    search_clicked = False
    target_col1, target_col2, target_col3 = st.columns([1, 1, 2])
    with target_col1:
        target_companies = st.number_input(
            "Target companies",
            min_value=5,
            max_value=100,
            value=25,
            step=5,
            help="Number of top companies to select for contact search.",
            disabled=_is_pending,
        )
    with target_col2:
        _budget_exceeded = budget.get("has_cap") and budget.get("percent", 0) >= 100
        if _is_pending:
            # Show Cancel button in the same position as Search during search
            if destructive_button("Cancel Search", key="intent_cancel_btn"):
                st.session_state.intent_search_pending = False
                st.rerun()
        else:
            search_clicked = st.button(
                "Search Companies" if not _budget_exceeded else "Budget Exceeded",
                type="primary",
                use_container_width=True,
                disabled=not can_query or _budget_exceeded,
            )

    # Reset button (after results)
    if st.session_state.intent_search_executed:
        with target_col3:
            if destructive_button("Reset", key="intent_reset_btn"):
                for key in defaults:
                    st.session_state[key] = defaults[key]
                st.rerun()


# --- Execute Intent Search ---
# Phase 1: Button click sets pending flag and reruns (so Cancel button renders)
if not _is_pending and search_clicked:
    budget_status = cost_tracker.check_budget("intent", 100)
    if budget_status.alert_level == "exceeded":
        st.error("Weekly budget exceeded")
        st.stop()
    if budget_status.alert_level in ("warning", "critical"):
        st.warning(budget_status.alert_message)
    st.session_state.intent_search_pending = True
    st.session_state["_intent_pending_params"] = {
        "topics": selected_topics,
        "signal_strengths": signal_strengths,
        "target_companies": target_companies,
        "management_levels": intent_mgmt_levels,
        "accuracy_min": intent_accuracy_min,
        "phone_fields": intent_phone_fields,
    }
    st.rerun()

# Phase 2: Pending flag is set — execute the actual search (Cancel is now visible)
if st.session_state.intent_search_pending:
    _pending = st.session_state.get("_intent_pending_params", {})
    _p_topics = _pending.get("topics", selected_topics)
    _p_signals = _pending.get("signal_strengths", signal_strengths)
    _p_target = _pending.get("target_companies", target_companies)

    logger.info("Intent search starting: topics=%s, signals=%s, target=%d", _p_topics, _p_signals, _p_target)

    # Cache-first lookup
    _cache_key = _intent_cache_key(_p_topics, _p_signals)
    _force_refresh = st.session_state.get("_intent_force_refresh", False)
    st.session_state["_intent_force_refresh"] = False  # reset flag

    cached_leads = None if _force_refresh else db.get_cached_results(_cache_key)

    if cached_leads is not None:
        # Cache hit — use cached results directly
        logger.info("Cache HIT: %d raw leads from cache", len(cached_leads))
        st.session_state["_intent_from_cache"] = True
        st.session_state["_intent_api_response_summary"] = {"total_results": len(cached_leads)}
        st.session_state.pop("_intent_stale_summary", None)
        scored = score_intent_leads(cached_leads)
        if not scored:
            st.session_state["_intent_stale_summary"] = compute_stale_summary(cached_leads)
        deduped, removed = dedupe_leads(scored)

        for lead in deduped:
            topic = lead.get("intentTopic", _p_topics[0] if _p_topics else "")
            score = lead.get("_score", 0)
            age = calculate_age_days(lead.get("intentDate"))
            lead["_lead_source"] = f"ZoomInfo Intent - {topic} - {score} - {age}d"
            lead["_priority"] = get_priority_label(score)
            lead["_priority_action"] = get_priority_action(score)

        st.session_state.intent_companies = deduped
        st.session_state.intent_search_executed = True
        st.session_state.intent_search_pending = False
        st.session_state.intent_query_params = {
            **_pending,
            "mode": st.session_state.intent_mode,
        }
        st.session_state["_intent_dedup_removed"] = removed

        # Log cache hit (credits=0) so it appears in Usage Dashboard
        cost_tracker.log_usage(
            workflow_type="intent",
            query_params=st.session_state.intent_query_params,
            credits_used=0,
            leads_returned=len(deduped),
        )
        db.log_query(
            workflow_type="intent",
            query_params=st.session_state.intent_query_params,
            leads_returned=len(deduped),
        )

        # In autopilot, auto-select top N
        if st.session_state.intent_mode == "autopilot":
            top_n = deduped[:_p_target]
            auto_selected = {}
            for lead in top_n:
                cid = str(lead.get("companyId", ""))
                if cid:
                    auto_selected[cid] = lead
            st.session_state.intent_selected_companies = auto_selected
            logger.info("Autopilot auto-selected %d/%d companies", len(auto_selected), len(deduped))
            if auto_selected:
                st.session_state.intent_companies_confirmed = True

        logger.info("Intent search complete (cached): %d companies ready", len(deduped))
        st.rerun()

    else:
        # Cache miss — call API
        logger.info("Cache MISS: querying ZoomInfo Intent API")
        st.session_state["_intent_from_cache"] = False
        with st.status("Searching for intent companies...", expanded=True) as status:
            try:
                client = get_zoominfo_client()
                params = IntentQueryParams(
                    topics=_p_topics,
                    signal_strengths=_p_signals,
                    employee_min=get_employee_minimum(),
                    sic_codes=get_sic_codes(),
                )

                # Build request body for display (mirrors search_intent logic)
                _strength_to_score = {"High": 90, "Medium": 75, "Low": 60}
                _display_body = {
                    "topics": params.topics,
                    "rpp": params.page_size,
                    "page": params.page,
                }
                if params.signal_strengths:
                    _display_body["signalScoreMin"] = min(_strength_to_score.get(s, 60) for s in params.signal_strengths)
                if params.employee_min:
                    _display_body["employeeRangeMin"] = str(params.employee_min)
                if params.sic_codes:
                    _display_body["sicCodes"] = f"[{len(params.sic_codes)} codes]"

                st.session_state["_intent_api_request"] = {
                    "method": "POST",
                    "endpoint": "/search/intent",
                    "body": _display_body,
                    "query_params": None,
                }

                def _intent_page_progress(current_page, total_pages):
                    status.update(label=f"Querying Intent API — page {current_page}/{total_pages}")
                    st.write(f"Fetched page {current_page} of {total_pages}")

                st.write("Querying ZoomInfo Intent API...")
                leads = client.search_intent_all_pages(params, max_pages=5, progress_callback=_intent_page_progress)

                st.session_state["_intent_api_response_summary"] = {
                    "total_results": len(leads),
                    "sample": leads[:3] if leads else [],
                    "raw_keys": getattr(client, "_last_intent_raw_keys", []),
                    "raw_sample": getattr(client, "_last_intent_raw_sample", {}),
                }

                # Check if user cancelled during the API call
                if not st.session_state.intent_search_pending:
                    logger.info("Intent search cancelled by user")
                    status.update(label="Search cancelled", state="error")
                    st.stop()

                if not leads:
                    logger.info("Intent search returned 0 results")
                    st.write("No companies found matching criteria.")
                    st.session_state.intent_companies = None
                    st.session_state.intent_search_executed = True
                    st.session_state.intent_search_pending = False
                    status.update(label="No results found", state="complete")
                else:
                    logger.info("Intent API returned %d raw companies", len(leads))
                    st.write(f"Found {len(leads)} companies. Scoring...")
                    # Cache raw leads for future lookups
                    db.cache_results(
                        cache_id=_cache_key,
                        workflow_type="intent",
                        query_params={"topics": _p_topics, "signal_strengths": _p_signals},
                        leads=leads,
                    )

                    st.session_state.pop("_intent_stale_summary", None)
                    scored = score_intent_leads(leads)
                    if not scored:
                        st.session_state["_intent_stale_summary"] = compute_stale_summary(leads)
                    st.write(f"Scored: {len(scored)}/{len(leads)} survived freshness filter. Deduplicating...")
                    deduped, removed = dedupe_leads(scored)

                    for lead in deduped:
                        topic = lead.get("intentTopic", _p_topics[0] if _p_topics else "")
                        score = lead.get("_score", 0)
                        age = calculate_age_days(lead.get("intentDate"))
                        lead["_lead_source"] = f"ZoomInfo Intent - {topic} - {score} - {age}d"
                        lead["_priority"] = get_priority_label(score)
                        lead["_priority_action"] = get_priority_action(score)

                    st.session_state.intent_companies = deduped
                    st.session_state.intent_search_executed = True
                    st.session_state.intent_search_pending = False
                    st.session_state.intent_query_params = {
                        **_pending,
                        "mode": st.session_state.intent_mode,
                    }
                    st.session_state["_intent_dedup_removed"] = removed

                    st.session_state["_intent_api_response_summary"]["after_scoring"] = {
                        "scored": len(scored),
                        "deduped": len(deduped),
                        "removed": removed,
                    }

                    # Log intent search usage (search is free — credits only on enrich)
                    cost_tracker.log_usage(
                        workflow_type="intent",
                        query_params=st.session_state.intent_query_params,
                        credits_used=0,
                        leads_returned=len(deduped),
                    )
                    db.log_query(
                        workflow_type="intent",
                        query_params=st.session_state.intent_query_params,
                        leads_returned=len(deduped),
                    )

                    # In autopilot, auto-select top N
                    if st.session_state.intent_mode == "autopilot":
                        top_n = deduped[:_p_target]
                        auto_selected = {}
                        for lead in top_n:
                            cid = str(lead.get("companyId", ""))
                            if cid:
                                auto_selected[cid] = lead
                        st.session_state.intent_selected_companies = auto_selected
                        logger.info("Autopilot auto-selected %d/%d companies", len(auto_selected), len(deduped))
                        if auto_selected:
                            st.session_state.intent_companies_confirmed = True

                    _summary = f"{len(leads)} raw → {len(scored)} scored → {len(deduped)} deduped"
                    if removed:
                        _summary += f" ({removed} duplicates removed)"
                    st.write(_summary)
                    logger.info("Intent search complete (API): %s", _summary)
                    status.update(label=f"Found {len(deduped)} companies", state="complete")
                    st.rerun()

            except PipelineError as e:
                logger.error("Intent search failed: %s", e.user_message)
                st.session_state.intent_search_pending = False
                st.session_state["_intent_api_error"] = str(e.user_message)
                st.session_state["_intent_api_exchange"] = getattr(client, "last_exchange", None)
                status.update(label="Search failed", state="error")
                st.error(e.user_message)
                try:
                    db.log_error(
                        workflow_type="intent",
                        error_type=type(e).__name__,
                        user_message=e.user_message,
                        technical_message=str(e),
                        recoverable=e.recoverable,
                    )
                except Exception:
                    pass  # Never let error logging cause secondary failures
            except Exception:
                st.session_state.intent_search_pending = False
                st.session_state["_intent_api_error"] = "An unexpected error occurred"
                try:
                    st.session_state["_intent_api_exchange"] = getattr(client, "last_exchange", None)
                except Exception:
                    pass
                logger.exception("Intent search failed")
                status.update(label="Search failed", state="error")
                st.error("An unexpected error occurred. Check application logs for details.")

# --- API Request / Response Debug Panel (hidden when results showing) ---
_has_debug = not _results_showing and (
    st.session_state.get("_intent_api_request")
    or st.session_state.get("_intent_api_error")
    or st.session_state.get("_intent_api_exchange")
)
if _has_debug:
    with st.expander("API Request / Response", expanded=bool(st.session_state.get("_intent_api_error"))):
        exchange = st.session_state.get("_intent_api_exchange")
        req_preview = st.session_state.get("_intent_api_request")

        # --- Request ---
        st.markdown("#### Request")
        if exchange and exchange.get("request"):
            ex_req = exchange["request"]
            st.markdown(f"**{ex_req['method']}** `{ex_req['url']}`")
            if ex_req.get("query_params"):
                st.caption("Query parameters:")
                st.code(json.dumps(ex_req["query_params"], indent=2, default=str), language="json")
            if ex_req.get("body"):
                st.caption("Request body:")
                st.code(json.dumps(ex_req["body"], indent=2, default=str), language="json")
        elif req_preview:
            st.markdown(f"**{req_preview['method']}** `https://api.zoominfo.com{req_preview['endpoint']}`")
            if req_preview.get("query_params"):
                st.caption("Query parameters:")
                st.code(json.dumps(req_preview["query_params"], indent=2), language="json")
            st.caption("Request body:")
            st.code(json.dumps(req_preview["body"], indent=2), language="json")

        # --- Error ---
        err = st.session_state.get("_intent_api_error")
        if err:
            st.markdown("#### Error")
            st.error(err)
            if exchange:
                st.caption(f"Attempts: {exchange.get('attempts', '?')}")
                # Show auth response if the error was auth-related
                if exchange.get("auth_response"):
                    st.caption("Authentication response body:")
                    st.code(json.dumps(exchange["auth_response"], indent=2, default=str), language="json")

        # --- Response ---
        st.markdown("#### Response")
        if exchange and exchange.get("response"):
            ex_resp = exchange["response"]
            status = ex_resp.get("status_code", "?")
            st.markdown(f"**HTTP {status}**")

            # Show response headers (toggled via checkbox since expanders can't nest)
            if ex_resp.get("headers"):
                if st.checkbox("Show response headers", value=False, key="_intent_show_headers"):
                    st.code(json.dumps(dict(ex_resp["headers"]), indent=2), language="json")

            # Show full response body
            resp_body = ex_resp.get("body")
            if resp_body:
                st.caption("Response body:")
                if isinstance(resp_body, (dict, list)):
                    st.code(json.dumps(resp_body, indent=2, default=str), language="json")
                else:
                    st.code(str(resp_body), language="text")
        elif exchange and exchange.get("error"):
            st.warning(f"No HTTP response received: {exchange['error']}")
        else:
            if err:
                st.caption("No HTTP response — error occurred before a response was received.")
            else:
                # Successful call — show summary from session
                resp = st.session_state.get("_intent_api_response_summary")
                if resp:
                    total = resp.get("total_results", 0)
                    after = resp.get("after_scoring", {})
                    if after:
                        st.markdown(f"**{total}** raw → **{after.get('scored', 0)}** scored → **{after.get('deduped', 0)}** deduped ({after.get('removed', 0)} removed)")
                    else:
                        st.markdown(f"**{total}** results returned")

                    raw_keys = resp.get("raw_keys", [])
                    if raw_keys:
                        st.caption(f"Raw API fields: {', '.join(raw_keys)}")

                    raw_sample = resp.get("raw_sample", {})
                    if raw_sample:
                        st.caption("Raw API response (first item):")
                        st.code(json.dumps(raw_sample, indent=2, default=str), language="json")

                    sample = resp.get("sample", [])
                    if sample:
                        st.caption(f"Normalized sample (first {len(sample)}):")
                        clean = [{k: v for k, v in item.items() if not k.startswith("_") and v not in ("", None, [], {})} for item in sample]
                        st.code(json.dumps(clean, indent=2, default=str), language="json")


# =============================================================================
# CACHE / DEDUP INDICATORS (shown after search, before company list)
# =============================================================================
if st.session_state.intent_search_executed and st.session_state.intent_companies:
    _indicator_parts = []
    _dedup_removed = st.session_state.get("_intent_dedup_removed", 0)
    if _dedup_removed:
        _indicator_parts.append(f"{_dedup_removed} duplicate{'s' if _dedup_removed != 1 else ''} removed")
    if st.session_state.get("_intent_from_cache"):
        _indicator_parts.append("Cached results")

    if _indicator_parts:
        _info_col, _refresh_col = st.columns([4, 1])
        with _info_col:
            st.caption(" · ".join(_indicator_parts))
        if st.session_state.get("_intent_from_cache"):
            with _refresh_col:
                if outline_button("Refresh", key="intent_cache_refresh_btn"):
                    st.session_state["_intent_force_refresh"] = True
                    # Reset search state so search_clicked can re-trigger
                    st.session_state.intent_companies = None
                    st.session_state.intent_search_executed = False
                    st.session_state.intent_companies_confirmed = False
                    st.session_state.intent_selected_companies = {}
                    st.rerun()

# Empty scoring results — all leads filtered by freshness
if st.session_state.intent_search_executed and not st.session_state.intent_companies:
    _resp = st.session_state.get("_intent_api_response_summary", {})
    _raw_count = _resp.get("total_results", 0)
    if _raw_count > 0:
        _stale_summ = st.session_state.get("_intent_stale_summary", {})
        _qp = st.session_state.get("intent_query_params", {})
        _used_topics = _qp.get("topics", [])
        _used_strengths = _qp.get("signal_strengths", [])
        _guidance = build_stale_guidance(_stale_summ, _used_topics, _used_strengths)

        st.warning(f"All {_raw_count} intent results are stale (>14 days old). No companies survived freshness scoring.")

        if _guidance:
            _items = "".join(
                f'<div style="padding:{SPACING["xs"]} 0;color:{COLORS["text_secondary"]};">'
                f'<span style="color:{COLORS["warning"]};margin-right:{SPACING["xs"]};">→</span>'
                f'{html.escape(g)}</div>'
                for g in _guidance
            )
            st.markdown(
                f'<div style="background:{COLORS["bg_secondary"]};border-left:3px solid {COLORS["warning_dark"]};'
                f'border-radius:0 6px 6px 0;padding:{SPACING["sm"]} {SPACING["md"]};margin-top:-{SPACING["sm"]};">'
                f'<div style="font-size:{FONT_SIZES["xs"]};color:{COLORS["text_muted"]};'
                f'text-transform:uppercase;letter-spacing:0.05em;margin-bottom:{SPACING["xs"]};">Try next</div>'
                f'{_items}</div>',
                unsafe_allow_html=True,
            )
    elif not st.session_state.get("_intent_api_error"):
        st.info("No companies found matching criteria.")

# =============================================================================
# STEP 2: SELECT COMPANIES (Manual mode only; Autopilot auto-advances)
# =============================================================================
if (
    st.session_state.intent_mode == "manual"
    and st.session_state.intent_companies
    and not st.session_state.intent_companies_confirmed
):
    st.subheader("Step 2 — Select Companies")
    companies = st.session_state.intent_companies

    st.caption(f"Found **{len(companies)}** companies. Select which to search for contacts.")

    # Filters
    filter_col1, filter_col2 = st.columns([1, 1])
    with filter_col1:
        priority_filter = st.multiselect(
            "Priority",
            ["High", "Medium", "Low", "Very Low"],
            default=["High", "Medium", "Low"],
            key="intent_company_priority_filter",
            label_visibility="collapsed",
        )
    with filter_col2:
        freshness_filter = st.multiselect(
            "Freshness",
            ["Hot", "Warm", "Cooling"],
            default=["Hot", "Warm", "Cooling"],
            key="intent_company_freshness_filter",
            label_visibility="collapsed",
        )

    # Build display data
    display_data = []
    for lead in companies:
        if lead.get("_priority", "") not in priority_filter:
            continue
        if lead.get("_freshness_label", "") not in freshness_filter:
            continue
        display_data.append({
            "Select": str(lead.get("companyId", "")) in st.session_state.intent_selected_companies,
            "Company": lead.get("companyName", ""),
            "Score": lead.get("_score", 0),
            "Priority": lead.get("_priority", ""),
            "Freshness": lead.get("_freshness_label", ""),
            "Signal": lead.get("intentStrength", ""),
            "Topic": lead.get("intentTopic", ""),
            "Age": f"{lead.get('_age_days', '?')}d",
            "_companyId": str(lead.get("companyId", "")),
        })

    if display_data:
        df = pd.DataFrame(display_data)

        edited_df = st.data_editor(
            df.drop(columns=["_companyId"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", default=False, width="small"),
                "Company": st.column_config.TextColumn("Company", width="large"),
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width="small"),
                "Priority": st.column_config.TextColumn("Priority", width="small"),
                "Freshness": st.column_config.TextColumn("Freshness", width="small"),
                "Signal": st.column_config.TextColumn("Signal", width="small"),
                "Topic": st.column_config.TextColumn("Topic", width="medium"),
                "Age": st.column_config.TextColumn("Age", width="small"),
            },
            disabled=["Company", "Score", "Priority", "Freshness", "Signal", "Topic", "Age"],
            key="intent_company_editor",
        )

        # Sync selections
        selected = {}
        for idx, row in edited_df.iterrows():
            if row["Select"]:
                cid = display_data[idx]["_companyId"]
                # Find the original lead
                for lead in companies:
                    if str(lead.get("companyId", "")) == cid:
                        selected[cid] = lead
                        break
        st.session_state.intent_selected_companies = selected

        # Bulk actions
        bulk_col1, bulk_col2, bulk_col3, bulk_col4 = st.columns([1, 1, 1, 1])
        with bulk_col1:
            if st.button(f"Select Top {target_companies}", key="intent_select_top_btn"):
                auto = {}
                for lead in companies[:target_companies]:
                    cid = str(lead.get("companyId", ""))
                    if cid:
                        auto[cid] = lead
                st.session_state.intent_selected_companies = auto
                st.rerun()
        with bulk_col2:
            if st.button("Select All Filtered", key="intent_select_all_btn"):
                auto = {}
                for d in display_data:
                    cid = d["_companyId"]
                    for lead in companies:
                        if str(lead.get("companyId", "")) == cid:
                            auto[cid] = lead
                            break
                st.session_state.intent_selected_companies = auto
                st.rerun()
        with bulk_col3:
            if destructive_button("Clear", key="intent_clear_btn"):
                st.session_state.intent_selected_companies = {}
                st.rerun()

    # Confirm button
    st.markdown("")
    selected_count = len(st.session_state.intent_selected_companies)
    confirm_col1, confirm_col2 = st.columns([1, 3])
    with confirm_col1:
        if st.button(
            f"Find Contacts ({selected_count} companies)",
            type="primary",
            use_container_width=True,
            disabled=selected_count == 0,
        ):
            st.session_state.intent_companies_confirmed = True
            st.rerun()
    with confirm_col2:
        st.caption(f"{selected_count} companies selected")


# =============================================================================
# STEP 3: FIND CONTACTS AT SELECTED COMPANIES
# =============================================================================
if (
    st.session_state.intent_companies_confirmed
    and st.session_state.intent_selected_companies
    and not st.session_state.intent_enrichment_done
):
    if st.session_state.intent_mode == "manual":
        st.subheader("Step 3 — Find Contacts")
    else:
        st.subheader("Step 2 — Find Contacts")

    selected_companies = st.session_state.intent_selected_companies
    company_ids = list(selected_companies.keys())

    st.caption(f"Finding ICP-filtered contacts at **{len(company_ids)}** companies...")

    # Two-phase contact resolution:
    # Phase 1: Resolve hashed company IDs → numeric IDs (via cache or enrich)
    # Phase 2: Contact Search with full ICP filters using numeric IDs
    if st.session_state.intent_contacts_by_company is None:
        logger.info("Contact search starting: %d companies selected", len(company_ids))
        with st.status(f"Finding contacts at {len(company_ids)} companies...", expanded=True) as search_status:
            try:
                client = get_zoominfo_client()
                db = get_database()

                # Phase 1: Resolve hashed → numeric company IDs
                st.write("Resolving company IDs...")
                search_status.update(label=f"Phase 1: Resolving {len(company_ids)} company IDs...")
                cached = db.get_company_ids_bulk(company_ids)
                numeric_map = {}  # hashed_id → numeric_id

                # Use cached IDs where available
                for hid in company_ids:
                    if hid in cached:
                        numeric_map[hid] = cached[hid]["numeric_id"]

                logger.info("Company ID resolution: %d cached, %d need enrichment", len(numeric_map), len(company_ids) - len(numeric_map))

                # Enrich 1 recommended contact per uncached company to get numeric IDs
                uncached = [hid for hid in company_ids if hid not in numeric_map]
                if uncached:
                    st.write(f"Enriching {len(uncached)} contacts to resolve IDs ({len(numeric_map)} cached)...")
                    for idx, hid in enumerate(uncached, 1):
                        company_lead = selected_companies[hid]
                        company_name = company_lead.get("companyName", hid[:8])
                        recommended = company_lead.get("recommendedContacts", [])
                        if not recommended:
                            logger.warning("No recommended contacts for %s — skipping", company_name)
                            continue
                        # Enrich first recommended contact
                        pid = recommended[0].get("id")
                        if not pid:
                            continue
                        try:
                            search_status.update(label=f"Phase 1: Resolving company IDs ({idx}/{len(uncached)})...")
                            enriched = client.enrich_contacts_batch(
                                person_ids=[pid],
                                output_fields=["id", "companyId", "companyName"],
                            )
                            if enriched:
                                company = enriched[0].get("company")
                                company = company if isinstance(company, dict) else {}
                                numeric_id = company.get("id") or enriched[0].get("companyId")
                                resolved_name = company.get("name") or enriched[0].get("companyName", "")
                                if numeric_id:
                                    numeric_map[hid] = int(numeric_id)
                                    db.save_company_id(hid, int(numeric_id), resolved_name)
                                    logger.info("Resolved %s → %s (ID %s)", company_name, resolved_name, numeric_id)
                        except Exception as e:
                            logger.warning("Could not resolve %s: %s", company_name, e)
                            st.caption(f"Could not resolve {company_name}: {e}")
                else:
                    st.write(f"All {len(numeric_map)} company IDs found in cache.")

                st.write(f"Resolved {len(numeric_map)}/{len(company_ids)} company IDs.")
                logger.info("Company ID resolution complete: %d/%d resolved", len(numeric_map), len(company_ids))

                if not numeric_map:
                    search_status.update(label="Could not resolve any company IDs", state="complete")
                    st.warning("Could not resolve company IDs. No contacts to search.")
                else:
                    # Phase 2: Contact Search with ICP filters
                    st.write(f"Searching {len(numeric_map)} companies with ICP filters...")
                    search_status.update(label=f"Phase 2: Contact search ({len(numeric_map)} companies)...")
                    numeric_ids = [str(nid) for nid in numeric_map.values()]

                    params = ContactQueryParams(
                        company_ids=numeric_ids,
                        management_levels=intent_mgmt_levels if intent_mgmt_levels is not None else get_default_management_levels(),
                        contact_accuracy_score_min=intent_accuracy_min,
                        required_fields=intent_phone_fields or get_default_phone_fields(),
                        required_fields_operator="or",
                    )

                    def _contact_page_progress(current_page, total_pages):
                        search_status.update(label=f"Phase 2: Contact search — page {current_page}/{total_pages}")
                        st.write(f"Contact search: page {current_page}/{total_pages}")

                    contacts = client.search_contacts_all_pages(params, max_pages=5, progress_callback=_contact_page_progress)

                    if not contacts:
                        logger.info("Contact search returned 0 results")
                        search_status.update(label="No ICP contacts found", state="complete")
                        st.warning("No contacts matched ICP filters. Try adjusting filters or selecting more companies.")
                    else:
                        logger.info("Contact search returned %d contacts", len(contacts))
                        st.write(f"Found {len(contacts)} contacts. Grouping by company...")
                        contacts_by_company = build_contacts_by_company(contacts)
                        st.session_state.intent_contacts_by_company = contacts_by_company

                        # Auto-select best contact per company
                        # Factor in learned title preferences when available
                        _title_prefs = {}
                        try:
                            _title_prefs = db.get_title_preferences()
                        except Exception:
                            pass  # No prefs yet — use default ranking
                        auto_selected = {}
                        for cid, data in contacts_by_company.items():
                            if data["contacts"]:
                                if _title_prefs:
                                    # Re-rank: accuracy stays primary, title preference breaks ties
                                    def _rank_key(c):
                                        raw = c.get("contactAccuracyScore", 0) or 0
                                        try:
                                            acc = int(raw)
                                        except (ValueError, TypeError):
                                            acc = 0
                                        return (acc, _title_prefs.get(normalize_title(c.get("jobTitle", "")), 0.5))
                                    best = max(data["contacts"], key=_rank_key)
                                    auto_selected[cid] = best
                                else:
                                    auto_selected[cid] = data["contacts"][0]
                        st.session_state.intent_selected_contacts = auto_selected
                        if _title_prefs:
                            logger.info("Auto-select used %d title preferences for ranking", len(_title_prefs))

                        found_companies = len(contacts_by_company)
                        _contact_summary = f"Found {len(contacts)} contacts at {found_companies} companies (best auto-selected)"
                        st.write(_contact_summary)
                        logger.info("Contact resolution complete: %s", _contact_summary)
                        search_status.update(
                            label=f"Found {len(contacts)} ICP contacts at {found_companies} companies",
                            state="complete",
                            expanded=False,
                        )

                        if st.session_state.intent_mode == "autopilot":
                            st.rerun()
                        else:
                            st.rerun()

            except PipelineError as e:
                search_status.update(label="❌ API Error", state="error")
                st.error(e.user_message)
                try:
                    db.log_error(
                        workflow_type="intent",
                        error_type=type(e).__name__,
                        user_message=e.user_message,
                        technical_message=str(e),
                        recoverable=e.recoverable,
                    )
                except Exception:
                    pass  # Never let error logging cause secondary failures
            except Exception:
                search_status.update(label="❌ Contact search failed", state="error")
                logger.exception("Contact search failed")
                st.error("Contact search failed unexpectedly. Check application logs.")

    # Show contacts for manual selection
    if (
        st.session_state.intent_mode == "manual"
        and st.session_state.intent_contacts_by_company
        and not st.session_state.intent_enrichment_done
    ):
        contacts_by_company = st.session_state.intent_contacts_by_company
        total_contacts = sum(len(d["contacts"]) for d in contacts_by_company.values())

        _skipped_count = len(contacts_by_company) - len(st.session_state.intent_selected_contacts)
        _skip_note = f" ({_skipped_count} skipped)" if _skipped_count > 0 else ""
        st.info(f"**{total_contacts}** contacts across **{len(contacts_by_company)}** companies. Select 1 per company or skip.{_skip_note}")

        # Show learning preference tooltip
        _pref_count = 0
        try:
            _pref_count = len(db.get_title_preferences())
        except Exception:
            pass
        if _pref_count > 0:
            st.caption(
                f"Preference learning active — tracking {_pref_count} title pattern{'s' if _pref_count != 1 else ''}. "
                "Your selections train auto-select to prefer titles you pick and deprioritize ones you skip."
            )
        else:
            st.caption(
                "Preference learning: your selections here teach the system which job titles to prefer in future auto-selects."
            )

        _selected_co_count = len(st.session_state.intent_selected_companies)
        _matched_co_count = len(contacts_by_company)
        if _matched_co_count < _selected_co_count:
            _missing = _selected_co_count - _matched_co_count
            st.caption(f"{_missing} compan{'y' if _missing == 1 else 'ies'} had no contacts matching ICP filters (management level, accuracy, phone requirements).")

        # Sort and filter controls
        sort_col, page_col = st.columns([1, 1])
        with sort_col:
            sort_options = {"score": "Best score", "company_name": "Company A-Z", "contact_count": "Most choices"}
            sort_value = st.selectbox(
                "Sort", options=list(sort_options.keys()),
                format_func=lambda x: sort_options[x],
                key="intent_review_sort", label_visibility="collapsed",
            )
        with page_col:
            page_size = st.selectbox("Per page", [5, 10, 20], index=1, key="intent_page_size", label_visibility="collapsed")

        # Build company list
        company_items = list(contacts_by_company.items())
        if sort_value == "company_name":
            company_items.sort(key=lambda x: x[1]["company_name"].lower())
        elif sort_value == "contact_count":
            company_items.sort(key=lambda x: len(x[1]["contacts"]), reverse=True)

        # Paginate
        page_items, current_page, total_pages = paginate_items(company_items, page_size=page_size, page_key="intent_company_page")
        st.caption(f"Showing {len(page_items)} of {len(company_items)} companies (Page {current_page}/{total_pages})")

        for company_id, data in page_items:
            contacts = data["contacts"]
            company_name = data["company_name"]

            with st.container():
                header_col1, header_col2 = st.columns([4, 1])
                with header_col1:
                    st.markdown(f"**{company_name}**")
                with header_col2:
                    badge = status_badge("neutral", f"{len(contacts)} contact{'s' if len(contacts) > 1 else ''}")
                    st.markdown(badge, unsafe_allow_html=True)

                SKIP_LABEL = "Skip — don't enrich"
                options = []
                for i, contact in enumerate(contacts):
                    label = format_contact_label(contact, is_best=(i == 0))
                    options.append((label, contact))

                current_selected = st.session_state.intent_selected_contacts.get(company_id)
                # Default to 0 (best contact); if previously skipped, select Skip option
                if current_selected is None:
                    current_index = len(options)  # Skip option is last
                else:
                    current_index = 0
                    for i, (_, contact) in enumerate(options):
                        c_id = contact.get("id") or contact.get("personId")
                        s_id = current_selected.get("id") or current_selected.get("personId")
                        if c_id and c_id == s_id:
                            current_index = i
                            break

                radio_options = [opt[0] for opt in options] + [SKIP_LABEL]
                selected_label = st.radio(
                    f"Select contact for {company_name}",
                    options=radio_options,
                    index=current_index,
                    key=f"intent_contact_select_{company_id}",
                    label_visibility="collapsed",
                    horizontal=False,
                )

                if selected_label == SKIP_LABEL:
                    st.session_state.intent_selected_contacts.pop(company_id, None)
                else:
                    for label, contact in options:
                        if label == selected_label:
                            st.session_state.intent_selected_contacts[company_id] = contact
                            break

                st.markdown("---")

        if total_pages > 1:
            pagination_controls(current_page, total_pages, "intent_company_page")

        # Bulk selection actions
        st.markdown("")
        bulk_col1, bulk_col2, bulk_col3 = st.columns(3)
        with bulk_col1:
            if st.button("Select all best", key="intent_select_all_contacts_btn"):
                for cid, data in contacts_by_company.items():
                    if data["contacts"]:
                        st.session_state.intent_selected_contacts[cid] = data["contacts"][0]
                st.rerun()
        with bulk_col2:
            if st.button("Skip all", key="intent_skip_all_btn"):
                st.session_state.intent_selected_contacts = {}
                st.rerun()
        with bulk_col3:
            pass  # spacer

        # Enrich confirmation dialog
        @st.dialog("Confirm Enrichment")
        def confirm_intent_enrich(count, remaining):
            st.write(f"This will enrich **{count}** contacts.")
            st.write(f"**{count}** credits will be consumed.")
            if remaining is not None:
                st.write(f"Budget remaining: **{remaining:,}** credits")
            st.markdown("")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("Confirm", type="primary", use_container_width=True):
                    st.session_state.intent_enrich_clicked = True
                    st.rerun()
            with col_no:
                if st.button("Cancel", use_container_width=True):
                    st.rerun()

        # Enrich button
        st.markdown("")
        selected_contact_count = len(st.session_state.intent_selected_contacts)
        _total_companies = len(contacts_by_company)
        _skipped = _total_companies - selected_contact_count

        if selected_contact_count == 0:
            st.warning("All companies skipped. Select at least one contact to enrich.")

        enrich_col1, enrich_col2 = st.columns([1, 3])
        with enrich_col1:
            if selected_contact_count == 0:
                st.button("Enrich (0 contacts)", disabled=True, use_container_width=True)
            elif st.session_state.intent_test_mode:
                # Test mode: skip dialog, go directly
                if st.button(f"Enrich ({selected_contact_count} contacts)", type="primary", key="intent_enrich_test_btn"):
                    st.session_state.intent_enrich_clicked = True
                    st.rerun()
            else:
                if st.button(f"Enrich ({selected_contact_count} contacts)", type="primary", key="intent_enrich_btn"):
                    remaining = budget["remaining"] if budget["has_cap"] else None
                    confirm_intent_enrich(selected_contact_count, remaining)
        with enrich_col2:
            if _skipped > 0:
                st.caption(f"{selected_contact_count} of {_total_companies} companies selected · {_skipped} skipped")
            if st.session_state.intent_test_mode:
                st.caption("🧪 Test mode: no credits used")

    def _record_title_preferences():
        """Record which titles were selected/skipped for learning. Called after successful enrichment."""
        selected_contacts = list(st.session_state.intent_selected_contacts.values())
        _sel_titles = [c.get("jobTitle", "") for c in selected_contacts if c.get("jobTitle")]

        # Only record skip signals in manual mode — autopilot skips are system choices, not user intent
        if st.session_state.intent_mode == "manual":
            _sel_pids = {c.get("personId") or c.get("id") for c in selected_contacts}
            _skip_titles = list({
                _contact["jobTitle"]
                for _cdata in (st.session_state.intent_contacts_by_company or {}).values()
                for _contact in _cdata.get("contacts", [])
                if (_contact.get("personId") or _contact.get("id")) not in _sel_pids
                and _contact.get("jobTitle")
            })
        else:
            _skip_titles = []

        if _sel_titles or _skip_titles:
            try:
                db.record_title_selections(_sel_titles, _skip_titles)
            except Exception:
                logger.debug("Title preference recording failed", exc_info=True)

    # --- ENRICHMENT (both modes) ---
    should_enrich = (
        st.session_state.intent_contacts_by_company
        and st.session_state.intent_selected_contacts
        and not st.session_state.intent_enrichment_done
        and (
            st.session_state.intent_mode == "autopilot"
            or st.session_state.intent_enrich_clicked
        )
    )

    if should_enrich:
            selected_contacts = list(st.session_state.intent_selected_contacts.values())
            person_ids = [
                c.get("personId") or c.get("id")
                for c in selected_contacts
                if c.get("personId") or c.get("id")
            ]

            if person_ids:
                if st.session_state.intent_test_mode:
                    logger.info("Enrichment (test mode): %d contacts, 0 credits", len(person_ids))
                    st.info("**Test Mode**: Using search data as mock enrichment (no credits used)")
                    mock_enriched = []
                    for contact in selected_contacts:
                        enriched = contact.copy()
                        enriched.setdefault("jobTitle", contact.get("jobTitle", "N/A"))
                        enriched.setdefault("email", contact.get("email", "test@example.com"))
                        enriched.setdefault("phone", contact.get("phone", "(555) 000-0000"))
                        enriched.setdefault("mobilePhone", contact.get("mobilePhone", ""))
                        enriched.setdefault("city", contact.get("city", contact.get("personCity", "")))
                        enriched.setdefault("state", contact.get("state", contact.get("personState", "")))
                        enriched["_test_mode"] = True
                        mock_enriched.append(enriched)
                    st.session_state.intent_enriched_contacts = mock_enriched
                    st.session_state.intent_enrichment_done = True
                    _record_title_preferences()
                    st.rerun()
                else:
                    _num_batches = (len(person_ids) + 24) // 25
                    logger.info("Enrichment starting: %d contacts in %d batches (USES %d CREDITS)", len(person_ids), _num_batches, len(person_ids))
                    with st.status(f"Enriching {len(person_ids)} contacts ({len(person_ids)} credits)...", expanded=True) as enrich_status:
                        try:
                            client = get_zoominfo_client()

                            def _enrich_progress(enriched_count, total_count):
                                _batch = (enriched_count + 24) // 25
                                enrich_status.update(label=f"Enriching contacts — {enriched_count}/{total_count} ({_batch}/{_num_batches} batches)")
                                st.write(f"Enriched {enriched_count}/{total_count} contacts")

                            st.write(f"Starting enrichment: {len(person_ids)} contacts, {_num_batches} batch(es)...")
                            enriched = client.enrich_contacts_batch(
                                person_ids=person_ids,
                                output_fields=DEFAULT_ENRICH_OUTPUT_FIELDS,
                                progress_callback=_enrich_progress,
                            )
                            logger.info("Enrichment complete: %d/%d contacts returned", len(enriched), len(person_ids))
                            st.write(f"Enrichment complete: {len(enriched)} contacts returned")
                            enrich_status.update(label=f"Enriched {len(enriched)} contacts", state="complete")
                            st.session_state.intent_enriched_contacts = enriched
                            st.session_state.intent_enrichment_done = True
                            _record_title_preferences()
                            st.rerun()
                        except PipelineError as e:
                            logger.error("Enrichment failed: %s", e.user_message)
                            enrich_status.update(label="Enrichment failed", state="error")
                            st.error(f"Enrichment failed: {e.user_message}")
                            try:
                                db.log_error(
                                    workflow_type="intent",
                                    error_type=type(e).__name__,
                                    user_message=e.user_message,
                                    technical_message=str(e),
                                    recoverable=e.recoverable,
                                )
                            except Exception:
                                pass  # Never let error logging cause secondary failures
                        except Exception:
                            logger.exception("Enrichment failed")
                            enrich_status.update(label="Enrichment failed", state="error")
                            st.error("Enrichment failed unexpectedly. Check application logs.")


# =============================================================================
# STEP 4: RESULTS & EXPORT
# =============================================================================
if st.session_state.intent_enrichment_done and st.session_state.intent_enriched_contacts:
    if st.session_state.intent_test_mode:
        st.warning("🧪 **TEST MODE** - Data shown is from search preview, not actual enrichment. No credits were used.", icon="⚠️")

    if st.session_state.intent_mode == "manual":
        st.subheader("Step 4 — Results")
    else:
        st.subheader("Step 3 — Results")

    enriched_contacts = st.session_state.intent_enriched_contacts
    logger.info("Results step: scoring %d enriched contacts", len(enriched_contacts))

    # Merge pre-enrichment metadata
    # Enrichment replaces contact objects entirely, losing search-only fields
    pre_enrichment = {}
    for company_id, contact in (st.session_state.intent_selected_contacts or {}).items():
        pid = str(contact.get("personId") or contact.get("id") or "")
        if pid:
            pre_enrichment[pid] = {
                "companyName": contact.get("companyName", ""),
                "companyId": contact.get("companyId", ""),
                "sicCode": contact.get("sicCode", ""),
                "employees": contact.get("employees") or contact.get("employeeCount", ""),
                "industry": contact.get("industry", ""),
                "directPhone": contact.get("directPhone", ""),
            }

    for contact in enriched_contacts:
        pid = str(contact.get("id") or contact.get("personId") or "")
        pre = pre_enrichment.get(pid, {})
        # Restore fields from pre-enrichment data that enrichment drops
        for field in ("companyName", "companyId", "sicCode", "employees", "industry", "directPhone"):
            if not contact.get(field) and pre.get(field):
                contact[field] = pre[field]
        # Normalize enrich-specific field names
        if not contact.get("companyName"):
            co = contact.get("company")
            contact["companyName"] = co.get("name", "") if isinstance(co, dict) else ""

    # Build company_scores dict for scoring
    company_scores = {}
    for cid, company_data in st.session_state.intent_selected_companies.items():
        company_scores[str(cid)] = company_data

    # Score contacts
    scored = score_intent_contacts(enriched_contacts, company_scores)

    # Add metadata
    for lead in scored:
        topic = lead.get("_intent_topic", "")
        if not topic and st.session_state.intent_query_params:
            topics = st.session_state.intent_query_params.get("topics", [])
            topic = topics[0] if topics else ""
        score = lead.get("_score", 0)
        age = lead.get("_intent_age_days", 0)
        lead["_lead_source"] = f"ZoomInfo Intent - {topic} - {score} - {age}d"
        lead["_priority"] = get_priority_label(score)
        lead["_priority_action"] = get_priority_action(score)

    st.session_state.intent_results = scored

    # Log usage (enrichment credits) - skip in test mode
    if not st.session_state.get("intent_usage_logged"):
        if st.session_state.intent_test_mode:
            st.caption("🧪 Test mode: Enrichment usage not logged")
        else:
            cost_tracker.log_usage(
                workflow_type="intent",
                query_params=st.session_state.intent_query_params or {},
                credits_used=len(enriched_contacts),
                leads_returned=len(scored),
            )
        st.session_state.intent_usage_logged = True

    # Metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        metric_card("Contacts", len(scored))
    with col2:
        def _company_id(lead):
            cid = lead.get("companyId")
            if cid:
                return str(cid)
            co = lead.get("company")
            if isinstance(co, dict) and co.get("id"):
                return str(co["id"])
            return ""

        companies_with_contacts = len(set(
            _company_id(lead) for lead in scored if _company_id(lead)
        ))
        selected_count = len(st.session_state.intent_selected_companies)
        metric_card("Companies", f"{companies_with_contacts} of {selected_count}")
    with col3:
        if budget["has_cap"]:
            metric_card("Budget Used", budget['display'])
        else:
            metric_card("Intent Credits", budget["current"])

    # Results table + filters (fragment for instant filter response)
    @st.fragment
    def intent_results_table(scored_leads):
        _is_test_mode = st.session_state.get("intent_test_mode", False)
        display_data = []
        for idx, lead in enumerate(scored_leads):
            row = {
                "_idx": idx,
                "_priority_label": lead.get("_priority", ""),
                "Name": f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip(),
                "Title": lead.get("jobTitle", ""),
                "Company": lead.get("companyName", "") or (lead.get("company", {}).get("name", "") if isinstance(lead.get("company"), dict) else ""),
                "Score": lead.get("_score", 0),
                "Accuracy": lead.get("contactAccuracyScore", 0),
                "Priority": lead.get("_priority_action", lead.get("_priority", "")),
                "Phone": lead.get("directPhone", "") or lead.get("phone", ""),
                "Email": lead.get("email", ""),
                "Topic": lead.get("_intent_topic", ""),
            }
            if not _is_test_mode:
                row["City"] = lead.get("city", "") or lead.get("personCity", "")
                row["State"] = lead.get("state", "") or lead.get("personState", "")
            display_data.append(row)

        df = pd.DataFrame(display_data)

        # Filters
        filter_col1, filter_col2 = st.columns([1, 1])
        with filter_col1:
            priority_filter = st.multiselect(
                "Priority",
                ["High", "Medium", "Low", "Very Low"],
                default=["High", "Medium", "Low"],
                key="intent_result_priority",
                label_visibility="collapsed",
            )
        with filter_col2:
            if not _is_test_mode and not df.empty and "State" in df.columns:
                available_states = sorted(df["State"].dropna().unique().tolist())
                if available_states and len(available_states) > 1:
                    state_filter = st.multiselect(
                        "State", available_states, default=available_states,
                        key="intent_result_state", label_visibility="collapsed",
                    )
                else:
                    state_filter = available_states
            else:
                state_filter = []
                if _is_test_mode:
                    st.caption("City/State data populates after enrichment (disabled in test mode)")

        # Apply filters
        if not df.empty:
            mask = df["_priority_label"].isin(priority_filter)
            if state_filter and "State" in df.columns:
                mask = mask & df["State"].isin(state_filter)
            filtered_df = df[mask]
        else:
            filtered_df = df

        # Display
        _col_config = {
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Title": st.column_config.TextColumn("Title", width="medium"),
            "Company": st.column_config.TextColumn("Company", width="large"),
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width="small"),
            "Accuracy": st.column_config.NumberColumn("Accuracy", width="small"),
            "Priority": st.column_config.TextColumn("Priority", width="small"),
            "Phone": st.column_config.TextColumn("Phone", width="medium"),
            "Email": st.column_config.TextColumn("Email", width="medium"),
            "Topic": st.column_config.TextColumn("Topic", width="small"),
        }
        if not _is_test_mode:
            _col_config["City"] = st.column_config.TextColumn("City", width="small")
            _col_config["State"] = st.column_config.TextColumn("State", width="small")

        st.dataframe(
            filtered_df.drop(columns=["_idx", "_priority_label"]),
            use_container_width=True,
            hide_index=True,
            column_config=_col_config,
        )
        st.markdown("")  # Space between table and score details

        # Score breakdown expander — only show leads matching current filters
        _filtered_indices = set(filtered_df["_idx"].tolist())
        with st.expander("Score details", expanded=False):
            for idx, lead in enumerate(scored_leads):
                if idx not in _filtered_indices:
                    continue
                name = f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip()
                company = lead.get("companyName", "Unknown")
                score_val = lead.get("_score", 0)
                st.markdown(f"**{name}** \u00b7 {company} \u00b7 {score_val}%")
                st.markdown(score_breakdown(lead, "intent"), unsafe_allow_html=True)
                st.markdown("---")

        # Export section
        st.markdown("---")

        export_quality_warnings(scored_leads)

        col1, col2, col3 = st.columns([1, 1, 1])

        with col1:
            if st.session_state.intent_mode == "manual":
                if outline_button("Back to Contact Selection", key="intent_back_btn"):
                    st.session_state.intent_enrichment_done = False
                    st.session_state.intent_enriched_contacts = None
                    st.session_state.intent_enrich_clicked = False
                    st.session_state.intent_usage_logged = False
                    st.rerun()

        with col2:
            csv = filtered_df.drop(columns=["_idx", "_priority_label"]).to_csv(index=False)
            st.download_button(
                "Quick Preview CSV",
                data=csv,
                file_name=f"intent_preview_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
                help="Simple table export for review — not VanillaSoft format",
            )

        with col3:
            st.page_link("pages/4_CSV_Export.py", label="VanillaSoft Export", icon="📤", use_container_width=True)

        # Store for export page
        if len(filtered_df) > 0:
            filtered_indices = filtered_df["_idx"].tolist()
            st.session_state.intent_export_leads = [scored_leads[i] for i in filtered_indices]

            # Persist to DB for re-export after session loss (full set, not filtered)
            if not st.session_state.get("intent_leads_staged"):
                db.save_staged_export(
                    "intent",
                    scored_leads,
                    query_params=st.session_state.get("intent_query_params"),
                )
                st.session_state.intent_leads_staged = True

    intent_results_table(scored)
