"""
CSV Export - Export leads with operator metadata, validation, and tracking.
"""

import json
import logging

import streamlit as st
from datetime import datetime

from turso_db import get_database
from export import export_leads_to_csv, get_export_summary, build_vanillasoft_row, record_csv_export
from vanillasoft_client import push_leads
from dedup import find_duplicates, flag_duplicates_in_list, get_dedup_days_back
from export_dedup import apply_export_dedup
from vs_leads import parse_vs_export
from utils import get_call_center_agents
from ui_components import (
    inject_base_styles,
    page_header,
    export_validation_checklist,
    metric_card,
    styled_table,
    empty_state,
    labeled_divider,
    score_breakdown,
)

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Export", page_icon="📤", layout="wide")

# Apply design system styles
inject_base_styles()

from utils import require_auth
require_auth()


# Initialize
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
# HEADER
# =============================================================================
page_header("Export", "Push leads to VanillaSoft or download CSV")


def render_vs_history_section():
    """VanillaSoft lead-history import + status (HADES-dio).

    The vanillasoft_leads table is the third dedup source — leads created
    outside HADES (other reps, pre-HADES records) are invisible to
    lead_outcomes and would be re-pushed without it.
    """
    labeled_divider("VanillaSoft Lead History")
    try:
        stats = db.get_vs_leads_stats()
    except Exception:
        logger.warning("VS lead history stats unavailable", exc_info=True)
        stats = {"total": 0, "hades": 0, "latest_added": None}

    if stats["total"]:
        st.caption(
            f"{stats['total']:,} VanillaSoft leads on file for dedup "
            f"({stats['hades']:,} HADES-pushed) · latest Added Date "
            f"{str(stats['latest_added'] or '')[:10]}"
        )
    else:
        st.warning(
            "No VanillaSoft lead history imported — dedup cannot see leads created "
            "outside HADES (other reps, pre-HADES records) and may re-push them. "
            "Import a VanillaSoft contact export below."
        )

    with st.expander("Import VanillaSoft contact export", expanded=not stats["total"]):
        st.caption(
            "Upload a VanillaSoft contact export (.csv). Re-imports are safe — rows are "
            "keyed on ContactID and updated in place. For files over the upload limit "
            "(~200MB), run `python scripts/import_vs_leads.py <file>` locally instead."
        )
        uploaded = st.file_uploader(
            "VS contact export (.csv)", type=["csv"], key="vs_history_upload",
        )
        if uploaded is None:
            return
        parsed = parse_vs_export(uploaded, uploaded.name)
        if not parsed.total_rows:
            st.error("Could not parse any rows — is this a VanillaSoft contact export?")
            return
        st.caption(
            f"{parsed.total_rows:,} rows · {len(parsed.rows):,} importable · "
            f"{parsed.hades_count:,} HADES-pushed · "
            f"{parsed.skipped_unmatchable:,} skipped (no company or phone)"
        )
        # Rerun guard: the upload widget re-delivers the same file every rerun.
        file_sig = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.get("_vs_import_done") == file_sig:
            st.success("Imported — dedup now sees this history.")
            return
        if st.button(f"Import {len(parsed.rows):,} leads", key="vs_import_btn"):
            progress = st.progress(0.0, text="Importing…")
            rows = parsed.rows
            chunk = 500
            for i in range(0, len(rows), chunk):
                db.upsert_vs_leads_batch(rows[i:i + chunk])
                done = min(i + chunk, len(rows))
                progress.progress(done / len(rows),
                                  text=f"Importing… {done:,}/{len(rows):,}")
            progress.empty()
            st.session_state["_vs_import_done"] = file_sig
            st.rerun()


# =============================================================================
# CHECK FOR LEADS
# =============================================================================
intent_leads = st.session_state.get("intent_export_leads", [])
geo_leads = st.session_state.get("geo_export_leads", [])
geo_operator = st.session_state.get("geo_operator")

# Initialize export metadata in session state
if "last_export_metadata" not in st.session_state:
    st.session_state.last_export_metadata = None

# =============================================================================
# EMPTY STATE - Show CTAs when no leads available
# =============================================================================
if not intent_leads and not geo_leads:
    # Check DB for persisted staged exports
    staged = db.get_staged_exports(limit=10)

    if staged:
        st.caption("Previous runs available for export — click **Load** to resume where you left off.")

        table_data = []
        for s in staged:
            status = "Exported" if s.get("exported_at") else "Staged"
            table_data.append({
                "time": s.get("created_at", "")[:16] if s.get("created_at") else "",
                "workflow": s["workflow_type"].title(),
                "leads": s["lead_count"],
                "status": status,
            })
        styled_table(
            rows=table_data,
            columns=[
                {"key": "time", "label": "Time"},
                {"key": "workflow", "label": "Workflow"},
                {"key": "leads", "label": "Leads", "align": "right", "mono": True},
                {"key": "status", "label": "Status", "pill": {"Exported": "success", "Staged": "muted"}},
            ],
        )
        st.caption("**Staged** = leads saved from a workflow run, ready to export as CSV.")

        st.markdown("")

        # Load button — most recent staged export
        most_recent = staged[0]
        label = f"Load Most Recent · {most_recent['workflow_type'].title()} · {most_recent['lead_count']} leads"
        if st.button(label, key="load_most_recent_staged", use_container_width=True):
            export_row = db.get_staged_export(most_recent["id"])
            if export_row and export_row["leads"]:
                ss_key = "intent_export_leads" if export_row["workflow_type"] == "intent" else "geo_export_leads"
                st.session_state[ss_key] = export_row["leads"]
                st.session_state["_loaded_staged_id"] = export_row["id"]
                # Remember this batch's id: its own outcome rows (recorded when
                # the automation generated it) must not dedup-block re-delivery
                # of the very same batch (HADES-guz).
                st.session_state["_loaded_staged_batch_id"] = export_row.get("batch_id")
                # Restore operator if available
                if export_row.get("operator_id"):
                    op = db.get_operator(export_row["operator_id"])
                    if op:
                        st.session_state["geo_operator"] = op
                st.rerun()

        st.markdown("---")

    else:
        empty_state(
            "No leads staged for export",
            icon="📤",
            hint="Run a workflow to find and stage leads, then return here to download your VanillaSoft CSV.",
        )

    # Export History — show completed exports
    exported = db.get_staged_exports(limit=20)
    exported = [e for e in exported if e.get("exported_at") or e.get("push_status")]
    if exported:
        labeled_divider("Export History")
        history_data = []
        for e in exported:
            if e.get("push_status") == "complete":
                status = "Pushed"
            elif e.get("push_status") == "partial":
                status = "Partial"
            elif e.get("exported_at"):
                status = "CSV"
            else:
                continue
            ts = e.get("exported_at") or e.get("created_at", "")
            history_data.append({
                "time": ts[:16] if ts else "",
                "workflow": e["workflow_type"].title(),
                "leads": e["lead_count"],
                "batch": (e.get("batch_id") or "")[:12],
                "status": status,
            })
        if history_data:
            styled_table(
                rows=history_data,
                columns=[
                    {"key": "time", "label": "Exported"},
                    {"key": "workflow", "label": "Workflow"},
                    {"key": "leads", "label": "Leads", "align": "right", "mono": True},
                    {"key": "batch", "label": "Batch", "mono": True},
                    {"key": "status", "label": "Method", "pill": {"Pushed": "success", "CSV": "info", "Partial": "warning"}},
                ],
            )

    render_vs_history_section()
    st.stop()


# =============================================================================
# SOURCE SELECTION
# =============================================================================
sources = []
if intent_leads:
    sources.append(("intent", f"Intent · {len(intent_leads)} leads"))
if geo_leads:
    sources.append(("geography", f"Geography · {len(geo_leads)} leads"))

if len(sources) > 1:
    source_labels = [s[1] for s in sources]
    _src_tab = st.segmented_control(
        "Source",
        options=source_labels,
        default=source_labels[0],
        key="export_source_tabs",
        label_visibility="collapsed",
    )
    _src_idx = source_labels.index(_src_tab) if _src_tab in source_labels else 0
    workflow_type = sources[_src_idx][0]
else:
    workflow_type = sources[0][0]
    st.caption(sources[0][1])

leads_to_export = intent_leads if workflow_type == "intent" else geo_leads


# =============================================================================
# CROSS-WORKFLOW DEDUP CHECK
# =============================================================================
if intent_leads and geo_leads:
    other_leads = geo_leads if workflow_type == "intent" else intent_leads
    other_name = "Geography" if workflow_type == "intent" else "Intent"

    duplicates = find_duplicates(leads_to_export, other_leads)

    if duplicates:
        st.markdown("---")
        with st.expander(f"Cross-workflow duplicates ({len(duplicates)} found)", expanded=True):
            st.caption(
                f"{len(duplicates)} lead(s) also appear in {other_name} results. "
                "Higher-scored version kept by default."
            )

            # Initialize override state
            if "_dedup_overrides" not in st.session_state:
                st.session_state._dedup_overrides = {}

            dup_rows = []
            for i, dup in enumerate(duplicates):
                company1 = dup["lead1"].get("companyName") or (dup["lead1"].get("company", {}).get("name", "") if isinstance(dup["lead1"].get("company"), dict) else "") or "Unknown"
                score1 = dup["lead1"].get("_score", 0)
                score2 = dup["lead2"].get("_score", 0)
                winner = "current" if score1 >= score2 else other_name.lower()
                dup_rows.append({
                    "company": company1,
                    "this_score": int(score1) if score1 else 0,
                    "other_score": int(score2) if score2 else 0,
                    "kept": "This workflow" if winner == "current" else other_name,
                })

            styled_table(
                rows=dup_rows,
                columns=[
                    {"key": "company", "label": "Company"},
                    {"key": "this_score", "label": f"{workflow_type.title()} Score", "align": "right", "mono": True},
                    {"key": "other_score", "label": f"{other_name} Score", "align": "right", "mono": True},
                    {"key": "kept", "label": "Kept In", "pill": {"This workflow": "success", other_name: "muted"}},
                ],
            )

            exclude_dupes = st.checkbox(
                "Exclude lower-scored duplicates from this export",
                value=True,
                key="exclude_cross_dupes",
            )

            if exclude_dupes:
                # Flag duplicates and filter out ones where other workflow scores higher
                flagged = flag_duplicates_in_list(leads_to_export, other_leads)
                filtered = []
                for lead in flagged:
                    if not lead.get("_is_duplicate"):
                        filtered.append(lead)
                        continue
                    # Keep if this lead scores >= the other version
                    lead_pid = str(lead.get("personId", ""))
                    key_matches = [d for d in duplicates if str(d["lead1"].get("personId", "")) == lead_pid or str(d["lead2"].get("personId", "")) == lead_pid]
                    if key_matches:
                        dup = key_matches[0]
                        my_score = lead.get("_score", 0)
                        other_score = (dup["score2"] if str(dup["lead1"].get("personId", "")) == lead_pid else dup["score1"])
                        if my_score >= other_score:
                            filtered.append(lead)
                    else:
                        filtered.append(lead)

                removed = len(leads_to_export) - len(filtered)
                if removed > 0:
                    st.caption(f"{removed} duplicate(s) excluded from export")
                    leads_to_export = filtered


# =============================================================================
# CROSS-SESSION EXPORT DEDUP (previously exported companies)
# =============================================================================
_dedup_days = get_dedup_days_back()
include_exported = st.checkbox(
    "Include previously exported companies",
    value=False,
    key="export_include_prev_exported",
    help=f"When unchecked, leads from companies already exported in the last {_dedup_days} days are removed.",
)

dedup_result = apply_export_dedup(
    leads_to_export, db, days_back=_dedup_days, include_exported=include_exported,
    exclude_batch_id=st.session_state.get("_loaded_staged_batch_id"),
)

if dedup_result["filtered_count"] > 0:
    if include_exported:
        st.caption(
            f"{dedup_result['filtered_count']} of {dedup_result['total_before_filter']} leads are from "
            f"previously exported companies (included because checkbox is checked)"
        )
    else:
        st.info(
            f"Removed {dedup_result['filtered_count']} lead(s) from companies already exported "
            f"in the last {dedup_result['days_back']} days. "
            f"{len(dedup_result['contacts'])} of {dedup_result['total_before_filter']} remain."
        )
        leads_to_export = dedup_result["contacts"]

    # Flag-first visibility (HADES-dio): companies matched against imported
    # VanillaSoft history came from OTHER reps/channels — show the operator
    # what they matched so the drop is a confirmed decision, not a silent one.
    _vs_filtered = [c for c in dedup_result["filtered_contacts"]
                    if c.get("_dedup_source") == "vanillasoft"]
    if _vs_filtered:
        with st.expander(
            f"Already in VanillaSoft from non-HADES sources ({len(_vs_filtered)})",
            expanded=False,
        ):
            st.caption(
                "Existing VanillaSoft leads (any rep or channel) added within the "
                "dedup window. Use the checkbox above to include them anyway."
            )
            styled_table(
                rows=[{
                    "company": c.get("companyName", ""),
                    "status": c.get("_vs_lead_status") or "—",
                    "added": (c.get("_vs_added_date") or "")[:10],
                } for c in _vs_filtered],
                columns=[
                    {"key": "company", "label": "Company"},
                    {"key": "status", "label": "VS Status"},
                    {"key": "added", "label": "Added Date", "mono": True},
                ],
            )

    if not include_exported and not leads_to_export:
        st.warning("All leads have been previously exported. Check the box above to re-export anyway.")
        st.stop()


# =============================================================================
# SUMMARY
# =============================================================================
summary = get_export_summary(leads_to_export)

col1, col2, col3 = st.columns(3)
with col1:
    metric_card("Leads", summary["total"])
with col2:
    high = summary["by_priority"].get("High", 0)
    metric_card("High Priority", high)
with col3:
    top_state = list(summary["by_state"].keys())[0] if summary["by_state"] else "—"
    metric_card("Top State", top_state)


# =============================================================================
# PRE-EXPORT VALIDATION
# =============================================================================
labeled_divider("Validation")
st.caption("Pre-export checks ensure data quality. Red items need attention before exporting; yellow items are OK to proceed.")
checks = export_validation_checklist(leads_to_export)

# Show warning summary if any checks failed
error_checks = [c for c in checks if c.get("status") == "error"]
warning_checks = [c for c in checks if c.get("status") == "warning"]
if error_checks:
    st.warning(f"{len(error_checks)} validation check(s) below threshold. Review before exporting.")
elif warning_checks:
    st.caption(f"{len(warning_checks)} check(s) with warnings — leads are still exportable.")


# =============================================================================
# SCORE DETAILS
# =============================================================================
with st.expander(f"Lead score details ({len(leads_to_export)} leads)", expanded=False):
    for lead in leads_to_export:
        name = f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip()
        company = lead.get("companyName") or (lead.get("company", {}).get("name", "") if isinstance(lead.get("company"), dict) else "") or "Unknown"
        score = lead.get("_score", 0)
        st.markdown(f"**{name}** · {company} · {score}%")
        st.markdown(score_breakdown(lead, workflow_type), unsafe_allow_html=True)
        st.markdown("---")


# =============================================================================
# OPERATOR SELECTION
# =============================================================================
labeled_divider("Operator")
st.caption("Assigning an operator tags this export for a specific sales territory")

# Pre-select operator from geography workflow if available
operators = db.get_operators()

if geo_operator and workflow_type == "geography":
    # Use operator from geography workflow
    selected_operator = geo_operator
    st.caption(f"Operator: **{geo_operator.get('operator_name')}** · {geo_operator.get('vending_business_name') or '—'}")

    with st.expander("Change operator", expanded=False):
        if operators:
            options = {f"{op['operator_name']} · {op.get('vending_business_name') or '—'}": op for op in operators}
            selected = st.selectbox(
                "Select",
                [""] + list(options.keys()),
                format_func=lambda x: x if x else "Choose operator...",
                label_visibility="collapsed",
            )
            if selected:
                selected_operator = options[selected]
        else:
            st.caption("No saved operators")

elif operators:
    options = {f"{op['operator_name']} · {op.get('vending_business_name') or '—'}": op for op in operators}
    options_list = ["(No operator)"] + list(options.keys())

    selected = st.selectbox(
        "Operator",
        options_list,
        label_visibility="collapsed",
    )

    selected_operator = options.get(selected) if selected != "(No operator)" else None

    if selected_operator:
        st.caption(f"{selected_operator.get('operator_zip', '—')} · {selected_operator.get('team') or '—'}")
else:
    st.caption("No operators configured")
    selected_operator = None


# =============================================================================
# EXPORT — Push to VanillaSoft + CSV Download
# =============================================================================
labeled_divider("Export")

# Check for VanillaSoft push capability
_vs_web_lead_id = st.secrets.get("VANILLASOFT_WEB_LEAD_ID")
_vs_push_available = bool(_vs_web_lead_id and _vs_web_lead_id != "your-web-lead-id")

agents = get_call_center_agents()

# Build rows (cached to avoid batch_id DB writes on rerun)
_export_cache_key = (
    tuple(l.get("personId", l.get("companyId", i)) for i, l in enumerate(leads_to_export)),
    selected_operator.get("id") if selected_operator else None,
    workflow_type,
)
if st.session_state.get("_export_cache_key") != _export_cache_key:
    csv_content, filename, batch_id = export_leads_to_csv(
        leads_to_export,
        operator=selected_operator,
        workflow_type=workflow_type,
        db=db,
        agents=agents,
    )
    st.session_state["_export_cache_key"] = _export_cache_key
    st.session_state["_export_cached"] = (csv_content, filename, batch_id)
else:
    csv_content, filename, batch_id = st.session_state["_export_cached"]

# Build VanillaSoft rows for push (same data as CSV, just dict form)
vs_rows = []
for i, lead in enumerate(leads_to_export):
    contact_owner = agents[i % len(agents)] if agents else ""
    vs_rows.append(build_vanillasoft_row(
        lead, selected_operator, batch_id=batch_id, contact_owner=contact_owner,
    ))

# Post-push/export display
if st.session_state.get("last_export_metadata"):
    meta = st.session_state.last_export_metadata
    op_name = meta.get("operator") or ""
    op_display = f" for {op_name}" if op_name else ""
    ts = meta.get("timestamp", "")[:16] if meta.get("timestamp") else ""
    batch_display = f" · {meta.get('batch_id')}" if meta.get("batch_id") else ""
    method = meta.get("method", "Exported")
    st.success(f"{method}: {meta.get('count', 0)} leads{op_display}{batch_display} · {ts}")

# Confirmation dialog for VanillaSoft push
@st.dialog("Confirm Push to VanillaSoft")
def confirm_push_dialog(lead_count, operator_name):
    st.write(f"Push **{lead_count}** leads to VanillaSoft?")
    if operator_name:
        st.write(f"Operator: **{operator_name}**")
    st.caption("This creates real CRM records that cannot be undone.")
    st.markdown("")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Push", type="primary", use_container_width=True):
            st.session_state["vs_push_confirmed"] = True
            st.rerun()
    with col_no:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

def _on_csv_download():
    """Record the download as an export (HADES-rkr).

    Runs once per click via on_click, before the rerun. Session-guarded per
    lead set so repeated clicks on the same batch don't re-record (the DB's
    INSERT OR IGNORE unique index is the second line of defense).
    """
    if st.session_state.get("_csv_download_recorded") == _export_cache_key:
        return
    recorded = record_csv_export(db, leads_to_export, batch_id, workflow_type)
    if not recorded:
        return
    st.session_state["_csv_download_recorded"] = _export_cache_key
    last_query = db.get_last_query(workflow_type)
    if last_query:
        db.update_query_exported(last_query["id"], recorded)
    staged_id = st.session_state.get("_loaded_staged_id")
    if staged_id and batch_id:
        db.mark_staged_exported(staged_id, batch_id)
    st.session_state.last_export_metadata = {
        "count": recorded,
        "timestamp": datetime.now().isoformat(),
        "operator": selected_operator.get("operator_name") if selected_operator else None,
        "batch_id": batch_id,
        "method": "CSV downloaded",
    }
    if workflow_type == "intent":
        st.session_state["intent_exported"] = True
    else:
        st.session_state["geo_exported"] = True


# Buttons
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    st.caption(f"Ready: {len(leads_to_export)} leads" + (f" for {selected_operator['operator_name']}" if selected_operator else ""))

with col2:
    push_clicked = st.button(
        "\U0001f4e4 Push to VanillaSoft",
        type="primary",
        use_container_width=True,
        disabled=not _vs_push_available,
        help="Send leads directly to VanillaSoft call queue. Each lead becomes a new record.",
    )
    if not _vs_push_available:
        st.caption("VanillaSoft push unavailable — configure `VANILLASOFT_WEB_LEAD_ID` in secrets.")

with col3:
    st.download_button(
        "\U0001f4be Download CSV",
        data=csv_content,
        file_name=filename,
        mime="text/csv",
        use_container_width=True,
        help="Download a CSV file formatted for VanillaSoft import (31 columns). "
             "Downloading marks these companies as exported for dedup purposes.",
        on_click=_on_csv_download,
    )

# Open confirmation dialog on button click
if push_clicked and _vs_push_available:
    _op_name = selected_operator.get("operator_name") if selected_operator else None
    confirm_push_dialog(len(leads_to_export), _op_name)

# Push flow — fires after dialog confirmation (pop ensures single execution),
# or when the user requested a retry of previously failed leads (HADES-1ue).
_retry_rows = st.session_state.pop("_vs_retry_rows", None)
_push_confirmed = st.session_state.pop("vs_push_confirmed", False)
if (_push_confirmed or _retry_rows) and _vs_push_available:
    rows_to_push = _retry_rows if _retry_rows else vs_rows
    progress_bar = st.progress(0, text="Pushing to VanillaSoft...")
    log_container = st.container()

    def _on_progress(current, total, result):
        progress_bar.progress(current / total, text=f"Pushing to VanillaSoft... {current}/{total}")
        icon = "\u2714" if result.success else "\u2716"
        err = f" ({result.error})" if result.error else ""
        log_container.caption(f"{icon} {result.lead_name} \u2014 {result.company}{err}")

    summary = push_leads(rows_to_push, web_lead_id=_vs_web_lead_id, progress_callback=_on_progress)

    progress_bar.empty()

    # Cumulative succeeded count across the initial push + retries (a retry
    # pushes exactly the previously-failed rows, so the new failure set fully
    # replaces the old one).
    _prior_succeeded = st.session_state.get("_vs_push_succeeded_total", 0) if _retry_rows else 0
    _total_succeeded = _prior_succeeded + len(summary.succeeded)
    st.session_state["_vs_push_succeeded_total"] = _total_succeeded

    # Summary banner
    if summary.failed:
        st.warning(f"Push complete: {len(summary.succeeded)}/{summary.total} succeeded, {len(summary.failed)} failed")
    else:
        st.success(f"All {summary.total} leads pushed to VanillaSoft")

    # Record outcomes for successful leads only — match by personId (unique), fallback to name+company
    if batch_id:
        now_iso = datetime.now().isoformat()
        succeeded_pids = {r.person_id for r in summary.succeeded if r.person_id}
        succeeded_names = {(r.lead_name, r.company) for r in summary.succeeded if not r.person_id}
        outcome_rows = []
        for lead in leads_to_export:
            pid = str(lead["personId"]) if lead.get("personId") is not None else None
            matched = (pid and pid in succeeded_pids) or (
                not pid
                and (f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip(), lead.get("companyName", ""))
                in succeeded_names
            )
            if not matched:
                continue
            features = {k: v for k, v in lead.items() if k.startswith("_") and v is not None}
            outcome_rows.append(
                db.build_outcome_row(
                    lead, batch_id, workflow_type, now_iso,
                    json.dumps(features) if features else None,
                )
            )
        if outcome_rows:
            db.record_lead_outcomes_batch(outcome_rows)

    # Update query log (cumulative across retries)
    last_query = db.get_last_query(workflow_type)
    if last_query:
        db.update_query_exported(last_query["id"], _total_succeeded)

    # Persist failed-lead state OUTSIDE the single-fire block so the panel
    # survives reruns and Retry can actually be observed (HADES-1ue: the old
    # in-block button was never executed on its own click's rerun, and
    # _vs_retry_rows had no consumer).
    failed_pids = {r.person_id for r in summary.failed if r.person_id}
    failed_names = {(r.lead_name, r.company) for r in summary.failed if not r.person_id}

    def _is_failed_row(r):
        pid = r.get("_personId")
        if pid and pid in failed_pids:
            return True
        if not pid:
            key = (f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip(), r.get("Company", ""))
            return key in failed_names
        return False

    if summary.failed:
        st.session_state["vs_push_failed_state"] = {
            "results": [
                {"name": r.lead_name, "company": r.company, "error": r.error, "person_id": r.person_id}
                for r in summary.failed
            ],
            "rows": [r for r in rows_to_push if _is_failed_row(r)],
            "cache_key": _export_cache_key,
        }
    else:
        st.session_state.pop("vs_push_failed_state", None)

    # Mark staged export
    staged_id = st.session_state.get("_loaded_staged_id")
    push_status = "complete" if not summary.failed else "partial"
    push_results = json.dumps({
        "succeeded": [{"name": r.lead_name, "company": r.company, "person_id": r.person_id} for r in summary.succeeded],
        "failed": [{"name": r.lead_name, "company": r.company, "error": r.error, "person_id": r.person_id} for r in summary.failed],
    })
    if staged_id and batch_id:
        db.mark_staged_exported(staged_id, batch_id)
        db.mark_staged_pushed(staged_id, push_status, push_results)

    # Store metadata
    st.session_state.last_export_metadata = {
        "count": _total_succeeded,
        "timestamp": datetime.now().isoformat(),
        "operator": selected_operator.get("operator_name") if selected_operator else None,
        "batch_id": batch_id,
        "method": "Pushed to VanillaSoft",
    }
    if workflow_type == "intent":
        st.session_state["intent_exported"] = True
    else:
        st.session_state["geo_exported"] = True

# Failed leads — rendered from persisted state so the panel (and the Retry
# button) survives the rerun that follows the push (HADES-1ue).
_failed_state = st.session_state.get("vs_push_failed_state")
if _failed_state and _failed_state.get("cache_key") == _export_cache_key and _failed_state.get("rows"):
    st.markdown("---")
    st.markdown(f"**Failed ({len(_failed_state['results'])}):**")
    for r in _failed_state["results"]:
        st.caption(f"\u2716 {r['name']} \u2014 {r['company']} ({r['error']})")

    fcol1, fcol2 = st.columns(2)
    with fcol1:
        if st.button("\U0001f504 Retry Failed", use_container_width=True,
                     disabled=not _vs_push_available):
            st.session_state["_vs_retry_rows"] = _failed_state["rows"]
            st.rerun()
    with fcol2:
        import csv as csv_mod
        import io
        from utils import VANILLASOFT_COLUMNS
        out = io.StringIO()
        writer = csv_mod.DictWriter(out, fieldnames=VANILLASOFT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in _failed_state["rows"]:
            writer.writerow(r)
        st.download_button(
            "\U0001f4be Download Failed as CSV",
            data=out.getvalue(),
            file_name=f"HADES-failed-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

render_vs_history_section()
