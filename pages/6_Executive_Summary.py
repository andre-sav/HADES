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
    narrative_metric,
    styled_table,
    workflow_summary_strip,
    COLORS,
)

st.set_page_config(page_title="Summary", page_icon="📈", layout="wide")

# Apply design system styles
inject_base_styles()

from utils import require_auth
require_auth()


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

# Context strip below header (since action_label precludes right_content)
_mtd_quick = cost_tracker.get_usage_summary(days=today.day)
workflow_summary_strip([
    {"label": "Leads MTD", "value": _mtd_quick.total_leads},
    {"label": "Credits MTD", "value": _mtd_quick.total_credits},
    {"label": "Queries MTD", "value": _mtd_quick.total_queries},
])


# =============================================================================
# TABBED CONTENT
# =============================================================================
_exec_active = ui.tabs(options=["Overview", "Trends", "Budget"], default_value="Overview", key="exec_main_tabs")

# --- OVERVIEW TAB ---
if _exec_active == "Overview":
    mtd = cost_tracker.get_usage_summary(days=today.day)

    # KPI cards — scannable at a glance
    _kpi1, _kpi2, _kpi3, _kpi4 = st.columns(4)
    with _kpi1:
        metric_card("Leads Exported", mtd.total_leads, help_text="Month to date")
    with _kpi2:
        metric_card("Credits Used", mtd.total_credits, help_text="Month to date")
    with _kpi3:
        _eff = mtd.total_leads / mtd.total_credits if mtd.total_credits > 0 else 0
        metric_card("Efficiency", f"{_eff:.2f}", help_text="Leads per credit")
    with _kpi4:
        metric_card("Queries", mtd.total_queries, help_text="Month to date")

    st.markdown("")

    # Narrative metrics — answers, not raw numbers
    if mtd.total_leads > 0 and mtd.total_credits > 0:
        cpl = mtd.total_credits / mtd.total_leads
        narrative_metric(
            f"{{value}} leads exported this month at {cpl:.2f} credits per lead",
            highlight_value=f"{mtd.total_leads:,}",
            subtext=f"{mtd.total_credits:,} credits used across {mtd.total_queries} queries",
        )
    else:
        narrative_metric(
            "{value} leads exported this month",
            highlight_value=f"{mtd.total_leads:,}" if mtd.total_leads > 0 else "0",
            subtext="No leads exported yet this month. First export will populate this dashboard."
            if mtd.total_leads == 0
            else f"{mtd.total_credits:,} credits used across {mtd.total_queries} queries",
        )

    # Budget narrative
    intent_budget = cost_tracker.format_budget_display("intent")
    if intent_budget["has_cap"]:
        pct = intent_budget["percent"]
        narrative_metric(
            "{value} of weekly Intent credits used",
            highlight_value=f"{intent_budget['current']:,} of {intent_budget['cap']:,} ({pct:.0f}%)",
            subtext=f"{intent_budget['remaining']:,} credits remaining this week"
            if intent_budget["remaining"] and intent_budget["remaining"] > 0
            else "Budget exhausted — resets Monday",
        )

    # Geography searches narrative
    geo_queries = mtd.by_workflow.get("geography", {}).get("queries", 0)
    if geo_queries > 0:
        geo_leads = mtd.by_workflow.get("geography", {}).get("leads", 0)
        narrative_metric(
            "{value} Geography searches this month",
            highlight_value=str(geo_queries),
            subtext=f"{geo_leads:,} leads found · no credit cap",
        )

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
                title=dict(text="Credits by Workflow", font=dict(size=14, color=COLORS["text_secondary"])),
                height=250,
                margin=dict(l=0, r=0, t=40, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORS["text_secondary"], family="Urbanist, sans-serif"),
                xaxis=dict(gridcolor=COLORS["border"], showgrid=False),
                yaxis=dict(gridcolor="rgba(38,45,58,0.37)", griddash="dot", title="Credits"),
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

            # Efficiency callout
            if table_data:
                _best = max(table_data, key=lambda r: float(r["efficiency"]) if r["efficiency"] != "0.00" else 0)
                if float(_best["efficiency"]) > 0:
                    st.caption(f"Most efficient: {_best['workflow']} ({_best['efficiency']} leads/credit)")
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
                title=dict(text="Credits by Week", font=dict(size=14, color=COLORS["text_secondary"])),
                height=220,
                margin=dict(l=0, r=0, t=35, b=30),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORS["text_secondary"], family="Urbanist, sans-serif"),
                xaxis=dict(gridcolor=COLORS["border"], showgrid=False, title=""),
                yaxis=dict(gridcolor="rgba(38,45,58,0.37)", griddash="dot", title="Credits"),
                showlegend=False,
            )
            st.plotly_chart(fig_credits, use_container_width=True)

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
                title=dict(text="Leads by Week", font=dict(size=14, color=COLORS["text_secondary"])),
                height=220,
                margin=dict(l=0, r=0, t=35, b=30),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORS["text_secondary"], family="Urbanist, sans-serif"),
                xaxis=dict(gridcolor=COLORS["border"], showgrid=False, title=""),
                yaxis=dict(gridcolor="rgba(38,45,58,0.37)", griddash="dot", title="Leads"),
                showlegend=False,
            )
            st.plotly_chart(fig_leads, use_container_width=True)
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
