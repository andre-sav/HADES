# Score Transparency & Actionable Prioritization

**Date:** 2026-02-19
**Status:** Approved

## Problem

Leads show a composite score (e.g., 78%) and a priority label (High/Medium/Low), but users can't see *why* a lead scored that way. This makes it hard to trust the ranking and decide which leads to call first.

## Solution

Add an expandable score breakdown per lead showing component scores as horizontal bars, a plain-English summary sentence, and upgraded priority labels with action phrases.

## Score Data (Already Exists)

The scoring engine computes component scores that are currently discarded after computing the composite. No new scoring logic needed.

**Intent components:** signal_score, onsite_score, freshness_score, audience_bonus, employee_bonus
**Geography components:** proximity_score, onsite_score, authority_score, employee_score

## Score Breakdown Component

New `score_breakdown()` in `ui_components.py` renders inside a Streamlit expander per lead.

**Visual:** Horizontal bars for each scoring factor, color-coded by strength:
- Green (70-100): strong contributor
- Yellow (40-69): moderate
- Gray (0-39): weak/neutral

**Layout (Geography example):**
```
Score: 78%  Priority: Call first — strong match
├── Proximity     ████████████░░  85  "3.2 mi away"
├── Industry      █████░░░░░░░░░  40  "Hotels (7011) — 6.8% delivery rate"
├── Authority     █████████░░░░░  75  "Director + facilities keyword"
└── Company Size  ████████░░░░░░  60  "250 employees"
```

**Plain-English summary line** generated from component score tiers:
- "Nearby facilities director at a mid-size hotel — moderate industry fit"
- Template-based, keyed to each component's strength tier (strong/moderate/weak)

**Priority label upgrade:**
- High (80+): "Call first — strong match"
- Medium (60-79): "Good prospect — review details"
- Low (<60): "Lower fit — call if capacity allows"

## Integration Points

1. **Geography Workflow** — results table gets expander row per lead with breakdown
2. **Intent Workflow** — same pattern, intent-specific scoring factors
3. **CSV Export page** — breakdown available when reviewing leads before export

## Data Flow Change

- `score_geography_leads()` / `score_intent_leads()` store component scores as `_score_components` dict on each lead
- `get_priority_label()` returns actionable phrase alongside label
- `score_breakdown()` component reads `_score_components` and renders

## What Doesn't Change

- Scoring math — identical, no recalculation
- CSV export format — breakdown is UI-only
- VanillaSoft push — unaffected
- Existing tests — unchanged

## Testing

- Summary sentence generator: ~5 tests (template variations)
- Component rendering: ~5 tests (HTML output assertions)
- Data flow: ~3 tests (component scores carried on lead dicts)

## Files to Modify

```
scoring.py                        - Carry component scores as _score_components
ui_components.py                  - score_breakdown() component + summary generator
pages/1_Intent_Workflow.py        - Add score expanders to results
pages/2_Geography_Workflow.py     - Add score expanders to results
pages/4_CSV_Export.py             - Add score expanders to review section
tests/test_ui_components.py       - Rendering tests
tests/test_scoring.py             - Component carry-through tests
```
