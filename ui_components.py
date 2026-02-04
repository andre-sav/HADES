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
from typing import Callable, Optional, Literal

# =============================================================================
# COLOR PALETTE
# =============================================================================

COLORS = {
    # Primary brand colors
    "primary": "#6366f1",       # Indigo-500
    "primary_light": "#818cf8", # Indigo-400
    "primary_dark": "#4f46e5",  # Indigo-600

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
    "bg_primary": "#0e1117",    # Main background
    "bg_secondary": "#1a1f2e",  # Card background
    "bg_tertiary": "#262c3d",   # Elevated surfaces
    "border": "#333846",        # Borders
    "border_light": "#444c5e",  # Hover borders
    "text_primary": "#fafafa",  # Primary text
    "text_secondary": "#a1a1aa",# Secondary text
    "text_muted": "#71717a",    # Muted text
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
    Replaces duplicated CSS across pages with consistent styling.
    """
    st.markdown(f"""
<style>
    /* Base container */
    .block-container {{
        padding-top: 3rem;
        max-width: 1200px;
    }}

    /* Metrics styling */
    div[data-testid="stMetric"] {{
        background: transparent;
    }}

    /* Status badges - WCAG AA compliant colors */
    .status-badge {{
        display: inline-flex;
        align-items: center;
        gap: {SPACING['xs']};
        padding: {SPACING['xs']} {SPACING['sm']};
        border-radius: 9999px;
        font-size: {FONT_SIZES['sm']};
        font-weight: 500;
        line-height: 1;
        /* Accessibility: minimum touch target */
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

    /* Step indicator */
    .step-indicator {{
        display: flex;
        align-items: center;
        gap: {SPACING['sm']};
        margin: {SPACING['md']} 0;
    }}

    .step {{
        display: flex;
        align-items: center;
        gap: {SPACING['xs']};
    }}

    .step-number {{
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: {FONT_SIZES['sm']};
        font-weight: 600;
    }}

    .step-number-active {{
        background-color: {COLORS['primary']};
        color: white;
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
        font-size: {FONT_SIZES['sm']};
    }}

    .step-label-active {{
        color: {COLORS['text_primary']};
        font-weight: 500;
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
    }}

    .step-connector-completed {{
        background-color: {COLORS['success']};
    }}

    /* Metric card */
    .metric-card {{
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
        padding: {SPACING['md']};
    }}

    .metric-card-value {{
        font-size: {FONT_SIZES['2xl']};
        font-weight: 600;
        color: {COLORS['text_primary']};
        margin: 0;
    }}

    .metric-card-label {{
        font-size: {FONT_SIZES['sm']};
        color: {COLORS['text_secondary']};
        margin: 0;
    }}

    .metric-card-delta {{
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

    /* Company group cards (Geography Workflow) */
    .company-group {{
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
        padding: {SPACING['md']};
        margin-bottom: {SPACING['md']};
        background: {COLORS['bg_secondary']};
    }}

    .best-pick {{
        background: {COLORS['success_bg']};
        border-left: 3px solid {COLORS['success']};
        padding-left: {SPACING['sm']};
    }}

    /* Prevent truncation in multiselect pills */
    div[data-baseweb="tag"] > span {{
        max-width: none !important;
    }}
    div[data-baseweb="tag"] {{
        max-width: none !important;
    }}

    /* Page header styling */
    .page-header {{
        margin-bottom: {SPACING['lg']};
    }}

    .page-header h1 {{
        margin-bottom: {SPACING['xs']};
    }}

    /* Progress indicator styling */
    .progress-bar-container {{
        background: {COLORS['bg_tertiary']};
        border-radius: 4px;
        height: 8px;
        overflow: hidden;
    }}

    .progress-bar-fill {{
        height: 100%;
        border-radius: 4px;
        transition: width 0.3s ease;
    }}

    .progress-bar-success {{
        background: linear-gradient(90deg, {COLORS['success_dark']}, {COLORS['success']});
    }}

    .progress-bar-warning {{
        background: linear-gradient(90deg, {COLORS['warning_dark']}, {COLORS['warning']});
    }}

    .progress-bar-error {{
        background: linear-gradient(90deg, {COLORS['error_dark']}, {COLORS['error']});
    }}

    .progress-bar-info {{
        background: linear-gradient(90deg, {COLORS['primary_dark']}, {COLORS['primary']});
    }}

    /* Contact card (for pagination) */
    .contact-card {{
        background: {COLORS['bg_secondary']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
        padding: {SPACING['md']};
        margin-bottom: {SPACING['sm']};
        transition: border-color 0.2s;
    }}

    .contact-card:hover {{
        border-color: {COLORS['border_light']};
    }}

    .contact-card-selected {{
        border-color: {COLORS['primary']};
        background: {COLORS['bg_tertiary']};
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
        font-size: {FONT_SIZES['sm']};
        color: {COLORS['text_muted']};
    }}

    /* Pagination controls */
    .pagination {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: {SPACING['md']};
        margin: {SPACING['lg']} 0;
    }}

    .pagination-info {{
        font-size: {FONT_SIZES['sm']};
        color: {COLORS['text_secondary']};
    }}

    /* Accessibility: Focus indicators */
    button:focus-visible,
    a:focus-visible,
    input:focus-visible,
    select:focus-visible,
    textarea:focus-visible {{
        outline: 2px solid {COLORS['primary']};
        outline-offset: 2px;
    }}

    /* Accessibility: Reduced motion preference */
    @media (prefers-reduced-motion: reduce) {{
        *,
        *::before,
        *::after {{
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
        }}
    }}

    /* Accessibility: High contrast mode adjustments */
    @media (prefers-contrast: high) {{
        .status-badge {{
            border-width: 2px;
        }}
        .contact-card,
        .metric-card {{
            border-width: 2px;
        }}
    }}

    /* Screen reader only text */
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
) -> None:
    """
    Render a consistent page header with optional action button.

    Args:
        title: The page title
        caption: Optional subtitle/description
        action_label: Optional button label (e.g., "Refresh")
        action_callback: Function to call when button clicked
        action_icon: Optional icon for the button
    """
    col1, col2 = st.columns(LAYOUT["header"])

    with col1:
        st.title(title)
        if caption:
            st.caption(caption)

    with col2:
        if action_label and action_callback:
            if st.button(
                action_label if not action_icon else f"{action_icon} {action_label}",
                use_container_width=True
            ):
                action_callback()

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
    height: int = 8,
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
    Render a horizontal divider with a centered label.

    Args:
        label: Text to display in the divider
    """
    st.markdown(
        f'''
        <div style="display: flex; align-items: center; margin: {SPACING['lg']} 0;">
            <div style="flex: 1; height: 1px; background: {COLORS['border']};"></div>
            <span style="padding: 0 {SPACING['md']}; color: {COLORS['text_muted']}; font-size: {FONT_SIZES['sm']};">{label}</span>
            <div style="flex: 1; height: 1px; background: {COLORS['border']};"></div>
        </div>
        ''',
        unsafe_allow_html=True
    )
