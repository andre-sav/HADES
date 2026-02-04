# Target Contacts with Auto-Expansion

**Date:** 2026-02-03
**Status:** Approved

## Overview

Allow users to specify a target number of contacts they need from ZoomInfo. If the initial search doesn't meet the target, the system automatically expands search parameters following a unified expansion strategy until the target is met or all expansion options are exhausted.

## User Interface

### Target Input

Add to Geography Workflow "Search Parameters" section, after Industry Filters:

- **Target contacts**: Number input (default: 25, min: 5, max: 100)
- **Stop early if target met**: Checkbox toggle
  - Default ON for Autopilot mode
  - Default OFF for Manual Review mode
- Help text: "System will auto-expand search if target not met"
- Caption showing starting parameters: "Starting: 10mi radius, 95 accuracy, Manager level, 50-5,000 employees"

### Results Summary

Replace simple "Found X contacts across Y companies" with expansion summary:

**Target met:**
```
✅ Target met: 52 contacts found (target: 50)
   Expansions applied: Radius → 15mi, Management → +Director
   Searches performed: 4
```

**Target not met:**
```
⚠️ Found 38 of 50 target contacts
   All expansions exhausted (9 steps applied)
   Final parameters: 20mi radius, 75 accuracy, Director/VP/C-Level, 50+ employees
```

**No expansion needed:**
```
✅ Target met: 67 contacts found (target: 50)
   No expansions needed
```

## Unified Expansion Strategy

Single expansion path, applied in order:

| Step | Change | Value |
|------|--------|-------|
| 1 | Radius | → 12.5mi |
| 2 | Radius | → 15mi |
| 3 | Management | → +Director |
| 4 | Management | → +VP/C-Level |
| 5 | Employee range | → 50-unlimited |
| 6 | Accuracy | → 85 |
| 7 | Accuracy | → 75 |
| 8 | Radius | → 17.5mi |
| 9 | Radius | → 20mi |

**Rationale:**
- Moderate geographic expansion first (15mi)
- Then broaden job levels and company sizes
- Accuracy preserved as long as possible
- Final geographic expansion only if filters exhausted

### Starting Parameters

| Parameter | Start Value |
|-----------|-------------|
| Radius | 10mi |
| Accuracy | 95 |
| Management | Manager |
| Employee range | 50-5,000 |
| Location type | PersonAndHQ (fixed, never changes) |

### Limits

| Parameter | Floor/Ceiling |
|-----------|---------------|
| Radius | 20mi max |
| Accuracy | 75 min |
| Management | Manager/Director/VP/C-Level |
| Employee range | 50 min, no max |

## Execution Flow

1. **Initial search** with starting parameters
2. **Check result count** against target
3. **If target met**: Stop (if "stop early" enabled) or continue to gather more
4. **If below target**:
   - Apply next expansion step
   - Search again with new parameters
   - Accumulate unique contacts (dedupe by `personId`)
   - Repeat until target met or all 9 steps exhausted

**Deduplication:** Each expansion may return overlapping contacts. Dedupe by `personId` to avoid counting the same contact twice.

**Rate limiting:** 500ms delay between expansion searches to avoid ZoomInfo rate limits.

**Max API calls:** 10 (initial + 9 expansion steps). Typical: 2-4 searches.

## Data Structures

### Expansion Steps Definition

```python
EXPANSION_STEPS = [
    {"radius": 12.5},
    {"radius": 15.0},
    {"management_levels": ["Manager", "Director"]},
    {"management_levels": ["Manager", "Director", "VP", "C-Level"]},
    {"employee_max": None},  # Remove cap
    {"accuracy_min": 85},
    {"accuracy_min": 75},
    {"radius": 17.5},
    {"radius": 20.0},
]
```

### Session State

```python
st.session_state.geo_expansion_result = {
    "target": 50,
    "found": 52,
    "target_met": True,
    "steps_applied": 3,
    "final_params": {
        "radius": 15.0,
        "accuracy_min": 95,
        "management_levels": ["Manager", "Director"],
        "employee_max": 5000,
    },
    "searches_performed": 4,
    "contacts": [...],  # Deduplicated contact list
}
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| API error mid-expansion | Stop, return contacts found so far, show warning |
| Zero results after all expansions | Show "No contacts found" message |
| Target exceeds available | Show shortfall in summary, user proceeds with available |
| Exact target hit | Stop at that step if "stop early" enabled |

## Integration with Existing Modes

### Manual Review
- Expansion runs during search phase
- User sees full expanded results in contact selection
- User picks 1 contact per company before enrichment

### Autopilot
- Expansion runs the same way
- Auto-selects best contact per company
- Proceeds directly to enrichment

### Test Mode
- Expansion logic runs (to test the flow)
- Searches return mock data, no API calls
- Summary shows simulated expansion steps

## Implementation

### Files to Modify

| File | Changes |
|------|---------|
| `pages/2_Geography_Workflow.py` | Add target input, expansion loop, results summary |

### New Components

- `EXPANSION_STEPS` constant
- `expand_search()` function
- Updated UI for target input and results summary

### Testing

- Unit tests for `expand_search()` with mocked API responses
- Test cases: target met early, target met after expansion, target never met, API error mid-expansion
- Manual test using Test Mode (no credits)

### Estimated Scope

~150-200 lines of new/modified code
