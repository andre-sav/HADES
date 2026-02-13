"""
Score Calibration - View current scoring weights, run calibration, review outcomes.
"""

import streamlit as st
import streamlit_shadcn_ui as ui
import yaml
from pathlib import Path

from turso_db import get_database
from calibration import compute_conversion_rates, compare_to_current, apply_calibration
from ui_components import (
    inject_base_styles,
    page_header,
    metric_card,
    styled_table,
    empty_state,
    COLORS,
)

st.set_page_config(page_title="Score Calibration", page_icon="⚖️", layout="wide")

inject_base_styles()


@st.cache_resource
def get_db():
    return get_database()


try:
    db = get_db()
except Exception as e:
    st.error(f"Failed to connect: {e}")
    st.stop()

CONFIG_PATH = Path(__file__).parent.parent / "config" / "icp.yaml"


# =============================================================================
# HEADER
# =============================================================================
page_header("Score Calibration", "Compare current weights to outcome data")

# =============================================================================
# TABS
# =============================================================================
tab_labels = ["Current Weights", "Calibration Report", "Outcomes Feed"]
active_tab = ui.tabs(options=tab_labels, default_value=tab_labels[0], key="calibration_tabs")


# =============================================================================
# TAB 1: CURRENT WEIGHTS
# =============================================================================
if active_tab == "Current Weights":
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    # Last calibration date
    rows = db.execute("SELECT value FROM sync_metadata WHERE key = 'last_calibration'")
    last_cal = rows[0][0][:10] if rows else "Never"

    col1, col2, col3 = st.columns(3)
    with col1:
        metric_card("Last Calibration", last_cal)
    with col2:
        sic_count = len(config.get("onsite_likelihood", {}).get("sic_scores", {}))
        metric_card("SIC Scores", sic_count)
    with col3:
        emp_tiers = len(config.get("employee_scale", []))
        metric_card("Employee Tiers", emp_tiers)

    # SIC Scores table
    st.markdown("---")
    st.caption("On-site Likelihood · SIC Scores")

    sic_scores = config.get("onsite_likelihood", {}).get("sic_scores", {})
    sic_default = config.get("onsite_likelihood", {}).get("default", 40)

    sic_rows = []
    for sic in sorted(sic_scores.keys()):
        sic_rows.append({"SIC": sic, "Score": sic_scores[sic]})
    sic_rows.append({"SIC": "default", "Score": sic_default})

    styled_table(
        rows=sic_rows,
        columns=[
            {"key": "SIC", "label": "SIC Code"},
            {"key": "Score", "label": "Score", "align": "right", "mono": True},
        ],
    )

    # Employee Scale table
    st.markdown("---")
    st.caption("Employee Scale Scores")
    emp_rows = []
    for tier in config.get("employee_scale", []):
        label = f"{tier['min']}-{tier['max']}" if tier["max"] < 999999 else f"{tier['min']}+"
        emp_rows.append({"Bucket": label, "Score": tier["score"]})

    styled_table(
        rows=emp_rows,
        columns=[
            {"key": "Bucket", "label": "Employee Range"},
            {"key": "Score", "label": "Score", "align": "right", "mono": True},
        ],
    )


# =============================================================================
# TAB 2: CALIBRATION REPORT
# =============================================================================
elif active_tab == "Calibration Report":
    rates = compute_conversion_rates(db)

    if not rates["sic_scores"] and not rates["employee_scores"]:
        empty_state(
            "No outcome data available",
            icon="⚖️",
            hint="Import historical data or export leads to start collecting outcomes.",
        )
        st.stop()

    # Overall stats
    overall = rates["overall"]
    col1, col2, col3 = st.columns(3)
    with col1:
        metric_card("Total Outcomes", overall["total"])
    with col2:
        metric_card("Deliveries", overall["delivered"])
    with col3:
        metric_card("Delivery Rate", f"{overall['rate'] * 100:.1f}%")

    # Comparison
    comparisons = compare_to_current(rates, str(CONFIG_PATH))

    if not comparisons:
        st.info("No comparisons to show.")
        st.stop()

    # Initialize session state for selections
    if "cal_selected" not in st.session_state:
        st.session_state.cal_selected = set()

    st.markdown("---")
    st.caption("SIC Code Calibration")

    sic_comps = [c for c in comparisons if c["dimension"] == "sic"]
    if sic_comps:
        for comp in sorted(sic_comps, key=lambda c: abs(c["delta"]), reverse=True):
            delta_color = "🟢" if comp["delta"] > 0 else "🔴" if comp["delta"] < 0 else "⚪"
            delta_sign = f"+{comp['delta']}" if comp["delta"] > 0 else str(comp["delta"])
            conf_badge = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}.get(comp["confidence"], "⚪")

            key = f"sic_{comp['key']}"
            checked = st.checkbox(
                f"{delta_color} SIC {comp['key']}: {comp['current']} → {comp['suggested']} ({delta_sign}) "
                f"· N={comp['n']} · {comp['rate']*100:.1f}% · {conf_badge} {comp['confidence']}",
                key=key,
                value=key in st.session_state.cal_selected,
            )
            if checked:
                st.session_state.cal_selected.add(key)
            else:
                st.session_state.cal_selected.discard(key)

    st.markdown("---")
    st.caption("Employee Scale Calibration")

    emp_comps = [c for c in comparisons if c["dimension"] == "employee"]
    if emp_comps:
        for comp in emp_comps:
            delta_color = "🟢" if comp["delta"] > 0 else "🔴" if comp["delta"] < 0 else "⚪"
            delta_sign = f"+{comp['delta']}" if comp["delta"] > 0 else str(comp["delta"])
            conf_badge = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}.get(comp["confidence"], "⚪")

            key = f"emp_{comp['key']}"
            checked = st.checkbox(
                f"{delta_color} {comp['key']}: {comp['current']} → {comp['suggested']} ({delta_sign}) "
                f"· N={comp['n']} · {comp['rate']*100:.1f}% · {conf_badge} {comp['confidence']}",
                key=key,
                value=key in st.session_state.cal_selected,
            )
            if checked:
                st.session_state.cal_selected.add(key)
            else:
                st.session_state.cal_selected.discard(key)

    # Apply button
    st.markdown("---")
    selected_count = len(st.session_state.cal_selected)

    if selected_count > 0:
        apply_trigger = ui.button(
            text=f"Apply {selected_count} Selected Update{'s' if selected_count > 1 else ''}",
            variant="default",
            key="apply_calibration_btn",
        )
        if apply_trigger:
            selected_updates = []
            for comp in comparisons:
                key = f"{'sic' if comp['dimension'] == 'sic' else 'emp'}_{comp['key']}"
                if key in st.session_state.cal_selected:
                    selected_updates.append(comp)

            apply_calibration(selected_updates, str(CONFIG_PATH), db=db)
            st.session_state.cal_selected = set()
            st.success(f"Applied {len(selected_updates)} score update(s) to icp.yaml")
            st.rerun()
    else:
        st.caption("Select scores above to apply updates")


# =============================================================================
# TAB 3: OUTCOMES FEED
# =============================================================================
elif active_tab == "Outcomes Feed":
    batches = db.get_recent_batches(limit=20)

    if not batches:
        empty_state(
            "No export batches yet",
            icon="📋",
            hint="Export leads from the CSV Export page to start tracking outcomes.",
        )
        st.stop()

    # Summary metrics
    total_leads = sum(b["lead_count"] for b in batches)
    total_outcomes = sum(b["outcomes_known"] for b in batches)
    total_deliveries = sum(b["deliveries"] for b in batches)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Batches", len(batches))
    with col2:
        metric_card("Leads Exported", total_leads)
    with col3:
        metric_card("Outcomes Known", total_outcomes)
    with col4:
        rate = f"{total_deliveries / total_outcomes * 100:.1f}%" if total_outcomes else "—"
        metric_card("Delivery Rate", rate)

    # Batch table
    st.markdown("---")
    st.caption("Recent Export Batches")

    table_rows = []
    for b in batches:
        outcome_str = f"{b['deliveries']}/{b['outcomes_known']}" if b["outcomes_known"] else "—"
        table_rows.append({
            "batch_id": b["batch_id"],
            "workflow": (b["workflow_type"] or "").title(),
            "exported": (b["exported_at"] or "")[:10],
            "leads": b["lead_count"],
            "outcomes": outcome_str,
        })

    styled_table(
        rows=table_rows,
        columns=[
            {"key": "batch_id", "label": "Batch ID", "mono": True},
            {"key": "workflow", "label": "Workflow"},
            {"key": "exported", "label": "Exported"},
            {"key": "leads", "label": "Leads", "align": "right", "mono": True},
            {"key": "outcomes", "label": "Deliveries / Known", "align": "right", "mono": True},
        ],
    )

    # Expandable detail per batch
    for b in batches[:5]:
        with st.expander(f"{b['batch_id']} · {b['lead_count']} leads"):
            outcomes = db.get_outcomes_by_batch(b["batch_id"])
            if outcomes:
                detail_rows = []
                for o in outcomes:
                    detail_rows.append({
                        "company": o["company_name"],
                        "sic": o.get("sic_code") or "—",
                        "score": o.get("hades_score") or "—",
                        "outcome": o.get("outcome") or "pending",
                    })
                styled_table(
                    rows=detail_rows,
                    columns=[
                        {"key": "company", "label": "Company"},
                        {"key": "sic", "label": "SIC"},
                        {"key": "score", "label": "Score", "align": "right", "mono": True},
                        {"key": "outcome", "label": "Outcome", "pill": {
                            "delivery": "success", "no_delivery": "muted", "pending": "warning",
                        }},
                    ],
                )
