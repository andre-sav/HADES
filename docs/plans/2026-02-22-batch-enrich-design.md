# Batch Enrich + exclude_org_exported Fix

**Date:** 2026-02-22
**Bead:** HADES-ect (P1)
**Depends on:** HADES-dd6 (closed)

## Problem

Two P1 audit findings:

1. **N+1 enrich calls in Step 3** — `run_intent_pipeline.py:194-205` loops over uncached companies calling `enrich_contacts_batch(person_ids=[single_pid])` one at a time. 25 individual API calls where 1 batch call suffices. Wastes ~24 credits per automated run on a 500/week budget.

2. **`exclude_org_exported` is a no-op** — field exists in `ContactQueryParams` dataclass and cache hash but `search_contacts()` never sends it to the ZoomInfo API. Users believe org-exported contacts are filtered; they are not.

## Design

### Fix 1: Batch Step 3 ID Resolution

Replace the per-company enrich loop with a single batch call:

1. Collect all uncached `(hashed_id, person_id)` pairs
2. Call `enrich_contacts_batch(person_ids=all_pids, output_fields=["id", "companyId", "companyName"])` once
3. Map enriched results back to hashed IDs using a PID→hashed_id lookup
4. Save resolved company IDs to cache

### Fix 2: Send exclude_org_exported to API

Add `excludeOrgExportedContacts` to the request body in `search_contacts()` when `params.exclude_org_exported` is True. Update tests to expect the field.

## Files Changed

| File | Change |
|---|---|
| `scripts/run_intent_pipeline.py` | Replace N+1 enrich loop with single batch call |
| `zoominfo_client.py` | Send `excludeOrgExportedContacts` in request body |
| `tests/test_zoominfo_client.py` | Update exclude_org_exported tests |
| `tests/test_run_intent_pipeline.py` | Update Step 3 expectations |
