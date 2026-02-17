# HADES Design System

Extracted from `ui_components.py`. Dark-mode-only Streamlit dashboard for a vending services sales team.

## Direction

Dark, data-dense, professional. Indigo/Cyan gradient accents on a near-black base. Urbanist typeface for warmth, IBM Plex Mono for data. Borders-first depth with subtle shadows. No light mode.

## Color Tokens

### Brand

| Token | Value | Usage |
|-------|-------|-------|
| `primary` | `#6366f1` Indigo-500 | Buttons, active states, focus rings |
| `primary_light` | `#818cf8` Indigo-400 | Hover text, highlights |
| `primary_dark` | `#4f46e5` Indigo-600 | Pressed states |
| `accent` | `#06b6d4` Cyan-500 | Gradient endpoint |
| `accent_light` | `#22d3ee` Cyan-400 | |
| `accent_dark` | `#0891b2` Cyan-600 | |

### Semantic

Each semantic color has 4 variants: base, light (400), dark (600), bg (950).

| Semantic | Base | Light | Dark | Background |
|----------|------|-------|------|------------|
| Success | `#22c55e` | `#4ade80` | `#16a34a` | `#14532d` |
| Warning | `#f59e0b` | `#fbbf24` | `#d97706` | `#451a03` |
| Error | `#ef4444` | `#f87171` | `#dc2626` | `#450a0a` |
| Info | `#3b82f6` | `#60a5fa` | `#2563eb` | `#172554` |

### Neutrals

| Token | Value | Usage |
|-------|-------|-------|
| `bg_primary` | `#0a0e14` | Main background |
| `bg_secondary` | `#141922` | Cards, sidebar |
| `bg_tertiary` | `#1e2530` | Elevated surfaces, table headers |
| `border` | `#262d3a` | Default borders |
| `border_light` | `#3a4350` | Hover borders |
| `text_primary` | `#f0f2f5` | Body text |
| `text_secondary` | `#8b929e` | Labels, captions |
| `text_muted` | `#5c6370` | Disabled, hints |

### Gradients

- **Accent gradient**: `linear-gradient(135deg, primary, accent)` -- Primary buttons, active step indicators
- **Accent gradient horizontal**: `linear-gradient(90deg, primary, accent)` -- Progress bars, step connectors
- **Background vignette**: Subtle radial gradients of primary (6% opacity) and accent (4% opacity)

## Typography

| Role | Family | Weight | Size | Tracking |
|------|--------|--------|------|----------|
| Display (h1) | Urbanist | 800 | 30px (3xl) | -0.025em |
| Heading (h2) | Urbanist | 700 | -- | -0.025em |
| Subheading (h3) | Urbanist | 600 | -- | -0.025em |
| Body | Urbanist | 400-500 | 16px (base) | -- |
| Label | Urbanist | 500 | 12px (xs) | 0.04em, uppercase |
| Data value | IBM Plex Mono | 700 | 24px (2xl) | tabular-nums |
| Small data | IBM Plex Mono | 500 | 14px (sm) | tabular-nums |

**Font scale**: 12, 14, 16, 18, 20, 24, 30 (px)

## Spacing

Base unit: 4px. Scale: `xs(4) sm(8) md(16) lg(24) xl(32) 2xl(48)`.

## Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius` | 10px | Cards, expanders, tables |
| `--radius-sm` | 6px | -- |
| Buttons/Inputs | 8px | All interactive elements |
| Badges/Pills | 9999px | Full pill shape |

## Depth

Borders-first strategy. Shadows used as enhancement, not primary depth cue.

| Level | Shadow | Border |
|-------|--------|--------|
| Flat | none | 1px solid `border` |
| Card (resting) | `0 1px 3px rgba(0,0,0,0.24), 0 1px 2px rgba(0,0,0,0.16)` | 1px solid `border` |
| Card (hover) | `0 4px 14px rgba(0,0,0,0.32), 0 2px 4px rgba(0,0,0,0.2)` | 1px solid `border_light` |
| Primary button (hover) | `0 4px 16px primary40` | none |
| Focus ring | `0 0 0 2px primary20` | -- |

## Transitions

- Default: `0.2s ease` (all interactive elements)
- Page load: `fadeInUp 0.3s ease-out`
- Shimmer: `background-position 200% → -200%` (skeleton loading)

## Component Patterns

### Metric Card

```
bg_secondary | 1px border | 10px radius | 1rem padding | card-shadow
Label: 12px uppercase muted, 0.05em tracking, 0 0 4px 0 margin
Value: 1.5rem mono 700wt text_primary
Delta: 14px mono 500wt, margin-left 8px, colored by sign
Hover: elevated shadow + border_light
```

### Status Badge

```
Pill: 9999px radius | 4px 8px padding | 14px body 500wt | 24px min-height
Variants: success/warning/error/info/neutral
Pattern: semantic_bg background + semantic_light text + semantic_dark border
```

### Step Indicator

```
Row: flex, 8px gap
Circle: 26px, mono 12px 600wt
States: active (gradient + glow), completed (green), pending (border + muted)
Connector: 2px height, 20-60px width, gradient when completed
```

### Styled Table

```
Separate borders | 10px radius | overflow hidden | 1px border
Header: bg_tertiary, 12px uppercase 600wt text_secondary, 10px 14px padding
Row (even): bg_secondary 80% opacity
Row (hover): bg_tertiary
Cell: 10px 14px padding, 1px bottom border at 60% opacity
Data cells: .mono class for IBM Plex Mono + tabular-nums
```

### Card Variants

| Variant | Distinctive Feature |
|---------|-------------------|
| Metric card | Label/value typography, delta indicator |
| Company group | 16px padding, .best-pick left border accent |
| Contact card | Selected state: primary border + glow ring |
| Quick action | Centered text, hover translateY(-1px) |

### Progress Bar

```
Container: bg_tertiary, 4px radius, 8px height
Fill: gradient background, 4px radius, 0.4s width transition
Variants: success (accent-gradient), warning, error, info
```

## Layout Presets

| Preset | Columns | Usage |
|--------|---------|-------|
| `header` | [3, 1] | Page title + action button |
| `filters` | [1, 1, 1, 1] | Filter row |
| `form_2col` | [1, 1] | Two-column forms |
| `action_row` | [1, 1, 2] | Buttons + spacer |
| `metric_4col` | [1, 1, 1, 1] | Four metrics |
| `metric_3col` | [1, 1, 1] | Three metrics |
| `content_sidebar` | [3, 1] | Main + side panel |

## Page Structure

Every page follows this skeleton:

```python
"""Page Name - One-line description."""
import streamlit as st
from turso_db import get_database
from ui_components import inject_base_styles, page_header, metric_card, ...

st.set_page_config(page_title="Name", page_icon="...", layout="wide")
inject_base_styles()

try:
    db = get_database()
except Exception as e:
    st.error(f"Failed to connect: {e}")
    st.stop()

page_header("Title", "Caption")

# Metrics row
col1, col2, col3 = st.columns(3)
with col1:
    metric_card("Label", value)

# Content sections
labeled_divider("Section Name")

# Empty states
if not data:
    empty_state("No data yet", hint="...")
```

## Widget Overrides

The CSS in `inject_base_styles()` overrides native Streamlit widgets:

- **Primary buttons**: Accent gradient, no border, 600wt, 8px radius, glow on hover
- **Secondary buttons**: 1px border, 500wt, hover turns primary-colored
- **Inputs**: 8px radius, border → primary on focus with 2px glow ring
- **Labels**: 12px uppercase 500wt muted, 0.04em tracking
- **Expanders**: 1px border, 10px radius, bg_secondary, hover brightens border
- **Sidebar**: bg_secondary, active page gets primary15 bg + 2px left accent
- **Scrollbar**: 6px thin, border-colored thumb
- **Dividers**: Gradient fade (transparent → border → transparent)

## Rules

1. **Always call `inject_base_styles()` first** on every page
2. **Use `st.button` not `ui.button`** for critical actions (shadcn-ui clicks are unreliable in nested blocks)
3. **Use design system components** (`metric_card`, `status_badge`, `labeled_divider`) -- never hardcode colors
4. **Session state keys prefixed by page**: `intent_*`, `geo_*`, `auto_*`
5. **Rerun guard pattern** for DB writes: set flag before write, check flag to prevent duplicates
6. **Data values in mono**: Use IBM Plex Mono for numbers, IDs, scores
7. **Labels are uppercase**: 12px, 500wt, muted, 0.04em tracking
8. **No light mode**: All decisions assume dark backgrounds
