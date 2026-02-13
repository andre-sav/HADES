"""
Design System - Centralized UI components and styles for HADES.

Usage:
    from ui_components import inject_base_styles, page_header, status_badge, metric_card, step_indicator

    # At the start of every page:
    inject_base_styles()

    # Page header with optional action:
    page_header("Title", "Description", action_label="Refresh", action_callback=refresh_fn)

    # Status badges (replace emoji indicators):
    status_badge("success", "Active")
    status_badge("warning", "At Risk")
    status_badge("error", "Critical")

    # Enhanced metric cards:
    metric_card("Credits", 1234, delta="+50", delta_color="success")

    # Workflow step indicators:
    step_indicator(current=2, total=4, labels=["Search", "Select", "Enrich", "Export"])
"""

import streamlit as st
try:
    import streamlit_shadcn_ui as ui
except ImportError:
    ui = None  # Not available in test environment
from typing import Callable, Optional, Literal

# =============================================================================
# COLOR PALETTE
# =============================================================================

COLORS = {
    # Primary brand colors
    "primary": "#6366f1",       # Indigo-500
    "primary_light": "#818cf8", # Indigo-400
    "primary_dark": "#4f46e5",  # Indigo-600

    # Accent (gradient endpoint)
    "accent": "#06b6d4",        # Cyan-500
    "accent_light": "#22d3ee",  # Cyan-400
    "accent_dark": "#0891b2",   # Cyan-600

    # Semantic colors
    "success": "#22c55e",       # Green-500
    "success_light": "#4ade80", # Green-400
    "success_dark": "#16a34a",  # Green-600
    "success_bg": "#14532d",    # Green-900

    "warning": "#f59e0b",       # Amber-500
    "warning_light": "#fbbf24", # Amber-400
    "warning_dark": "#d97706",  # Amber-600
    "warning_bg": "#451a03",    # Amber-950

    "error": "#ef4444",         # Red-500
    "error_light": "#f87171",   # Red-400
    "error_dark": "#dc2626",    # Red-600
    "error_bg": "#450a0a",      # Red-950

    "info": "#3b82f6",          # Blue-500
    "info_light": "#60a5fa",    # Blue-400
    "info_dark": "#2563eb",     # Blue-600
    "info_bg": "#172554",       # Blue-950

    # Neutral colors (for dark mode)
    "bg_primary": "#0a0e14",    # Main background (deeper)
    "bg_secondary": "#141922",  # Card background
    "bg_tertiary": "#1e2530",   # Elevated surfaces
    "border": "#262d3a",        # Borders (subtler)
    "border_light": "#3a4350",  # Hover borders
    "text_primary": "#f0f2f5",  # Primary text (slightly softer)
    "text_secondary": "#8b929e",# Secondary text
    "text_muted": "#5c6370",    # Muted text
}

# =============================================================================
# FONTS
# =============================================================================

FONTS = {
    "display": "'Urbanist', sans-serif",
    "body": "'Urbanist', sans-serif",
    "mono": "'IBM Plex Mono', monospace",
}

# =============================================================================
# TYPOGRAPHY & SPACING
# =============================================================================

SPACING = {
    "xs": "0.25rem",   # 4px
    "sm": "0.5rem",    # 8px
    "md": "1rem",      # 16px
    "lg": "1.5rem",    # 24px
    "xl": "2rem",      # 32px
    "2xl": "3rem",     # 48px
}

FONT_SIZES = {
    "xs": "0.75rem",   # 12px
    "sm": "0.875rem",  # 14px
    "base": "1rem",    # 16px
    "lg": "1.125rem",  # 18px
    "xl": "1.25rem",   # 20px
    "2xl": "1.5rem",   # 24px
    "3xl": "1.875rem", # 30px
}

# =============================================================================
# LAYOUT PRESETS
# =============================================================================

LAYOUT = {
    "header": [3, 1],           # Title + action
    "filters": [1, 1, 1, 1],    # 4 equal columns
    "form_2col": [1, 1],        # Equal columns
    "action_row": [1, 1, 2],    # 2 buttons + spacer
    "metric_4col": [1, 1, 1, 1],# 4 metrics
    "metric_3col": [1, 1, 1],   # 3 metrics
    "content_sidebar": [3, 1],  # Main content + sidebar
}

# =============================================================================
# BASE STYLES
# =============================================================================

def inject_base_styles():
    """
    Inject base CSS styles. Call once at the start of each page.
    Loads Google Fonts, applies global theme, and styles native Streamlit widgets.
    """
    # Load Google Fonts via <link> (more reliable than @import in <style>)
    st.markdown(
        '<link href="https://fonts.googleapis.com/css2?family=Urbanist:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">',
        unsafe_allow_html=True,
    )

    st.markdown(f"""
<style>
    /* ================================================================
       CSS CUSTOM PROPERTIES
       ================================================================ */
    :root {{
        --font-display: {FONTS['display']};
        --font-body: {FONTS['body']};
        --font-mono: {FONTS['mono']};
        --accent-gradient: linear-gradient(135deg, {COLORS['primary']}, {COLORS['accent']});
        --accent-gradient-h: linear-gradient(90deg, {COLORS['primary']}, {COLORS['accent']});
        --card-shadow: 0 1px 3px rgba(0,0,0,0.24), 0 1px 2px rgba(0,0,0,0.16);
        --card-shadow-hover: 0 4px 14px rgba(0,0,0,0.32), 0 2px 4px rgba(0,0,0,0.2);
        --radius: 10px;
        --radius-sm: 6px;
        --transition: 0.2s ease;
    }}

    /* ================================================================
       GLOBAL FONT OVERRIDE
       ================================================================ */
    html, body, [class*="css"], .stMarkdown, .stText,
    div[data-testid="stAppViewContainer"],
    div[data-testid="stHeader"] {{
        font-family: var(--font-body) !important;
    }}

    h1, h2, h3, h4, h5, h6,
    .stTitle, [data-testid="stHeading"] {{
        font-family: var(--font-display) !important;
        letter-spacing: -0.025em;
    }}

    h1 {{
        font-weight: 800 !important;
        font-size: {FONT_SIZES['3xl']} !important;
    }}

    h2 {{
        font-weight: 700 !important;
    }}

    h3 {{
        font-weight: 600 !important;
    }}

    /* Monospace for data values */
    div[data-testid="stMetricValue"] > div,
    .metric-card-value,
    .summary-item .value,
    .metric-inline .value {{
        font-family: var(--font-mono) !important;
        font-variant-numeric: tabular-nums;
    }}

    /* ================================================================
       BASE CONTAINER
       ================================================================ */
    .block-container {{
        padding-top: 1.25rem;
        max-width: 100%;
        padding-left: 2rem;
        padding-right: 2rem;
    }}

    /* Subtle background vignette for depth */
    div[data-testid="stAppViewContainer"] {{
        background:
            radial-gradient(ellipse at 20% 0%, {COLORS['primary']}06 0%, transparent 50%),
            radial-gradient(ellipse at 80% 100%, {COLORS['accent']}04 0%, transparent 50%),
            {COLORS['bg_primary']} !important;
    }}

    /* ================================================================
       PAGE LOAD ANIMATION
       ================================================================ */
    @keyframes fadeInUp {{
        from {{ opacity: 0; transform: translateY(6px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}

    .main .block-container > div {{
        animation: fadeInUp 0.3s ease-out both;
    }}

    /* Shimmer animation for skeleton loading */
    @keyframes shimmer {{
        0% {{ background-position: 200% 0; }}
        100% {{ background-position: -200% 0; }}
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - BUTTONS
       ================================================================ */
    button[data-testid="stBaseButton-primary"] {{
        background: var(--accent-gradient) !important;
        border: none !important;
        font-family: var(--font-body) !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        letter-spacing: 0.01em;
        transition: all var(--transition) !important;
    }}

    button[data-testid="stBaseButton-primary"]:hover {{
        filter: brightness(1.1) !important;
        box-shadow: 0 4px 16px {COLORS['primary']}40 !important;
    }}

    button[data-testid="stBaseButton-primary"]:active {{
        transform: scale(0.98) !important;
    }}

    button[data-testid="stBaseButton-secondary"],
    button[data-testid="stBaseButton-minimal"] {{
        border: 1px solid {COLORS['border']} !important;
        border-radius: 8px !important;
        font-family: var(--font-body) !important;
        font-weight: 500 !important;
        transition: all var(--transition) !important;
    }}

    button[data-testid="stBaseButton-secondary"]:hover,
    button[data-testid="stBaseButton-minimal"]:hover {{
        border-color: {COLORS['primary']} !important;
        color: {COLORS['primary_light']} !important;
        background: {COLORS['primary']}0a !important;
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - INPUTS
       ================================================================ */
    div[data-testid="stTextInput"] input,
    div[data-testid="stNumberInput"] input,
    div[data-testid="stTextArea"] textarea {{
        border-radius: 8px !important;
        border: 1px solid {COLORS['border']} !important;
        background: {COLORS['bg_primary']} !important;
        font-family: var(--font-body) !important;
        transition: border-color var(--transition), box-shadow var(--transition) !important;
    }}

    div[data-testid="stTextInput"] input:focus,
    div[data-testid="stNumberInput"] input:focus,
    div[data-testid="stTextArea"] textarea:focus {{
        border-color: {COLORS['primary']} !important;
        box-shadow: 0 0 0 2px {COLORS['primary']}20 !important;
    }}

    /* Input labels */
    div[data-testid="stTextInput"] label,
    div[data-testid="stNumberInput"] label,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stMultiSelect"] label,
    div[data-testid="stTextArea"] label {{
        font-family: var(--font-body) !important;
        font-size: {FONT_SIZES['xs']} !important;
        font-weight: 500 !important;
        color: {COLORS['text_secondary']} !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}

    /* Selectbox/Multiselect */
    div[data-testid="stSelectbox"] > div > div,
    div[data-testid="stMultiSelect"] > div > div {{
        border-radius: 8px !important;
        border-color: {COLORS['border']} !important;
        transition: border-color var(--transition) !important;
    }}

    div[data-testid="stSelectbox"] > div > div:hover,
    div[data-testid="stMultiSelect"] > div > div:hover {{
        border-color: {COLORS['border_light']} !important;
    }}

    /* Prevent truncation in multiselect pills */
    div[data-baseweb="tag"] > span {{
        max-width: none !important;
    }}
    div[data-baseweb="tag"] {{
        max-width: none !important;
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - DATAFRAME
       ================================================================ */
    div[data-testid="stDataFrame"] {{
        border-radius: var(--radius) !important;
        overflow: hidden;
        border: 1px solid {COLORS['border']};
    }}

    /* Glide data grid header cells */
    div[data-testid="stDataFrame"] [data-testid="glideDataEditor"] {{
        font-family: var(--font-body) !important;
    }}

    /* Glide data grid alternating rows and hover */
    div[data-testid="stDataFrame"] canvas + div {{
        font-family: var(--font-body) !important;
    }}

    /* HTML table styling (for st.table and custom HTML tables) */
    .styled-table {{
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        border-radius: var(--radius);
        overflow: hidden;
        border: 1px solid {COLORS['border']};
        font-family: var(--font-body);
        font-size: {FONT_SIZES['sm']};
    }}

    .styled-table thead th {{
        background: {COLORS['bg_tertiary']};
        color: {COLORS['text_secondary']};
        font-size: {FONT_SIZES['xs']};
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        padding: 10px 14px;
        text-align: left;
        border-bottom: 1px solid {COLORS['border']};
    }}

    .styled-table tbody tr {{
        transition: background var(--transition);
    }}

    .styled-table tbody tr:nth-child(even) {{
        background: {COLORS['bg_secondary']}80;
    }}

    .styled-table tbody tr:hover {{
        background: {COLORS['bg_tertiary']};
    }}

    .styled-table tbody td {{
        padding: 10px 14px;
        border-bottom: 1px solid {COLORS['border']}60;
        color: {COLORS['text_primary']};
    }}

    .styled-table tbody td.mono {{
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
    }}

    /* Status pill */
    .status-pill {{
        display: inline-block;
        padding: 2px 10px;
        border-radius: 9999px;
        font-size: {FONT_SIZES['xs']};
        font-weight: 500;
        line-height: 1.6;
    }}

    .status-pill-success {{
        background: {COLORS['success_bg']};
        color: {COLORS['success_light']};
    }}

    .status-pill-muted {{
        background: {COLORS['bg_tertiary']};
        color: {COLORS['text_muted']};
    }}

    .status-pill-info {{
        background: {COLORS['info_bg']};
        color: {COLORS['info_light']};
    }}

    .status-pill-warning {{
        background: {COLORS['warning_bg']};
        color: {COLORS['warning_light']};
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - EXPANDER
       ================================================================ */
    div[data-testid="stExpander"] {{
        border: 1px solid {COLORS['border']} !important;
        border-radius: var(--radius) !important;
        overflow: hidden;
        background: {COLORS['bg_secondary']};
        transition: border-color var(--transition);
    }}

    div[data-testid="stExpander"]:hover {{
        border-color: {COLORS['border_light']} !important;
    }}

    div[data-testid="stExpander"] summary {{
        font-family: var(--font-body) !important;
        font-weight: 500;
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - TABS
       ================================================================ */
    div[data-testid="stTabs"] button[data-baseweb="tab"] {{
        font-family: var(--font-body) !important;
        font-weight: 500 !important;
        font-size: 0.875rem !important;
        letter-spacing: 0.01em;
        transition: color var(--transition) !important;
    }}

    /* Active tab indicator */
    div[data-testid="stTabs"] [aria-selected="true"] {{
        font-weight: 600 !important;
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - SIDEBAR
       ================================================================ */
    section[data-testid="stSidebar"] {{
        background: {COLORS['bg_secondary']} !important;
        border-right: 1px solid {COLORS['border']} !important;
    }}

    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li {{
        border-radius: 8px;
    }}

    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{
        font-family: var(--font-body) !important;
        font-weight: 500;
        border-radius: 8px;
        transition: background var(--transition);
    }}

    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {{
        background: {COLORS['bg_tertiary']};
    }}

    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {{
        background: {COLORS['primary']}15;
        border-left: 2px solid {COLORS['primary']};
    }}

    /* Sidebar page icons via CSS */
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a span::before {{
        margin-right: 8px;
        font-style: normal;
        opacity: 0.7;
    }}

    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(1) a span::before {{ content: "◉"; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(2) a span::before {{ content: "🎯"; font-size: 0.85em; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(3) a span::before {{ content: "📍"; font-size: 0.85em; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(4) a span::before {{ content: "👤"; font-size: 0.85em; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(5) a span::before {{ content: "📤"; font-size: 0.85em; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(6) a span::before {{ content: "📊"; font-size: 0.85em; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(7) a span::before {{ content: "📈"; font-size: 0.85em; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(8) a span::before {{ content: "🧪"; font-size: 0.85em; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] li:nth-child(9) a span::before {{ content: "🔬"; font-size: 0.85em; }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - DIVIDER
       ================================================================ */
    hr {{
        border: none !important;
        height: 1px !important;
        background: linear-gradient(90deg, transparent, {COLORS['border']}, transparent) !important;
        margin: 0.75rem 0 !important;
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - METRICS
       ================================================================ */
    div[data-testid="stMetric"] {{
        background: transparent;
    }}

    div[data-testid="stMetricLabel"] {{
        font-family: var(--font-body) !important;
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - STATUS/SPINNER
       ================================================================ */
    div[data-testid="stStatusWidget"] {{
        border-radius: var(--radius) !important;
        border: 1px solid {COLORS['border']} !important;
    }}

    /* ================================================================
       NATIVE WIDGET OVERRIDES - CAPTION
       ================================================================ */
    .stCaption, [data-testid="stCaptionContainer"] {{
        font-family: var(--font-body) !important;
        letter-spacing: 0.01em;
    }}

    /* ================================================================
       SCROLLBAR
       ================================================================ */
    ::-webkit-scrollbar {{
        width: 6px;
        height: 6px;
    }}
    ::-webkit-scrollbar-track {{
        background: transparent;
    }}
    ::-webkit-scrollbar-thumb {{
        background: {COLORS['border']};
        border-radius: 3px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background: {COLORS['border_light']};
    }}

    /* ================================================================
       STATUS BADGES - WCAG AA compliant
       ================================================================ */
    .status-badge {{
        display: inline-flex;
        align-items: center;
        gap: {SPACING['xs']};
        padding: {SPACING['xs']} {SPACING['sm']};
        border-radius: 9999px;
        font-family: var(--font-body);
        font-size: {FONT_SIZES['sm']};
        font-weight: 500;
        line-height: 1;
        min-height: 24px;
    }}

    .status-badge-success {{
        background-color: {COLORS['success_bg']};
        color: {COLORS['success_light']};
        border: 1px solid {COLORS['success_dark']};
    }}

    .status-badge-warning {{
        background-color: {COLORS['warning_bg']};
        color: {COLORS['warning_light']};
        border: 1px solid {COLORS['warning_dark']};
    }}

    .status-badge-error {{
        background-color: {COLORS['error_bg']};
        color: {COLORS['error_light']};
        border: 1px solid {COLORS['error_dark']};
    }}

    .status-badge-info {{
        background-color: {COLORS['info_bg']};
        color: {COLORS['info_light']};
        border: 1px solid {COLORS['info_dark']};
    }}

    .status-badge-neutral {{
        background-color: {COLORS['bg_tertiary']};
        color: {COLORS['text_secondary']};
        border: 1px solid {COLORS['border']};
    }}

    /* ================================================================
       STEP INDICATOR
       ================================================================ */
    .step-indicator {{
        display: flex;
        align-items: center;
        gap: {SPACING['sm']};
        margin: {SPACING['sm']} 0;
    }}

    .step {{
        display: flex;
        align-items: center;
        gap: {SPACING['xs']};
    }}

    .step-number {{
        width: 26px;
        height: 26px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: var(--font-mono);
        font-size: {FONT_SIZES['xs']};
        font-weight: 600;
        transition: all var(--transition);
    }}

    .step-number-active {{
        background: var(--accent-gradient);
        color: white;
        box-shadow: 0 0 12px {COLORS['primary']}40;
    }}

    .step-number-completed {{
        background-color: {COLORS['success']};
        color: white;
    }}

    .step-number-pending {{
        background-color: {COLORS['bg_tertiary']};
        color: {COLORS['text_muted']};
        border: 1px solid {COLORS['border']};
    }}

    .step-label {{
        font-family: var(--font-body);
        font-size: {FONT_SIZES['sm']};
    }}

    .step-label-active {{
        color: {COLORS['text_primary']};
        font-weight: 600;
    }}

    .step-label-completed {{
        color: {COLORS['success_light']};
    }}

    .step-label-pending {{
        color: {COLORS['text_muted']};
    }}

    .step-connector {{
        flex: 1;
        height: 2px;
        background-color: {COLORS['border']};
        min-width: 20px;
        max-width: 60px;
        transition: background var(--transition);
    }}

    .step-connector-completed {{
        background: var(--accent-gradient-h);
    }}

    /* ================================================================
       METRIC CARD (custom HTML cards)
       ================================================================ */
    .metric-card {{
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: var(--radius);
        padding: 1rem 1rem 0.75rem;
        position: relative;
        overflow: hidden;
        box-shadow: var(--card-shadow);
        transition: box-shadow var(--transition), border-color var(--transition);
    }}

    .metric-card:hover {{
        box-shadow: var(--card-shadow-hover);
        border-color: {COLORS['border_light']};
    }}

    .metric-card-value {{
        font-size: 1.5rem;
        font-weight: 700;
        color: {COLORS['text_primary']};
        margin: 0;
        line-height: 1.2;
    }}

    .metric-card-label {{
        font-family: var(--font-body);
        font-size: {FONT_SIZES['xs']};
        font-weight: 500;
        color: {COLORS['text_muted']};
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin: 0 0 4px 0;
    }}

    .metric-card-delta {{
        font-family: var(--font-mono);
        font-size: {FONT_SIZES['sm']};
        font-weight: 500;
        margin-left: {SPACING['sm']};
    }}

    .metric-delta-positive {{
        color: {COLORS['success']};
    }}

    .metric-delta-negative {{
        color: {COLORS['error']};
    }}

    .metric-delta-neutral {{
        color: {COLORS['text_muted']};
    }}

    /* ================================================================
       COMPANY GROUP CARDS (Geography Workflow)
       ================================================================ */
    .company-group {{
        border: 1px solid {COLORS['border']};
        border-radius: var(--radius);
        padding: {SPACING['md']};
        margin-bottom: {SPACING['md']};
        background: {COLORS['bg_secondary']};
        box-shadow: var(--card-shadow);
        transition: border-color var(--transition), box-shadow var(--transition);
    }}

    .company-group:hover {{
        border-color: {COLORS['border_light']};
    }}

    .best-pick {{
        background: {COLORS['success_bg']};
        border-left: 3px solid {COLORS['success']};
        padding-left: {SPACING['sm']};
    }}

    /* ================================================================
       PAGE HEADER
       ================================================================ */
    .page-header {{
        margin-bottom: {SPACING['md']};
    }}

    .page-header h1 {{
        margin-bottom: {SPACING['xs']};
    }}

    /* ================================================================
       PROGRESS BARS
       ================================================================ */
    .progress-bar-container {{
        background: {COLORS['bg_tertiary']};
        border-radius: 4px;
        height: 8px;
        overflow: hidden;
    }}

    .progress-bar-fill {{
        height: 100%;
        border-radius: 4px;
        transition: width 0.4s ease;
    }}

    .progress-bar-success {{
        background: var(--accent-gradient-h);
    }}

    .progress-bar-warning {{
        background: linear-gradient(90deg, {COLORS['warning_dark']}, {COLORS['warning']});
    }}

    .progress-bar-error {{
        background: linear-gradient(90deg, {COLORS['error_dark']}, {COLORS['error']});
    }}

    .progress-bar-info {{
        background: var(--accent-gradient-h);
    }}

    /* ================================================================
       QUICK ACTION CARDS (home page)
       ================================================================ */
    .quick-action {{
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: var(--radius);
        padding: 1.25rem;
        text-align: center;
        transition: border-color var(--transition), box-shadow var(--transition), transform var(--transition);
    }}

    .quick-action:hover {{
        border-color: {COLORS['primary']}60;
        box-shadow: 0 4px 16px {COLORS['primary']}12;
        transform: translateY(-1px);
    }}

    .quick-action .icon {{
        font-size: 1.5rem;
        margin-bottom: 0.25rem;
        opacity: 0.85;
    }}

    .quick-action .title {{
        font-weight: 600;
        color: {COLORS['text_primary']};
        margin-bottom: 0.125rem;
        font-size: {FONT_SIZES['base']};
    }}

    .quick-action .desc {{
        font-size: {FONT_SIZES['xs']};
        color: {COLORS['text_muted']};
        line-height: 1.4;
    }}

    /* ================================================================
       CONTACT CARDS (pagination)
       ================================================================ */
    .contact-card {{
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: var(--radius);
        padding: {SPACING['md']};
        margin-bottom: {SPACING['sm']};
        transition: border-color var(--transition), box-shadow var(--transition);
    }}

    .contact-card:hover {{
        border-color: {COLORS['border_light']};
        box-shadow: var(--card-shadow);
    }}

    .contact-card-selected {{
        border-color: {COLORS['primary']};
        background: {COLORS['bg_tertiary']};
        box-shadow: 0 0 0 1px {COLORS['primary']}30;
    }}

    .contact-card-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: {SPACING['sm']};
    }}

    .contact-card-name {{
        font-weight: 600;
        color: {COLORS['text_primary']};
    }}

    .contact-card-title {{
        font-size: {FONT_SIZES['sm']};
        color: {COLORS['text_secondary']};
    }}

    .contact-card-details {{
        font-family: var(--font-mono);
        font-size: {FONT_SIZES['xs']};
        color: {COLORS['text_muted']};
    }}

    /* ================================================================
       PAGINATION
       ================================================================ */
    .pagination {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: {SPACING['md']};
        margin: {SPACING['lg']} 0;
    }}

    .pagination-info {{
        font-family: var(--font-mono);
        font-size: {FONT_SIZES['sm']};
        color: {COLORS['text_secondary']};
    }}

    /* ================================================================
       TYPOGRAPHY UTILITIES
       ================================================================ */
    .section-title {{
        font-family: var(--font-display);
        font-size: {FONT_SIZES['xl']};
        font-weight: 700;
        color: {COLORS['text_primary']};
        letter-spacing: -0.02em;
        margin-bottom: {SPACING['md']};
    }}

    .subsection-title {{
        font-family: var(--font-display);
        font-size: {FONT_SIZES['lg']};
        font-weight: 600;
        color: {COLORS['text_primary']};
        margin-bottom: {SPACING['sm']};
    }}

    .field-label {{
        font-family: var(--font-body);
        font-size: {FONT_SIZES['xs']};
        font-weight: 500;
        color: {COLORS['text_muted']};
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: {SPACING['xs']};
    }}

    /* Spacing utilities */
    .section-gap {{
        margin-top: {SPACING['xl']};
        margin-bottom: {SPACING['lg']};
    }}

    .subsection-gap {{
        margin-top: {SPACING['lg']};
        margin-bottom: {SPACING['md']};
    }}

    /* ================================================================
       ACTION BAR
       ================================================================ */
    .action-bar {{
        display: flex;
        align-items: center;
        gap: {SPACING['md']};
        padding: {SPACING['sm']} {SPACING['md']};
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: var(--radius);
        margin-bottom: {SPACING['md']};
        box-shadow: var(--card-shadow);
    }}

    .action-bar-left {{
        display: flex;
        align-items: center;
        gap: {SPACING['md']};
        flex: 1;
    }}

    /* ================================================================
       SUMMARY STRIP
       ================================================================ */
    .summary-strip {{
        display: flex;
        gap: {SPACING['xl']};
        padding: {SPACING['sm']} 0;
        border-bottom: 1px solid {COLORS['border']};
        margin-bottom: {SPACING['md']};
    }}

    .summary-item {{
        display: flex;
        flex-direction: column;
    }}

    .summary-item .label {{
        font-family: var(--font-body);
        font-size: 0.6875rem;
        color: {COLORS['text_muted']};
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 500;
    }}

    .summary-item .value {{
        font-size: {FONT_SIZES['lg']};
        font-weight: 600;
        color: {COLORS['text_primary']};
    }}

    /* Inline metric (compact horizontal) */
    .metric-inline {{
        display: inline-flex;
        flex-direction: column;
        padding: 0 12px;
    }}

    .metric-inline .label {{
        font-family: var(--font-body);
        font-size: 0.6875rem;
        color: {COLORS['text_muted']};
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-weight: 500;
    }}

    .metric-inline .value {{
        font-size: {FONT_SIZES['base']};
        font-weight: 600;
        color: {COLORS['text_primary']};
    }}

    /* ================================================================
       EXPORT VALIDATION
       ================================================================ */
    .validation-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: {SPACING['sm']};
        margin-bottom: {SPACING['md']};
    }}

    .validation-item {{
        display: flex;
        align-items: center;
        gap: {SPACING['sm']};
        padding: {SPACING['sm']} {SPACING['md']};
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: var(--radius-sm);
        font-family: var(--font-body);
        font-size: {FONT_SIZES['sm']};
        transition: border-color var(--transition);
    }}

    .validation-item:hover {{
        border-color: {COLORS['border_light']};
    }}

    .validation-dot {{
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }}

    /* ================================================================
       SHADCN UI IFRAME
       ================================================================ */
    iframe[title*="streamlit_shadcn_ui"] {{
        border: none !important;
        color-scheme: dark;
    }}

    /* ================================================================
       ACCESSIBILITY
       ================================================================ */
    button:focus-visible,
    a:focus-visible,
    input:focus-visible,
    select:focus-visible,
    textarea:focus-visible {{
        outline: 2px solid {COLORS['primary']};
        outline-offset: 2px;
    }}

    @media (prefers-reduced-motion: reduce) {{
        *,
        *::before,
        *::after {{
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
        }}
    }}

    @media (prefers-contrast: high) {{
        .status-badge {{
            border-width: 2px;
        }}
        .contact-card,
        .metric-card,
        .company-group {{
            border-width: 2px;
        }}
    }}

    .sr-only {{
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }}
</style>
""", unsafe_allow_html=True)


# =============================================================================
# PAGE HEADER
# =============================================================================

def page_header(
    title: str,
    caption: Optional[str] = None,
    action_label: Optional[str] = None,
    action_callback: Optional[Callable] = None,
    action_icon: Optional[str] = None,
    right_content: Optional[tuple[str, str]] = None,
) -> None:
    """
    Render a consistent page header with optional action button or right content.

    Args:
        title: The page title
        caption: Optional subtitle/description
        action_label: Optional button label (e.g., "Refresh")
        action_callback: Function to call when button clicked
        action_icon: Optional icon for the button
        right_content: Optional tuple of (badge_html, caption) to display on right side
                       Example: (status_badge("info", "1,234 credits"), "This week")
    """
    col1, col2 = st.columns(LAYOUT["header"])

    with col1:
        st.title(title)
        if caption:
            st.caption(caption)

    with col2:
        if action_label and action_callback:
            st.markdown("")  # Align vertically with title
            if st.button(
                action_label if not action_icon else f"{action_icon} {action_label}",
                use_container_width=True
            ):
                action_callback()
        elif right_content:
            badge_html, right_caption = right_content
            st.markdown("")  # Add spacing to align with title
            st.markdown(badge_html, unsafe_allow_html=True)
            if right_caption:
                st.caption(right_caption)

    st.markdown("---")


# =============================================================================
# STATUS BADGE
# =============================================================================

StatusType = Literal["success", "warning", "error", "info", "neutral"]

def status_badge(
    status: StatusType,
    label: str,
    icon: Optional[str] = None,
) -> str:
    """
    Create a colored status badge (replaces emoji indicators).

    Args:
        status: One of "success", "warning", "error", "info", "neutral"
        label: The badge text
        icon: Optional icon character

    Returns:
        HTML string for the badge (WCAG AA compliant)

    Usage:
        st.markdown(status_badge("success", "Active"), unsafe_allow_html=True)
    """
    icon_html = f"{icon} " if icon else ""
    # Add ARIA role for accessibility
    return f'<span class="status-badge status-badge-{status}" role="status">{icon_html}{label}</span>'


def status_badge_from_percent(
    percent: float,
    label: Optional[str] = None,
) -> str:
    """
    Create a status badge based on percentage thresholds.

    Args:
        percent: 0-100 value
        label: Optional custom label (defaults to percentage)

    Returns:
        HTML string for the badge
    """
    display_label = label or f"{percent:.0f}%"

    if percent > 90:
        return status_badge("error", display_label)
    elif percent > 70:
        return status_badge("warning", display_label)
    else:
        return status_badge("success", display_label)


def budget_status_badge(percent: float, remaining: int) -> str:
    """
    Create a budget status badge with remaining credits.

    Args:
        percent: Current usage percentage (0-100)
        remaining: Credits remaining

    Returns:
        HTML string showing status badge with remaining count
    """
    if percent > 90:
        return status_badge("error", f"{remaining:,} left")
    elif percent > 70:
        return status_badge("warning", f"{remaining:,} left")
    else:
        return status_badge("success", f"{remaining:,} left")


# =============================================================================
# METRIC CARD
# =============================================================================

DeltaColor = Literal["success", "error", "neutral", "auto"]

def metric_card(
    label: str,
    value: str | int | float,
    delta: Optional[str | int | float] = None,
    delta_color: DeltaColor = "auto",
    help_text: Optional[str] = None,
) -> None:
    """
    Render an enhanced metric card with optional delta indicator.

    Args:
        label: Metric label
        value: Metric value
        delta: Optional change indicator (e.g., "+50" or -10)
        delta_color: Color for delta ("success", "error", "neutral", or "auto" to infer from sign)
        help_text: Optional tooltip text
    """
    # Format value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        formatted_value = f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"
    else:
        formatted_value = str(value)

    # Build delta HTML
    delta_html = ""
    if delta is not None:
        # Determine delta color
        if delta_color == "auto":
            if isinstance(delta, (int, float)):
                delta_color = "positive" if delta > 0 else "negative" if delta < 0 else "neutral"
            elif isinstance(delta, str):
                delta_color = "positive" if delta.startswith("+") else "negative" if delta.startswith("-") else "neutral"
            else:
                delta_color = "neutral"
        else:
            # Map our colors to CSS classes
            color_map = {"success": "positive", "error": "negative", "neutral": "neutral"}
            delta_color = color_map.get(delta_color, "neutral")

        delta_text = str(delta)
        delta_html = f'<span class="metric-card-delta metric-delta-{delta_color}">{delta_text}</span>'

    # Render
    html = f"""
    <div class="metric-card">
        <p class="metric-card-label">{label}</p>
        <p class="metric-card-value">{formatted_value}{delta_html}</p>
    </div>
    """

    if help_text:
        st.markdown(html, unsafe_allow_html=True, help=help_text)
    else:
        st.markdown(html, unsafe_allow_html=True)


# =============================================================================
# STEP INDICATOR
# =============================================================================

def step_indicator(
    current: int,
    total: int,
    labels: list[str],
) -> None:
    """
    Render a workflow step indicator.

    Args:
        current: Current step (1-indexed)
        total: Total number of steps
        labels: List of step labels

    Example:
        step_indicator(2, 4, ["Search", "Select", "Enrich", "Export"])

    Accessibility:
        - Uses aria-current to indicate current step
        - Includes screen reader text for step status
    """
    if len(labels) != total:
        raise ValueError(f"Expected {total} labels, got {len(labels)}")

    steps_html = []

    for i, label in enumerate(labels, 1):
        if i < current:
            # Completed
            number_class = "step-number-completed"
            label_class = "step-label-completed"
            check = "&#10003;"  # Checkmark
            number = check
            aria_label = f"Step {i}: {label} (completed)"
            aria_current = ""
        elif i == current:
            # Active
            number_class = "step-number-active"
            label_class = "step-label-active"
            number = str(i)
            aria_label = f"Step {i}: {label} (current)"
            aria_current = 'aria-current="step"'
        else:
            # Pending
            number_class = "step-number-pending"
            label_class = "step-label-pending"
            number = str(i)
            aria_label = f"Step {i}: {label} (pending)"
            aria_current = ""

        step_html = f'''
        <div class="step" {aria_current} aria-label="{aria_label}">
            <span class="step-number {number_class}" aria-hidden="true">{number}</span>
            <span class="step-label {label_class}">{label}</span>
        </div>
        '''
        steps_html.append(step_html)

        # Add connector (except after last step)
        if i < total:
            connector_class = "step-connector-completed" if i < current else ""
            steps_html.append(f'<div class="step-connector {connector_class}" aria-hidden="true"></div>')

    # Wrap in nav with aria-label for screen readers
    full_html = f'<nav aria-label="Workflow progress" class="step-indicator" role="navigation">{"".join(steps_html)}</nav>'
    st.markdown(full_html, unsafe_allow_html=True)


# =============================================================================
# PROGRESS BAR
# =============================================================================

def colored_progress_bar(
    percent: float,
    height: int = 10,
) -> None:
    """
    Render a colored progress bar that changes color based on value.

    Args:
        percent: 0-100 value
        height: Bar height in pixels
    """
    # Determine color based on percentage
    if percent > 90:
        color_class = "progress-bar-error"
    elif percent > 70:
        color_class = "progress-bar-warning"
    else:
        color_class = "progress-bar-success"

    # Clamp to 0-100
    width = max(0, min(100, percent))

    html = f'''
    <div class="progress-bar-container" style="height: {height}px;">
        <div class="progress-bar-fill {color_class}" style="width: {width}%;"></div>
    </div>
    '''
    st.markdown(html, unsafe_allow_html=True)


# =============================================================================
# PAGINATION HELPER
# =============================================================================

def paginate_items(
    items: list,
    page_size: int = 10,
    page_key: str = "page",
) -> tuple[list, int, int]:
    """
    Paginate a list of items with session state tracking.

    Args:
        items: List of items to paginate
        page_size: Items per page
        page_key: Session state key for tracking current page

    Returns:
        Tuple of (current_page_items, current_page, total_pages)
    """
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)

    # Initialize session state
    if page_key not in st.session_state:
        st.session_state[page_key] = 1

    current_page = st.session_state[page_key]

    # Clamp to valid range
    current_page = max(1, min(current_page, total_pages))
    st.session_state[page_key] = current_page

    # Slice items
    start_idx = (current_page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = items[start_idx:end_idx]

    return page_items, current_page, total_pages


def pagination_controls(
    current_page: int,
    total_pages: int,
    page_key: str = "page",
) -> None:
    """
    Render pagination controls (Previous, Page X of Y, Next).

    Args:
        current_page: Current page number (1-indexed)
        total_pages: Total number of pages
        page_key: Session state key for tracking current page
    """
    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if st.button("Previous", disabled=current_page <= 1, key=f"{page_key}_prev"):
            st.session_state[page_key] = current_page - 1
            st.rerun()

    with col2:
        st.markdown(
            f'<div class="pagination-info" style="text-align: center;">Page {current_page} of {total_pages}</div>',
            unsafe_allow_html=True
        )

    with col3:
        if st.button("Next", disabled=current_page >= total_pages, key=f"{page_key}_next"):
            st.session_state[page_key] = current_page + 1
            st.rerun()


# =============================================================================
# CONTACT CARD (for Geography Workflow pagination)
# =============================================================================

def contact_card(
    contact: dict,
    is_selected: bool = False,
    is_best_pick: bool = False,
    show_select: bool = True,
    key_suffix: str = "",
) -> bool:
    """
    Render a contact card with selection capability.

    Args:
        contact: Contact dict with firstName, lastName, jobTitle, etc.
        is_selected: Whether this contact is currently selected
        is_best_pick: Whether to show "Best Pick" indicator
        show_select: Whether to show selection checkbox
        key_suffix: Unique suffix for widget keys

    Returns:
        True if selected, False otherwise
    """
    name = f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or "Unknown"
    title = contact.get("jobTitle", "")
    score = contact.get("contactAccuracyScore", 0)
    phone = contact.get("directPhone", "") or contact.get("phone", "")
    contact_zip = contact.get("zipCode", "")

    card_class = "contact-card-selected" if is_selected else ""
    if is_best_pick:
        card_class += " best-pick"

    details = []
    if score:
        details.append(f"Score: {score}")
    if contact_zip:
        details.append(f"ZIP: {contact_zip}")
    if phone:
        details.append(phone)

    details_text = " | ".join(details)

    # Use columns for layout with checkbox
    if show_select:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**{name}**" + (" (Best Pick)" if is_best_pick else ""))
            if title:
                st.caption(title)
            if details_text:
                st.caption(details_text)
        with col2:
            return st.checkbox("Select", value=is_selected, key=f"contact_select_{key_suffix}", label_visibility="collapsed")
    else:
        st.markdown(f"**{name}**" + (" (Best Pick)" if is_best_pick else ""))
        if title:
            st.caption(title)
        if details_text:
            st.caption(details_text)
        return is_selected


# =============================================================================
# DIVIDER WITH LABEL
# =============================================================================

def labeled_divider(label: str) -> None:
    """
    Render a section divider with a label.

    Args:
        label: Text to display in the divider
    """
    st.markdown(
        f'''
        <div style="display: flex; align-items: center; margin: {SPACING['lg']} 0 {SPACING['md']} 0;">
            <div style="flex: 0 0 auto; height: 1px; width: 24px; background: linear-gradient(90deg, transparent, {COLORS['border']});"></div>
            <span style="padding: 0 {SPACING['sm']}; color: {COLORS['text_secondary']}; font-size: {FONT_SIZES['xs']}; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 500;">{label}</span>
            <div style="flex: 1; height: 1px; background: linear-gradient(90deg, {COLORS['border']}, transparent);"></div>
        </div>
        ''',
        unsafe_allow_html=True
    )


# =============================================================================
# PARAMETER GROUP (Phase 2 - Collapsible Filter Sections)
# =============================================================================

def parameter_group(
    title: str,
    summary: str,
    expanded: bool = False,
    key: Optional[str] = None,
) -> "streamlit.expander":
    """
    Create a collapsible parameter group with a summary line.

    Wraps st.expander with consistent styling and a summary display.

    Args:
        title: Group title (e.g., "Location", "Contact Requirements")
        summary: Brief summary of current settings (e.g., "15mi from 75201 (42 ZIPs, TX)")
        expanded: Whether the group starts expanded
        key: Optional unique key for the expander widget

    Returns:
        A Streamlit expander context manager

    Usage:
        with parameter_group("Location", "15mi from 75201", expanded=False):
            # Your widgets here
            center_zip = st.text_input("Center ZIP", ...)
    """
    # Format the label with summary
    label = f"**{title}** · {summary}" if summary else f"**{title}**"
    return st.expander(label, expanded=expanded)


# =============================================================================
# QUERY SUMMARY BAR (Phase 2 - Query State Display)
# =============================================================================

QueryState = Literal["ready", "stale", "loading", "executed"]

def query_summary_bar(
    params: dict,
    state: QueryState,
    result_count: Optional[int] = None,
) -> None:
    """
    Display a query summary bar showing current parameters and state.

    Args:
        params: Dict with keys like 'zip_count', 'radius', 'states', 'accuracy_min', etc.
        state: Query state - "ready" (green), "stale" (amber), "loading" (blue), "executed" (green check)
        result_count: Number of results (shown when state is "executed")

    Usage:
        query_summary_bar(
            params={"zip_count": 42, "radius": 15, "states": ["TX"], "accuracy_min": 95},
            state="ready"
        )
    """
    # Build summary text
    parts = []
    if params.get("radius"):
        parts.append(f"{params['radius']}mi radius")
    if params.get("zip_count"):
        parts.append(f"{params['zip_count']} ZIPs")
    if params.get("states"):
        states = params["states"]
        if isinstance(states, list):
            parts.append(", ".join(states[:3]) + ("..." if len(states) > 3 else ""))
        else:
            parts.append(str(states))
    if params.get("accuracy_min"):
        parts.append(f"{params['accuracy_min']}+ accuracy")
    if params.get("target_contacts"):
        parts.append(f"target: {params['target_contacts']}")

    summary_text = " · ".join(parts) if parts else "Configure search parameters"

    # State-specific styling
    state_config = {
        "ready": {
            "color": COLORS["success"],
            "bg": COLORS["success_bg"],
            "border": COLORS["success_dark"],
            "icon": "✓",
            "label": "Ready to search",
        },
        "stale": {
            "color": COLORS["warning"],
            "bg": COLORS["warning_bg"],
            "border": COLORS["warning_dark"],
            "icon": "⚠",
            "label": "Parameters changed",
        },
        "loading": {
            "color": COLORS["info"],
            "bg": COLORS["info_bg"],
            "border": COLORS["info_dark"],
            "icon": "⏳",
            "label": "Searching...",
        },
        "executed": {
            "color": COLORS["success"],
            "bg": COLORS["success_bg"],
            "border": COLORS["success_dark"],
            "icon": "✓",
            "label": f"Found {result_count} results" if result_count else "Search complete",
        },
    }

    config = state_config.get(state, state_config["ready"])

    html = f'''
    <div style="
        display: flex;
        align-items: center;
        gap: {SPACING['md']};
        padding: {SPACING['sm']} {SPACING['md']};
        background: {config['bg']};
        border: 1px solid {config['border']};
        border-radius: 6px;
        margin: {SPACING['sm']} 0;
    ">
        <span style="color: {config['color']}; font-size: 1.1em;">{config['icon']}</span>
        <span style="color: {COLORS['text_secondary']}; font-size: {FONT_SIZES['sm']};">
            {summary_text}
        </span>
        <span style="margin-left: auto; color: {config['color']}; font-size: {FONT_SIZES['xs']}; font-weight: 500;">
            {config['label']}
        </span>
    </div>
    '''
    st.markdown(html, unsafe_allow_html=True)


# =============================================================================
# EXPORT QUALITY WARNINGS (Phase 2)
# =============================================================================

def export_quality_warnings(leads: list[dict]) -> None:
    """
    Display quality warnings before export.

    Analyzes leads for potential issues and shows warnings.

    Args:
        leads: List of lead dictionaries to analyze

    Warnings shown:
        - Contacts missing mobile phone
        - Person-only (branch) contacts
        - Below accuracy threshold
    """
    if not leads:
        return

    warnings = []

    # Count contacts missing mobile phone
    missing_mobile = sum(1 for l in leads if not l.get("mobilePhone"))
    if missing_mobile > 0:
        pct = (missing_mobile / len(leads)) * 100
        warnings.append(f"📱 **{missing_mobile}** contacts ({pct:.0f}%) missing mobile phone")

    # Count person-only (branch office) contacts
    person_only = sum(1 for l in leads if l.get("_location_type") == "Person")
    if person_only > 0:
        pct = (person_only / len(leads)) * 100
        warnings.append(f"🏢 **{person_only}** contacts ({pct:.0f}%) are branch office only (Person-only)")

    # Count below accuracy threshold (< 90)
    low_accuracy = sum(1 for l in leads if (l.get("contactAccuracyScore") or 0) < 90)
    if low_accuracy > 0:
        pct = (low_accuracy / len(leads)) * 100
        warnings.append(f"📊 **{low_accuracy}** contacts ({pct:.0f}%) have accuracy below 90")

    if warnings:
        with st.expander("⚠️ Quality Notes", expanded=False):
            for w in warnings:
                st.markdown(w)
            st.caption("These contacts are still included in the export. Review if quality is a concern.")


# =============================================================================
# EMPTY STATE
# =============================================================================

def empty_state(
    message: str,
    icon: str = "",
    hint: Optional[str] = None,
) -> None:
    """
    Render a centered empty state with optional icon and hint.

    Args:
        message: Primary message
        icon: Optional icon/emoji
        hint: Optional secondary guidance text
    """
    icon_html = f'<div style="font-size: 1.5rem; margin-bottom: 0.25rem; opacity: 0.4;">{icon}</div>' if icon else ""
    hint_html = f'<p style="color: {COLORS["text_muted"]}; font-size: {FONT_SIZES["sm"]}; margin-top: 0.25rem;">{hint}</p>' if hint else ""
    st.markdown(
        f'''<div style="text-align: center; padding: {SPACING["xl"]} 0 {SPACING["lg"]};">
            {icon_html}
            <p style="color: {COLORS["text_secondary"]}; margin: 0;">{message}</p>
            {hint_html}
        </div>''',
        unsafe_allow_html=True,
    )


# =============================================================================
# SKELETON LOADING CARD (Phase 4)
# =============================================================================

def skeleton_card(height: int = 100, count: int = 3) -> None:
    """
    Display skeleton loading placeholders.

    Args:
        height: Height of each skeleton card in pixels
        count: Number of skeleton cards to show
    """
    for i in range(count):
        st.markdown(
            f'''
            <div style="
                background: linear-gradient(90deg, {COLORS['bg_secondary']} 0%, {COLORS['bg_tertiary']} 50%, {COLORS['bg_secondary']} 100%);
                background-size: 200% 100%;
                animation: shimmer 1.5s infinite;
                border-radius: 8px;
                height: {height}px;
                margin-bottom: {SPACING['sm']};
            "></div>
            ''',
            unsafe_allow_html=True
        )

    # Shimmer keyframe is defined in inject_base_styles()


# =============================================================================
# REVIEW CONTROLS BAR (Phase 3)
# =============================================================================

def review_controls_bar(
    sort_key: str = "geo_review_sort",
    filter_key: str = "geo_review_filter",
) -> tuple[str, str]:
    """
    Display sort and filter controls for review section.

    Args:
        sort_key: Session state key for sort selection
        filter_key: Session state key for filter selection

    Returns:
        Tuple of (sort_value, filter_value)
    """
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        sort_options = {
            "score": "Best score",
            "company_name": "Company A-Z",
            "contact_count": "Most choices",
        }
        sort_value = st.selectbox(
            "Sort by",
            options=list(sort_options.keys()),
            format_func=lambda x: sort_options[x],
            key=sort_key,
            label_visibility="collapsed",
        )

    with col2:
        filter_options = {
            "all": "All companies",
            "multi_only": "Multiple contacts",
            "has_mobile": "Has mobile phone",
            "high_accuracy": "95+ accuracy",
        }
        filter_value = st.selectbox(
            "Filter",
            options=list(filter_options.keys()),
            format_func=lambda x: filter_options[x],
            key=filter_key,
            label_visibility="collapsed",
        )

    return sort_value, filter_value


# =============================================================================
# SCORE BREAKDOWN (Phase 3)
# =============================================================================

def score_breakdown(contact: dict) -> str:
    """
    Generate a score breakdown explanation for a contact.

    Args:
        contact: Contact dictionary with scoring fields

    Returns:
        HTML string showing score breakdown
    """
    parts = []

    # Accuracy score contribution
    accuracy = contact.get("contactAccuracyScore", 0)
    if accuracy >= 95:
        parts.append(f"<span style='color:{COLORS['success']}'>Accuracy {accuracy} (+20)</span>")
    elif accuracy >= 85:
        parts.append(f"<span style='color:{COLORS['warning']}'>Accuracy {accuracy} (+10)</span>")
    else:
        parts.append(f"<span style='color:{COLORS['text_muted']}'>Accuracy {accuracy}</span>")

    # Mobile phone bonus
    if contact.get("mobilePhone"):
        parts.append(f"<span style='color:{COLORS['success']}'>Mobile ✓ (+15)</span>")
    else:
        parts.append(f"<span style='color:{COLORS['text_muted']}'>No mobile</span>")

    # Management level
    mgmt = contact.get("managementLevel", "")
    if mgmt:
        if mgmt in ("VP", "C-Level"):
            parts.append(f"<span style='color:{COLORS['success']}'>{mgmt}</span>")
        elif mgmt == "Director":
            parts.append(f"<span style='color:{COLORS['warning']}'>{mgmt}</span>")
        else:
            parts.append(f"<span style='color:{COLORS['text_muted']}'>{mgmt}</span>")

    # Location type
    loc_type = contact.get("_location_type", "")
    if loc_type == "PersonAndHQ":
        parts.append(f"<span style='color:{COLORS['success']}'>HQ+Person (+10)</span>")
    elif loc_type == "Person":
        parts.append(f"<span style='color:{COLORS['warning']}'>Branch only (+5)</span>")

    return " · ".join(parts)


# =============================================================================
# COMPANY CARD GROUP (Phase 3)
# =============================================================================

def company_card_header(
    company_name: str,
    contact_count: int,
    best_contact_name: str,
    is_expanded: bool = False,
) -> str:
    """
    Generate HTML for a company card header.

    Args:
        company_name: Name of the company
        contact_count: Number of contacts available
        best_contact_name: Name of the best contact
        is_expanded: Whether the card is expanded

    Returns:
        HTML string for the header
    """
    badge_color = COLORS["success"] if contact_count == 1 else COLORS["info"]
    badge_text = f"{contact_count} contact{'s' if contact_count > 1 else ''}"

    return f'''
    <div style="
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: {SPACING['sm']} {SPACING['md']};
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
        margin-bottom: {SPACING['xs']};
    ">
        <div>
            <span style="font-weight: 600; color: {COLORS['text_primary']};">{company_name}</span>
            <span style="color: {COLORS['text_muted']}; font-size: {FONT_SIZES['sm']}; margin-left: {SPACING['sm']};">
                Best: {best_contact_name}
            </span>
        </div>
        <span style="
            background: {badge_color}20;
            color: {badge_color};
            padding: {SPACING['xs']} {SPACING['sm']};
            border-radius: 9999px;
            font-size: {FONT_SIZES['xs']};
            font-weight: 500;
        ">{badge_text}</span>
    </div>
    '''


# =============================================================================
# WORKFLOW RUN STATE (UX Overhaul)
# =============================================================================

# State to pill color mapping
_STATE_COLORS: dict[str, StatusType] = {
    "idle": "neutral",
    "searched": "info",
    "selecting": "info",
    "contacts_found": "warning",
    "enriched": "success",
    "exported": "success",
}


def workflow_run_state(prefix: str) -> str:
    """
    Derive the current workflow run state from session state.

    Args:
        prefix: Session state prefix - "intent" or "geo"

    Returns:
        One of: "idle", "searched", "selecting", "contacts_found", "enriched", "exported"
    """
    ss = st.session_state

    if ss.get(f"{prefix}_exported"):
        return "exported"
    if ss.get(f"{prefix}_enrichment_done"):
        return "enriched"
    if ss.get(f"{prefix}_contacts_by_company"):
        return "contacts_found"

    # Check for manual mode selecting state
    if prefix == "intent":
        if ss.get("intent_companies") and ss.get("intent_mode") == "manual" and not ss.get("intent_companies_confirmed"):
            return "selecting"
    elif prefix == "geo":
        if ss.get("geo_preview_contacts") and ss.get("geo_mode") == "manual" and not ss.get("geo_selection_confirmed"):
            return "selecting"

    if ss.get(f"{prefix}_search_executed"):
        return "searched"

    # Check for companies/contacts existing (intent has intent_companies, geo has geo_preview_contacts)
    if prefix == "intent" and ss.get("intent_companies"):
        return "searched"
    if prefix == "geo" and ss.get("geo_preview_contacts"):
        return "searched"

    return "idle"


# =============================================================================
# ACTION BAR (UX Overhaul)
# =============================================================================

def action_bar(
    run_state: str,
    primary_label: Optional[str] = None,
    primary_key: Optional[str] = None,
    secondary_label: Optional[str] = None,
    secondary_key: Optional[str] = None,
    metrics: Optional[list[dict]] = None,
) -> tuple[bool, bool]:
    """
    Render a sticky action bar with state pill, metrics, and up to 2 action buttons.

    Args:
        run_state: Current workflow state (from workflow_run_state)
        primary_label: Label for primary action button
        primary_key: Unique key for primary button
        secondary_label: Label for secondary action button
        secondary_key: Unique key for secondary button
        metrics: Optional inline metrics [{label, value}]

    Returns:
        Tuple of (primary_clicked, secondary_clicked)
    """
    pill_color = _STATE_COLORS.get(run_state, "neutral")
    state_display = run_state.replace("_", " ").title()
    pill_html = status_badge(pill_color, state_display)

    # Build inline metrics HTML
    metrics_html = ""
    if metrics:
        for m in metrics:
            metrics_html += (
                f'<div class="metric-inline">'
                f'<span class="label">{m["label"]}</span>'
                f'<span class="value">{m["value"]}</span>'
                f'</div>'
            )

    # Render the bar: left side is HTML (pill + metrics), right side is Streamlit buttons
    if primary_label or secondary_label:
        # Calculate columns: left for pill+metrics, right for buttons
        btn_count = (1 if primary_label else 0) + (1 if secondary_label else 0)
        left_col, *btn_cols = st.columns([3] + [1] * btn_count)
    else:
        left_col = st.columns(1)[0]
        btn_cols = []

    with left_col:
        st.markdown(
            f'<div class="action-bar"><div class="action-bar-left">{pill_html}{metrics_html}</div></div>',
            unsafe_allow_html=True,
        )

    primary_clicked = False
    secondary_clicked = False

    col_idx = 0
    if secondary_label and btn_cols:
        with btn_cols[col_idx]:
            secondary_clicked = bool(ui.button(
                text=secondary_label,
                variant="outline",
                key=secondary_key or f"action_bar_secondary_{run_state}",
            ))
        col_idx += 1

    if primary_label and col_idx < len(btn_cols):
        with btn_cols[col_idx]:
            primary_clicked = st.button(
                primary_label,
                type="primary",
                key=primary_key or f"action_bar_primary_{run_state}",
                use_container_width=True,
            )

    return primary_clicked, secondary_clicked


# =============================================================================
# SUMMARY STRIP (UX Overhaul)
# =============================================================================

def workflow_summary_strip(items: list[dict]) -> None:
    """
    Render a compact horizontal row of key metrics.

    Args:
        items: List of {label: str, value: str|int} dicts (3-6 items)
    """
    if not items:
        return

    parts = []
    for item in items:
        val = item.get("value", "")
        if isinstance(val, int):
            val = f"{val:,}"
        parts.append(
            f'<div class="summary-item">'
            f'<span class="label">{item["label"]}</span>'
            f'<span class="value">{val}</span>'
            f'</div>'
        )

    html = f'<div class="summary-strip">{"".join(parts)}</div>'
    st.markdown(html, unsafe_allow_html=True)


# =============================================================================
# LAST RUN INDICATOR (UX Overhaul)
# =============================================================================

def last_run_indicator(last_query: dict | None) -> None:
    """
    Render a small inline indicator showing last run info.

    Args:
        last_query: Dict from get_last_query() with created_at, leads_returned, workflow_type.
                    None if no previous runs.
    """
    if not last_query:
        return

    from datetime import datetime

    created_at = last_query.get("created_at", "")
    leads = last_query.get("leads_returned", 0)
    workflow = last_query.get("workflow_type", "").title()

    # Compute time delta
    time_display = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            delta = datetime.now() - dt.replace(tzinfo=None)
            if delta.days > 0:
                time_display = f"{delta.days}d ago"
            elif delta.seconds >= 3600:
                time_display = f"{delta.seconds // 3600}h ago"
            elif delta.seconds >= 60:
                time_display = f"{delta.seconds // 60}m ago"
            else:
                time_display = "just now"
        except (ValueError, TypeError):
            time_display = created_at[:10] if len(created_at) >= 10 else created_at

    parts = []
    if time_display:
        parts.append(time_display)
    if leads:
        parts.append(f"{leads} leads")
    if workflow:
        parts.append(workflow)

    if parts:
        st.caption(f"Last run: {' · '.join(parts)}")


# =============================================================================
# EXPORT VALIDATION CHECKLIST (UX Overhaul)
# =============================================================================

def export_validation_checklist(leads: list[dict]) -> list[dict]:
    """
    Run validation checks on leads and render a compact grid.

    Args:
        leads: List of lead dicts to validate

    Returns:
        List of check results: [{check, passed, failed, status}]
    """
    if not leads:
        return []

    total = len(leads)
    checks = []

    # Has phone number
    has_phone = sum(
        1 for l in leads
        if l.get("directPhone") or l.get("phone") or l.get("mobilePhone")
    )
    checks.append({
        "check": "Has phone number",
        "passed": has_phone,
        "failed": total - has_phone,
    })

    # Has email
    has_email = sum(1 for l in leads if l.get("email"))
    checks.append({
        "check": "Has email",
        "passed": has_email,
        "failed": total - has_email,
    })

    # Accuracy >= 85
    high_accuracy = sum(
        1 for l in leads if (l.get("contactAccuracyScore") or 0) >= 85
    )
    checks.append({
        "check": "Accuracy >= 85",
        "passed": high_accuracy,
        "failed": total - high_accuracy,
    })

    # No duplicates (by personId)
    person_ids = [l.get("personId") or l.get("id") for l in leads if l.get("personId") or l.get("id")]
    unique_count = len(set(person_ids))
    duplicate_count = len(person_ids) - unique_count
    checks.append({
        "check": "No duplicates",
        "passed": unique_count,
        "failed": duplicate_count,
    })

    # Assign status based on thresholds
    for check in checks:
        if total > 0:
            pass_rate = check["passed"] / total
        else:
            pass_rate = 1.0

        if pass_rate > 0.9:
            check["status"] = "success"
        elif pass_rate > 0.7:
            check["status"] = "warning"
        else:
            check["status"] = "error"

    # Render grid
    status_colors = {
        "success": COLORS["success"],
        "warning": COLORS["warning"],
        "error": COLORS["error"],
    }

    items_html = ""
    for check in checks:
        color = status_colors.get(check["status"], COLORS["text_muted"])
        items_html += (
            f'<div class="validation-item">'
            f'<div class="validation-dot" style="background:{color};"></div>'
            f'<span>{check["check"]}</span>'
            f'<span style="margin-left:auto;color:{COLORS["text_secondary"]};">'
            f'{check["passed"]}/{check["passed"]+check["failed"]}</span>'
            f'</div>'
        )

    st.markdown(f'<div class="validation-grid">{items_html}</div>', unsafe_allow_html=True)

    return checks


# =============================================================================
# STYLED HTML TABLE
# =============================================================================

def styled_table(
    rows: list[dict],
    columns: list[dict],
) -> None:
    """
    Render a themed HTML table with alternating rows, hover, and optional status pills.

    Args:
        rows: List of row dicts (keys match column 'key')
        columns: List of column defs: [{key, label, align?, mono?, pill?}]
                 pill: dict mapping values to pill classes (e.g. {"Exported": "success", "Not exported": "muted"})
    """
    if not rows:
        return

    # Header
    header_html = "".join(
        f'<th style="text-align:{c.get("align","left")}">{c["label"]}</th>'
        for c in columns
    )

    # Rows
    body_html = ""
    for row in rows:
        cells = ""
        for c in columns:
            val = row.get(c["key"], "")
            td_class = ' class="mono"' if c.get("mono") else ""
            align = f' style="text-align:{c["align"]}"' if c.get("align") else ""

            if c.get("pill") and val in c["pill"]:
                pill_cls = c["pill"][val]
                cell_content = f'<span class="status-pill status-pill-{pill_cls}">{val}</span>'
            else:
                cell_content = str(val)

            cells += f"<td{td_class}{align}>{cell_content}</td>"
        body_html += f"<tr>{cells}</tr>"

    html = f'<table class="styled-table"><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>'
    st.markdown(html, unsafe_allow_html=True)
