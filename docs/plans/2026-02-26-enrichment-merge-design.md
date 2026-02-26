# Enrichment Merge Redesign

**Date:** 2026-02-26
**Status:** Approved
**Problem:** Address, SIC, industry, and employee count fields silently dropped during enrichment — same root cause hit 3 times across sessions 42-43.

## Root Cause

Contact fields are defined in 7 separate locations. The pre-enrichment snapshot/restore pattern is copy-pasted across 3 code paths (Intent page, Geography page, headless pipeline) with hardcoded field lists. Adding a new field requires updating all locations — omitting any one produces silent data loss.

## Design: `merge_contact()` Function

### Location

`export.py` — consolidates merge concern alongside existing export logic.

### Behavior

```python
def merge_contact(search_contact: dict, enriched_contact: dict) -> dict:
```

1. Start with a copy of `search_contact` (all fields preserved as baseline)
2. Flatten any nested `company` object from `enriched_contact` (`company.street` → `companyStreet`, etc.)
3. Overwrite with non-empty enriched values (enrich wins when it has data)
4. Normalize `id`/`personId` (enrich returns `id`, search returns `personId`)

**Key invariant:** No hardcoded field list. Every field from both sources survives automatically.

### Caller Changes

All three code paths replace snapshot+restore with:

```python
# Before enrichment — build lookup from search-phase contacts
search_by_pid = {str(c.get("personId") or c.get("id")): c for c in selected_contacts}

# After enrichment — merge each contact
for i, contact in enumerate(enriched_contacts):
    pid = str(contact.get("id") or contact.get("personId") or "")
    search_data = search_by_pid.get(pid, {})
    enriched_contacts[i] = merge_contact(search_data, contact)
```

**Deleted code:** `pre_enrichment` dict construction, snapshot loop, restore loop, `companyName` nested fallback — in all 3 code paths (~120 lines total).

**Preserved:** Geography-specific `distance` calculation and `_location_type` injection (workflow-specific, not merge).

### Safety Net

The nested `company` handler in `build_vanillasoft_row()` stays as a final fallback for un-merged contacts.

## Testing

1. Enrich value wins when both have data
2. Search value fills gap when enrich is empty/None
3. Nested `company` object flattened correctly
4. Flat enrich fields beat flattened nested company fields
5. `id`/`personId` normalization
6. `_` prefixed computed fields survive merge
7. Empty strings/None in enrich don't overwrite real search data
8. **End-to-end:** mock contact with all `ZOOMINFO_TO_VANILLASOFT` fields → `merge_contact` with sparse enrich → `build_vanillasoft_row` → assert no mapped column is blank

## Files Modified

- `export.py` — add `merge_contact()` function
- `pages/1_Intent_Workflow.py` — replace snapshot/restore with merge call
- `pages/2_Geography_Workflow.py` — replace snapshot/restore with merge call
- `scripts/run_intent_pipeline.py` — replace snapshot/restore with merge call
- `tests/test_export.py` — add merge_contact tests + end-to-end field preservation test

## What This Prevents

Any new ZoomInfo field (requested via `DEFAULT_ENRICH_OUTPUT_FIELDS` or returned by Contact Search) automatically flows through the pipeline to CSV export without touching merge code. The class of bugs that hit SIC, industry, employee count, and addresses becomes structurally impossible.
