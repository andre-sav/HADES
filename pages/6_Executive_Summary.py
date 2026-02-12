"""
Summary - High-level metrics and trends.
Superhuman-inspired: clean dashboards, clear insights.
"""

import streamlit as st
import streamlit_shadcn_ui as ui
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

from turso_db import get_database
from cost_tracker import CostTracker
from ui_components import (
    inject_base_styles,
    page_header,
    status_badge,
    colored_progress_bar,
    metric_card,
    styled_table,
    COLORS,
)

st.set_page_config(page_title="Summary", page_icon="📈", layout="wide")

# Apply design system styles
inject_base_styles()


# Initialize
@st.cache_resource
def get_services():
    db = get_database()
    return db, CostTracker(db)


try:
    db, cost_tracker = get_services()
except Exception as e:
    st.error(f"Failed to initialize: {e}")
    st.stop()


# =============================================================================
# HEADER
# =============================================================================
today = datetime.now()


def refresh_data():
    st.cache_resource.clear()
    st.rerun()


page_header(
    "Summary",
    f"{today.strftime('%B %Y')} · {today.day} days",
    action_label="Refresh",
    action_callback=refresh_data,
)


# =============================================================================
# TABBED CONTENT
# =============================================================================
_exec_active = ui.tabs(options=["Overview", "Trends", "Budget"], default_value="Overview", key="exec_main_tabs")

# --- OVERVIEW TAB ---
if _exec_active == "Overview":
    mtd = cost_tracker.get_usage_summary(days=today.day)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        metric_card("MTD Credits", mtd.total_credits)

    with col2:
        metric_card("MTD Leads", mtd.total_leads)

    with col3:
        metric_card("MTD Queries", mtd.total_queries)

    with col4:
        if mtd.total_credits > 0 and mtd.total_leads > 0:
            cpl = mtd.total_credits / mtd.total_leads
            metric_card("Credits/Lead", f"{cpl:.2f}")
        else:
            metric_card("Credits/Lead", "—")

    # Workflow comparison
    if mtd.by_workflow:
        st.markdown("---")

        col1, col2 = st.columns(2)

        with col1:
            # Map each workflow to a theme color
            wf_colors = {"geography": COLORS["accent"], "intent": COLORS["primary"]}
            workflows = [wf.title() for wf in mtd.by_workflow.keys()]
            credits = [stats["credits"] for stats in mtd.by_workflow.values()]
            bar_colors = [wf_colors.get(wf, COLORS["primary"]) for wf in mtd.by_workflow.keys()]

            fig = go.Figure(data=[go.Bar(
                x=workflows,
                y=credits,
                marker_color=bar_colors,
                hovertemplate="<b>%{x}</b><br>Credits: %{y:,}<extra></extra>",
            )])
            fig.update_layout(
                height=250,
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORS["text_secondary"], family="Urbanist, sans-serif"),
                xaxis=dict(gridcolor=COLORS["border"], showgrid=False),
                yaxis=dict(gridcolor="rgba(38,45,58,0.37)", griddash="dot"),
                showlegend=False,
                bargap=0.4,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            table_data = []
            for wf, stats in mtd.by_workflow.items():
                eff = stats["leads"] / stats["credits"] if stats["credits"] > 0 else 0
                table_data.append({
                    "workflow": wf.title(),
                    "credits": stats["credits"],
                    "leads": stats["leads"],
                    "efficiency": f"{eff:.2f}",
                })

            styled_table(
                rows=table_data,
                columns=[
                    {"key": "workflow", "label": "Workflow"},
                    {"key": "credits", "label": "Credits", "align": "right", "mono": True},
                    {"key": "leads", "label": "Leads", "align": "right", "mono": True},
                    {"key": "efficiency", "label": "Efficiency", "align": "right", "mono": True},
                ],
            )
    else:
        st.caption("No workflow data yet")


# --- TRENDS TAB ---
elif _exec_active == "Trends":
    trend = []
    for weeks_ago in range(4):
        week_end = today - timedelta(days=weeks_ago * 7)
        week_start = week_end - timedelta(days=7)

        current = cost_tracker.get_usage_summary(days=7 + (weeks_ago * 7))
        previous = cost_tracker.get_usage_summary(days=weeks_ago * 7) if weeks_ago > 0 else None

        if previous:
            credits = current.total_credits - previous.total_credits
            leads = current.total_leads - previous.total_leads
        else:
            credits = current.total_credits
            leads = current.total_leads

        trend.append({
            "Week": week_start.strftime("%b %d"),
            "Credits": max(0, credits),
            "Leads": max(0, leads),
        })

    trend.reverse()
    trend_df = pd.DataFrame(trend)

    if trend_df["Credits"].sum() > 0:
        col1, col2 = st.columns(2)

        with col1:
            fig_credits = go.Figure()
            fig_credits.add_trace(go.Scatter(
                x=trend_df["Week"],
                y=trend_df["Credits"],
                mode="lines+markers",
                line=dict(color=COLORS["primary"], width=3),
                marker=dict(size=8),
                hovertemplate="<b>%{x}</b><br>Credits: %{y:,}<extra></extra>",
            ))
            fig_credits.update_layout(
                height=220,
                margin=dict(l=0, r=0, t=10, b=30),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORS["text_secondary"], family="Urbanist, sans-serif"),
                xaxis=dict(gridcolor=COLORS["border"], showgrid=False, title=""),
                yaxis=dict(gridcolor="rgba(38,45,58,0.37)", griddash="dot", title=""),
                showlegend=False,
            )
            st.plotly_chart(fig_credits, use_container_width=True)
            st.caption("Credits by week")

        with col2:
            fig_leads = go.Figure()
            fig_leads.add_trace(go.Scatter(
                x=trend_df["Week"],
                y=trend_df["Leads"],
                mode="lines+markers",
                line=dict(color=COLORS["success"], width=3),
                marker=dict(size=8),
                hovertemplate="<b>%{x}</b><br>Leads: %{y:,}<extra></extra>",
            ))
            fig_leads.update_layout(
                height=220,
                margin=dict(l=0, r=0, t=10, b=30),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORS["text_secondary"], family="Urbanist, sans-serif"),
                xaxis=dict(gridcolor=COLORS["border"], showgrid=False, title=""),
                yaxis=dict(gridcolor="rgba(38,45,58,0.37)", griddash="dot", title=""),
                showlegend=False,
            )
            st.plotly_chart(fig_leads, use_container_width=True)
            st.caption("Leads by week")
    else:
        st.caption("Not enough data for trends")


# --- BUDGET TAB ---
elif _exec_active == "Budget":
    col1, col2 = st.columns(2)

    with col1:
        st.caption("Intent")
        intent = cost_tracker.format_budget_display("intent")

        if intent["has_cap"]:
            pct = intent["percent"]
            # Replace emoji with status badge
            if pct > 90:
                badge = status_badge("error", f"{intent['current']:,} / {intent['cap']:,}")
            elif pct > 70:
                badge = status_badge("warning", f"{intent['current']:,} / {intent['cap']:,}")
            else:
                badge = status_badge("success", f"{intent['current']:,} / {intent['cap']:,}")

            st.markdown(badge, unsafe_allow_html=True)
            colored_progress_bar(pct)
            st.caption(f"{intent['remaining']:,} remaining")
        else:
            st.caption("No cap configured")

    with col2:
        st.caption("Geography")
        geo = cost_tracker.format_budget_display("geography")

        if geo["has_cap"]:
            st.markdown(f"**{geo['current']:,}** / {geo['cap']:,}")
        else:
            weekly = cost_tracker.get_weekly_usage_by_workflow()
            credits_used = weekly.get('geography', 0)
            st.markdown(status_badge("info", f"{credits_used:,} credits used"), unsafe_allow_html=True)
            st.caption("No cap · unlimited")
