# Dry-Run Option for Automation Run Now

**Date:** 2026-02-24
**Bead:** HADES-epj (P1)
**Status:** Approved

## Problem

The "Run Now" button on the Automation page fires the full intent pipeline immediately — consuming credits, hitting APIs, and emailing CSVs. There's no way to preview what would happen before committing.

## Solution

Add a "Dry Run" button that executes the intent pipeline through scoring/dedup (Steps 1-2) and stops before the expensive operations (Steps 3-5: company ID resolution, contact search, enrichment, export, email). Intent Search is free (no credits consumed), so this gives real numbers at zero cost.

## Approach

Refactor the existing `dry_run` early-exit in `run_pipeline()` (currently a stub that returns zeroes) to run Steps 1-2 with real data before returning.

## Backend Changes

**File:** `scripts/run_intent_pipeline.py`

Move the `dry_run` exit point from before Step 1 to after Step 2:

1. Init ZoomInfo client (needs creds for auth)
2. Step 1 — Intent Search (free, no credits)
3. Step 2 — Score, dedup, select top N
4. Populate `top_companies` in summary (name, score, topic, signal strength)
5. Return summary with real numbers
6. Skip Steps 3-5

The dry-run path skips:
- Budget check (no credits consumed)
- Concurrent-run guard (stateless, read-only)
- `start_pipeline_run` / `complete_pipeline_run` (no DB logging)

## Frontend Changes

**File:** `pages/10_Automation.py`

**Run Now section** gets two buttons side-by-side:
- "Dry Run" (secondary) — runs preview, renders results inline below
- "Run Now" (primary) — existing behavior with confirmation dialog

**Dry-run results** (rendered inline when `session_state["dry_run_result"]` exists):
- Metric row: intent results | scored (non-stale) | after dedup | would select
- Estimated credits line (= companies_selected, each gets ~1 enrich call)
- Top 5 companies table: company name, score, topic, signal strength
- "Run Full Pipeline" button — shortcut to confirmation dialog
- "Dismiss" link to clear results

Results live in `st.session_state` only — ephemeral, no DB persistence.

## Error Handling

If dry run fails (API timeout, auth error), show `st.error()` with friendly message. No retry, no fallback. User clicks Dry Run again.

## Testing

- `run_pipeline(dry_run=True)` returns summary with real intent/scored/dedup counts
- `dry_run=True` does NOT call `search_contacts`, `enrich_contacts_batch`, `export_leads_to_csv`, or `start_pipeline_run`
- `top_companies` list populated with name, score, topic, strength

## Unblocks

HADES-dgr (show budget remaining in Run Now dialog) — can piggyback on the dry-run summary to show estimated credit cost vs. remaining budget.
