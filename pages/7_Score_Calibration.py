"""
Score Calibration - View current scoring weights, run calibration, review outcomes.
"""

import logging

import pandas as pd
import streamlit as st
import yaml
from pathlib import Path

from turso_db import get_database
from calibration import compute_conversion_rates, compare_to_current, apply_calibration
from utils import SIC_CODE_DESCRIPTIONS
from ui_components import (
    inject_base_styles,
    page_header,
    status_badge,
    metric_card,
    styled_table,
    empty_state,
    labeled_divider,
    COLORS,
)

logger = logging.getLogger(__name__)

st.set_page_config(page_title="Score Calibration", page_icon="⚖️", layout="wide")

inject_base_styles()

from utils import require_auth
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

CONFIG_PATH = Path(__file__).parent.parent / "config" / "icp.yaml"


# =============================================================================
# HEADER
# =============================================================================
page_header("Score Calibration", "Compare current weights to outcome data")

st.caption("Review scoring weights and SIC industry scores. Calibrate based on delivery outcome data.")

# =============================================================================
# TABS
# =============================================================================
tab_labels = ["Current Weights", "Calibration Report", "Outcomes Feed"]
tab_weights, tab_calibration, tab_outcomes = st.tabs(tab_labels)


# =============================================================================
# TAB 1: CURRENT WEIGHTS
# =============================================================================
with tab_weights:
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    # Last calibration date
    _last_cal_val = db.get_sync_value("last_calibration")
    last_cal = _last_cal_val[:10] if _last_cal_val else "Never"

    col1, col2, col3 = st.columns(3)
    with col1:
        if last_cal == "Never":
            # Check if any SIC codes have calibrated scores
            _cal_scores = config.get("onsite_likelihood", {}).get("sic_scores", {})
            if _cal_scores:
                st.markdown(status_badge("success", f"{len(_cal_scores)} of 25 calibrated"), unsafe_allow_html=True)
                st.caption("SIC Calibration")
            else:
                st.markdown(status_badge("warning", "Never calibrated"), unsafe_allow_html=True)
                st.caption("Last Calibration")
        else:
            metric_card("Last Calibration", last_cal)
    with col2:
        all_sics = config.get("hard_filters", {}).get("sic_codes", [])
        metric_card("ICP SIC Codes", len(all_sics))
    with col3:
        emp_tiers = len(config.get("employee_scale", []))
        metric_card("Employee Tiers", emp_tiers)

    # SIC Scores table — show all 25 ICP codes, not just calibrated ones
    st.markdown("---")
    st.caption("On-site Likelihood · SIC Scores")

    sic_scores = config.get("onsite_likelihood", {}).get("sic_scores", {})
    sic_default = config.get("onsite_likelihood", {}).get("default", 40)
    all_sics = config.get("hard_filters", {}).get("sic_codes", [])

    _sic_filter = st.text_input("Filter", placeholder="Search by code or industry...", key="sic_table_filter")

    sic_rows = []
    for sic in sorted(all_sics):
        score = sic_scores.get(sic, sic_default)
        source = "Calibrated" if sic in sic_scores else "Default"
        desc = SIC_CODE_DESCRIPTIONS.get(sic, "Unknown")
        if _sic_filter:
            _q = _sic_filter.lower()
            if _q not in sic.lower() and _q not in desc.lower():
                continue
        sic_rows.append({"SIC Code": sic, "Industry": desc, "Score": score, "Source": source})

    sic_df = pd.DataFrame(sic_rows) if sic_rows else pd.DataFrame(columns=["SIC Code", "Industry", "Score", "Source"])
    st.dataframe(
        sic_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "SIC Code": st.column_config.TextColumn(width="small"),
            "Industry": st.column_config.TextColumn(width="medium"),
            "Score": st.column_config.NumberColumn(width="small"),
            "Source": st.column_config.TextColumn(width="small"),
        },
    )

    # Employee Scale table
    labeled_divider("Employee Scale")
    st.caption("Employee score contributes ~25% of total ICP score. Smaller companies convert more often based on delivery data.")
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
with tab_calibration:
    rates = compute_conversion_rates(db)

    if not rates["sic_scores"] and not rates["employee_scores"]:
        empty_state(
            "No outcome data available",
            icon="⚖️",
            hint="Import historical data or export leads to start collecting outcomes.",
        )
    else:
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
        else:
            # Initialize session state for selections
            if "cal_selected" not in st.session_state:
                st.session_state.cal_selected = set()

            def _render_calibration_item(comp, prefix):
                """Render a single calibration item with structured layout."""
                key = f"{prefix}_{comp['key']}"
                delta_sign = f"+{comp['delta']}" if comp["delta"] > 0 else str(comp["delta"])
                delta_type = "success" if comp["delta"] > 0 else "error" if comp["delta"] < 0 else "neutral"
                conf_type = {"High": "success", "Medium": "warning", "Low": "error"}.get(comp["confidence"], "neutral")

                # Description for SIC codes
                desc = SIC_CODE_DESCRIPTIONS.get(comp["key"], "") if prefix == "sic" else comp["key"]
                label = f"SIC {comp['key']}" if prefix == "sic" else comp["key"]

                col_check, col_info, col_delta, col_conf = st.columns([1, 8, 3, 2])
                with col_check:
                    checked = st.checkbox("", key=key, value=key in st.session_state.cal_selected, label_visibility="collapsed")
                with col_info:
                    st.markdown(f"**{label}** · {desc}" if desc else f"**{label}**")
                    st.caption(f"N={comp['n']} · {comp['rate']*100:.1f}% delivery rate")
                with col_delta:
                    delta_label = f"{comp['current']} → {comp['suggested']} ({delta_sign})"
                    st.markdown(status_badge(delta_type, delta_label), unsafe_allow_html=True)
                with col_conf:
                    st.markdown(status_badge(conf_type, comp["confidence"]), unsafe_allow_html=True)

                if checked:
                    st.session_state.cal_selected.add(key)
                else:
                    st.session_state.cal_selected.discard(key)

            labeled_divider("SIC Code Calibration")

            sic_comps = [c for c in comparisons if c["dimension"] == "sic"]
            if sic_comps:
                for comp in sorted(sic_comps, key=lambda c: abs(c["delta"]), reverse=True):
                    _render_calibration_item(comp, "sic")

            labeled_divider("Employee Scale Calibration")

            emp_comps = [c for c in comparisons if c["dimension"] == "employee"]
            if emp_comps:
                for comp in emp_comps:
                    _render_calibration_item(comp, "emp")

            # Apply button
            st.markdown("---")
            selected_count = len(st.session_state.cal_selected)

            if selected_count > 0:
                if st.button(
                    f"Apply {selected_count} Selected Update{'s' if selected_count > 1 else ''}",
                    type="primary",
                    key="apply_calibration_btn",
                ):
                    selected_updates = []
                    for comp in comparisons:
                        key = f"{'sic' if comp['dimension'] == 'sic' else 'emp'}_{comp['key']}"
                        if key in st.session_state.cal_selected:
                            selected_updates.append(comp)

                    try:
                        apply_calibration(selected_updates, str(CONFIG_PATH), db=db)
                        st.session_state.cal_selected = set()
                        st.success(f"Applied {len(selected_updates)} score update(s) to icp.yaml")
                        st.rerun()
                    except Exception as e:
                        logger.error(f"Failed to apply calibration: {e}")
                        st.error("Failed to apply calibration. Please try again.")
            else:
                st.caption("Select scores above to apply updates")


# =============================================================================
# TAB 3: OUTCOMES FEED
# =============================================================================
with tab_outcomes:
    batches = db.get_recent_batches(limit=20)

    if not batches:
        empty_state(
            "No export batches yet",
            icon="📋",
            hint="Export leads from the CSV Export page to start tracking outcomes.",
        )
    else:
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
