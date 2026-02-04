"""
CSV Export - Export leads with operator metadata.
Superhuman-inspired: clean, focused, minimal steps.
"""

import streamlit as st
from turso_db import get_database
from export import export_leads_to_csv, get_export_summary
from ui_components import inject_base_styles, page_header

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

if not intent_leads and not geo_leads:
    st.info("No leads available. Run a search from Intent or Geography first.")
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
    selected_label = st.radio("Source", source_labels, horizontal=True, label_visibility="collapsed")
    workflow_type = sources[source_labels.index(selected_label)][0]
else:
    workflow_type = sources[0][0]
    st.caption(sources[0][1])

leads_to_export = intent_leads if workflow_type == "intent" else geo_leads


# =============================================================================
# SUMMARY
# =============================================================================
summary = get_export_summary(leads_to_export)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Leads", summary["total"])
with col2:
    high = summary["by_priority"].get("High", 0)
    st.metric("High priority", high)
with col3:
    top_state = list(summary["by_state"].keys())[0] if summary["by_state"] else "—"
    st.metric("Top state", top_state)


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
# EXPORT
# =============================================================================
st.markdown("---")

# Generate
csv_content, filename = export_leads_to_csv(
    leads_to_export,
    operator=selected_operator,
    workflow_type=workflow_type,
)

col1, col2 = st.columns([2, 1])

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
