"""
CSV Export - Export leads with operator metadata, validation, and tracking.
"""

import json
import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
from datetime import datetime

from turso_db import get_database
from export import export_leads_to_csv, get_export_summary
from dedup import find_duplicates, flag_duplicates_in_list
from utils import get_call_center_agents
from ui_components import (
    inject_base_styles,
    page_header,
    status_badge,
    export_validation_checklist,
    metric_card,
    styled_table,
    empty_state,
    COLORS,
)

st.set_page_config(page_title="Export", page_icon="📤", layout="wide")

# Apply design system styles
inject_base_styles()


# Initialize
@st.cache_resource
def get_db():
    return get_database()


try:
    db = get_db()
except Exception as e:
    st.error(f"Failed to connect: {e}")
    st.stop()


# =============================================================================
# HEADER
# =============================================================================
page_header("Export", "Download leads in VanillaSoft format")


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
        st.caption("Previous runs available for export")

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

        st.markdown("")

        # Load buttons — one per staged export
        cols = st.columns(min(len(staged), 3))
        for i, s in enumerate(staged):
            with cols[i % 3]:
                label = f"{s['workflow_type'].title()} · {s['lead_count']} leads"
                if s.get("exported_at"):
                    label += " (re-export)"
                if st.button(label, key=f"load_staged_{s['id']}", use_container_width=True):
                    export_row = db.get_staged_export(s["id"])
                    if export_row and export_row["leads"]:
                        ss_key = "intent_export_leads" if export_row["workflow_type"] == "intent" else "geo_export_leads"
                        st.session_state[ss_key] = export_row["leads"]
                        st.session_state["_loaded_staged_id"] = export_row["id"]
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

    col1, col2 = st.columns(2)
    with col1:
        st.page_link("pages/1_Intent_Workflow.py", label="Run Intent Search", icon="🎯", use_container_width=True)
    with col2:
        st.page_link("pages/2_Geography_Workflow.py", label="Run Geography Search", icon="📍", use_container_width=True)

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
    _src_tab = ui.tabs(options=source_labels, default_value=source_labels[0], key="export_source_tabs")
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
                company1 = dup["lead1"].get("companyName", "Unknown")
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
                    key_matches = [d for d in duplicates if d["lead1"] is lead or d["lead2"] is lead]
                    if key_matches:
                        dup = key_matches[0]
                        my_score = lead.get("_score", 0)
                        other_score = (dup["score2"] if dup["lead1"] is lead else dup["score1"])
                        if my_score >= other_score:
                            filtered.append(lead)
                    else:
                        filtered.append(lead)

                removed = len(leads_to_export) - len(filtered)
                if removed > 0:
                    st.caption(f"{removed} duplicate(s) excluded from export")
                    leads_to_export = filtered


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
st.markdown("---")
st.caption("Export validation")
checks = export_validation_checklist(leads_to_export)

# Show warning summary if any checks failed
error_checks = [c for c in checks if c.get("status") == "error"]
warning_checks = [c for c in checks if c.get("status") == "warning"]
if error_checks:
    st.warning(f"{len(error_checks)} validation check(s) below threshold. Review before exporting.")
elif warning_checks:
    st.caption(f"{len(warning_checks)} check(s) with warnings — leads are still exportable.")


# =============================================================================
# OPERATOR SELECTION
# =============================================================================
st.markdown("---")

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
# EXPORT + MARK EXPORTED
# =============================================================================
st.markdown("---")

# Generate
agents = get_call_center_agents()
csv_content, filename, batch_id = export_leads_to_csv(
    leads_to_export,
    operator=selected_operator,
    workflow_type=workflow_type,
    db=db,
    agents=agents,
)

# Post-export display (if already exported)
if st.session_state.last_export_metadata:
    meta = st.session_state.last_export_metadata
    op_name = meta.get("operator") or ""
    op_display = f" for {op_name}" if op_name else ""
    ts = meta.get("timestamp", "")[:16] if meta.get("timestamp") else ""

    batch_display = f" · {meta.get('batch_id')}" if meta.get("batch_id") else ""
    st.success(f"Exported: {meta.get('filename', '')} · {meta.get('count', 0)} leads{op_display}{batch_display} · {ts}")


# Download and mark exported buttons
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    st.caption(f"Ready: {len(leads_to_export)} leads" + (f" for {selected_operator['operator_name']}" if selected_operator else ""))

with col2:
    st.download_button(
        f"Download {filename}",
        data=csv_content,
        file_name=filename,
        mime="text/csv",
        type="primary",
        use_container_width=True,
    )

with col3:
    _mark_trigger = ui.button(text="Mark as Exported", variant="outline", key="mark_exported_btn")
    _mark_confirmed = ui.alert_dialog(
        show=_mark_trigger,
        title="Mark as Exported",
        description=f"Mark {len(leads_to_export)} leads as exported? This updates the query log.",
        confirm_label="Mark Exported",
        cancel_label="Cancel",
        key="mark_exported_dialog",
    )
    if _mark_confirmed:
        last_query = db.get_last_query(workflow_type)
        if last_query:
            db.update_query_exported(last_query["id"], len(leads_to_export))

        # Record lead outcomes for tracking
        if batch_id:
            now_iso = datetime.now().isoformat()
            outcome_rows = []
            for lead in leads_to_export:
                # Collect _-prefixed scoring features as JSON
                features = {k: v for k, v in lead.items() if k.startswith("_") and v is not None}
                outcome_rows.append((
                    batch_id,
                    lead.get("companyName", ""),
                    str(lead.get("companyId", "")) if lead.get("companyId") else None,
                    str(lead.get("personId", "")) if lead.get("personId") else None,
                    lead.get("sicCode") or lead.get("_sic_code"),
                    lead.get("employees") or lead.get("numberOfEmployees"),
                    lead.get("_distance_miles"),
                    lead.get("zip") or lead.get("zipCode"),
                    lead.get("state"),
                    lead.get("_score"),
                    workflow_type,
                    now_iso,
                    json.dumps(features) if features else None,
                ))
            db.record_lead_outcomes_batch(outcome_rows)

        # Mark staged export as exported (if loaded from DB)
        staged_id = st.session_state.get("_loaded_staged_id")
        if staged_id and batch_id:
            db.mark_staged_exported(staged_id, batch_id)

        st.session_state.last_export_metadata = {
            "filename": filename,
            "count": len(leads_to_export),
            "timestamp": datetime.now().isoformat(),
            "operator": selected_operator.get("operator_name") if selected_operator else None,
            "batch_id": batch_id,
        }

        # Set exported flag for action bar state
        if workflow_type == "intent":
            st.session_state["intent_exported"] = True
        else:
            st.session_state["geo_exported"] = True

        st.rerun()
