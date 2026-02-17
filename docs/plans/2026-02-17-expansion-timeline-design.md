# Expansion Timeline Component Design

**Date:** 2026-02-17
**Bead:** HADES-5xm
**Story:** 2.3 — Target Contacts with Auto-Expansion

## Problem

The Geography Workflow's auto-expansion currently shows a single-line summary: "Expansions applied: Management → ..., Accuracy → 85". Story 2.3 AC requires per-step detail: parameter changed, old → new value, contacts found per step, and why expansion was needed.

## Design

### 1. Structured Step Data

Add `expansion_steps` list to `expand_search()` result dict. Each step records:

```python
{
    "param": "management_levels",
    "old_value": "Manager/Director",
    "new_value": "Manager/Director/VP/C-Level",
    "contacts_found": 14,
    "new_companies": 5,
    "cumulative_companies": 18,
    "target": 25,
}
```

Built inside the expansion loop alongside the existing `expansion_log`.

### 2. `expansion_timeline()` Component

Renders inside `st.expander("Expansion details", expanded=True)`. Each step is an HTML row:

```
→ Step 1: Management  Manager/Director → +VP/C-Level    +5 companies (18 total)
→ Step 2: Employees   50-5,000 → 50+ (no cap)           +3 companies (21 total)
→ Step 3: Accuracy    95 → 85                            +4 companies (25 total)
  ✓ Target met — 25 companies found. 5 steps skipped.
```

Uses left-border accent, monospace values, muted captions — consistent with `narrative_metric()`.

### 3. Integration

Replaces the `st.caption()` summary in `pages/2_Geography_Workflow.py` with the timeline in an expander. Auto-expanded when expansions occurred, collapsed when none needed.

## Files Changed

| File | Change |
|---|---|
| `expand_search.py` | Add `expansion_steps` list to result, populated per step |
| `ui_components.py` | Add `expansion_timeline()` component |
| `pages/2_Geography_Workflow.py` | Replace caption summary with `expansion_timeline()` in expander |
| `tests/test_expand_search.py` | Verify `expansion_steps` in result |
| `tests/test_ui_components.py` | Test `expansion_timeline()` HTML output |

## What Stays the Same

- `expansion_log` — unchanged, used for real-time progress during search
- All search logic — no behavior change
- Summary badge — still shows "Target met" / "X of Y" above the expander
