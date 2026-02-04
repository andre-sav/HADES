"""
Intent Workflow - Find companies showing intent signals.
Superhuman-inspired: clean, focused, progressive disclosure.
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from turso_db import get_database
from zoominfo_client import get_zoominfo_client, IntentQueryParams, ZoomInfoError
from scoring import score_intent_leads, get_priority_label
from dedup import dedupe_leads
from cost_tracker import CostTracker
from utils import get_intent_topics, get_sic_codes, get_employee_minimum
from ui_components import (
    inject_base_styles,
    status_badge,
    colored_progress_bar,
    COLORS,
)

st.set_page_config(page_title="Intent", page_icon="🎯", layout="wide")

# Apply design system styles
inject_base_styles()


# Initialize services
@st.cache_resource
def get_services():
    db = get_database()
    return db, CostTracker(db)


try:
    db, cost_tracker = get_services()
except Exception as e:
    st.error(f"Failed to initialize: {e}")
    st.stop()


# --- Session State ---
if "intent_results" not in st.session_state:
    st.session_state.intent_results = None
if "intent_query_params" not in st.session_state:
    st.session_state.intent_query_params = None


# =============================================================================
# HEADER
# =============================================================================
col1, col2 = st.columns([3, 1])
with col1:
    st.title("Intent")
    st.caption("Find companies showing intent signals for vending")
with col2:
    # Budget indicator with status badge
    budget = cost_tracker.format_budget_display("intent")
    if budget["has_cap"]:
        remaining = budget["remaining"]
        pct = budget["percent"]
        if pct > 90:
            badge = status_badge("error", f"{remaining:,} left")
        elif pct > 70:
            badge = status_badge("warning", f"{remaining:,} left")
        else:
            badge = status_badge("success", f"{remaining:,} left")
        st.markdown(badge, unsafe_allow_html=True)
        colored_progress_bar(pct)

st.markdown("---")


# =============================================================================
# SEARCH CONFIGURATION
# =============================================================================
col1, col2, col3 = st.columns([2, 2, 1])

with col1:
    topics_config = get_intent_topics()
    available_topics = topics_config.get("primary", []) + topics_config.get("expansion", [])

    selected_topics = st.multiselect(
        "Topics",
        options=available_topics,
        default=["Vending"] if "Vending" in available_topics else [],
        label_visibility="collapsed",
        placeholder="Select intent topics...",
    )

with col2:
    signal_strengths = st.multiselect(
        "Signal strength",
        options=["High", "Medium", "Low"],
        default=["High", "Medium"],
        label_visibility="collapsed",
        placeholder="Select signal strengths...",
    )

with col3:
    can_query = len(selected_topics) > 0 and len(signal_strengths) > 0
    search_clicked = st.button("Search", type="primary", use_container_width=True, disabled=not can_query)

# Filters - collapsed
with st.expander("Filters", expanded=False):
    st.caption(f"Minimum employees: {get_employee_minimum()}")
    st.caption(f"SIC codes: {len(get_sic_codes())} industries")

# --- Execute Search ---
if search_clicked:
    # Check budget
    budget_status = cost_tracker.check_budget("intent", 100)

    if budget_status.alert_level == "exceeded":
        st.error("Weekly budget exceeded")
        st.stop()

    if budget_status.alert_level in ("warning", "critical"):
        st.warning(budget_status.alert_message)

    with st.spinner("Searching..."):
        try:
            client = get_zoominfo_client()
            params = IntentQueryParams(
                topics=selected_topics,
                signal_strengths=signal_strengths,
                employee_min=get_employee_minimum(),
                sic_codes=get_sic_codes(),
            )

            leads = client.search_intent_all_pages(params, max_pages=5)

            if not leads:
                st.info("No companies found")
                st.session_state.intent_results = None
            else:
                scored = score_intent_leads(leads)
                deduped, removed = dedupe_leads(scored)

                for lead in deduped:
                    topic = lead.get("intentTopic", selected_topics[0])
                    lead["_lead_source"] = f"ZoomInfo Intent · {topic}"
                    lead["_priority"] = get_priority_label(lead.get("_score", 0))

                st.session_state.intent_results = deduped
                st.session_state.intent_query_params = {
                    "topics": selected_topics,
                    "signal_strengths": signal_strengths,
                }

                # Log
                cost_tracker.log_usage(
                    workflow_type="intent",
                    query_params=st.session_state.intent_query_params,
                    credits_used=len(leads),
                    leads_returned=len(deduped),
                )
                db.log_query(
                    workflow_type="intent",
                    query_params=st.session_state.intent_query_params,
                    leads_returned=len(deduped),
                )

                st.rerun()

        except ZoomInfoError as e:
            st.error(e.user_message)
        except Exception as e:
            st.error(str(e))


# =============================================================================
# RESULTS
# =============================================================================
if st.session_state.intent_results:
    results = st.session_state.intent_results

    st.markdown("---")

    # Header with inline filters
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        st.subheader(f"{len(results)} companies found")

    with col2:
        priority_filter = st.multiselect(
            "Priority",
            ["High", "Medium", "Low", "Very Low"],
            default=["High", "Medium", "Low"],
            label_visibility="collapsed",
        )

    with col3:
        freshness_filter = st.multiselect(
            "Freshness",
            ["Hot", "Warm", "Cooling"],
            default=["Hot", "Warm", "Cooling"],
            label_visibility="collapsed",
        )

    # Build table
    display_data = []
    for lead in results:
        display_data.append({
            "Company": lead.get("companyName", ""),
            "City": lead.get("city", ""),
            "State": lead.get("state", ""),
            "Employees": lead.get("employees", ""),
            "Score": lead.get("_score", 0),
            "Priority": lead.get("_priority", ""),
            "Freshness": lead.get("_freshness_label", ""),
            "Age": f"{lead.get('_age_days', '?')}d",
            "Signal": lead.get("intentStrength", ""),
            "Topic": lead.get("intentTopic", ""),
        })

    df = pd.DataFrame(display_data)

    # Filter
    filtered_df = df[
        df["Priority"].isin(priority_filter) &
        df["Freshness"].isin(freshness_filter)
    ]

    # Display
    st.dataframe(
        filtered_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Company": st.column_config.TextColumn("Company", width="large"),
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, width="small"),
            "Employees": st.column_config.NumberColumn("Emp", width="small"),
            "Age": st.column_config.TextColumn("Age", width="small"),
        },
    )

    # Export
    st.markdown("---")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col2:
        csv = filtered_df.to_csv(index=False)
        st.download_button(
            "Download preview",
            data=csv,
            file_name=f"intent_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with col3:
        st.page_link("pages/4_CSV_Export.py", label="Full export", icon="📤", use_container_width=True)

    # Store for export
    if len(filtered_df) > 0:
        filtered_indices = filtered_df.index.tolist()
        st.session_state.intent_export_leads = [results[i] for i in filtered_indices]
