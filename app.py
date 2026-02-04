"""
HADES - ZoomInfo Lead Pipeline
Superhuman-inspired: clean, focused, minimal.
"""

import streamlit as st
from ui_components import inject_base_styles, page_header, status_badge

st.set_page_config(
    page_title="HADES",
    page_icon="◉",
    layout="wide",
)

# Apply design system styles
inject_base_styles()

# --- Header ---
page_header("HADES", "ZoomInfo lead pipeline with ICP filtering and scoring")

# --- Initialize & Status ---
try:
    from turso_db import get_database
    db = get_database()
    connected = True
except Exception as e:
    connected = False
    st.error(f"Database connection failed: {e}")
    st.caption("Check `.streamlit/secrets.toml` configuration")
    st.stop()

# --- Quick Stats ---
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    operators = db.get_operators()
    st.metric("Operators", len(operators))

with col2:
    weekly_credits = db.get_weekly_usage()
    st.metric("Credits this week", f"{weekly_credits:,}")

with col3:
    recent = db.get_recent_queries(limit=100)
    st.metric("Recent queries", len(recent))

with col4:
    # Status badge instead of metric
    badge = status_badge("success", "Connected") if connected else status_badge("error", "Offline")
    st.markdown(badge, unsafe_allow_html=True)
    st.caption("Database")

# --- Quick Actions ---
st.markdown("---")

col1, col2, col3 = st.columns(3)

with col1:
    st.page_link("pages/1_Intent_Workflow.py", label="Intent search", icon="🎯", use_container_width=True)
    st.caption("Find companies showing intent signals")

with col2:
    st.page_link("pages/2_Geography_Workflow.py", label="Geography search", icon="📍", use_container_width=True)
    st.caption("Find companies by location")

with col3:
    st.page_link("pages/4_CSV_Export.py", label="Export leads", icon="📤", use_container_width=True)
    st.caption("Download VanillaSoft CSV")

# --- Recent Activity ---
st.markdown("---")

if recent:
    st.caption("Recent activity")
    for q in recent[:5]:
        workflow = q["workflow_type"].title()
        leads = q["leads_returned"]
        time = q["created_at"][:10] if q["created_at"] else ""
        st.text(f"{workflow}  ·  {leads} leads  ·  {time}")
else:
    st.caption("No recent activity")
