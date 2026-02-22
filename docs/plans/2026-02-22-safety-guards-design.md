# Safety Guards for Irreversible Actions

**Date:** 2026-02-22
**Bead:** HADES-dd6 (P0)
**Blocks:** HADES-ect, HADES-io6

## Problem

Four P0/P1 audit findings where the app lacks protection against accidental or duplicate irreversible actions:

1. Single-click VanillaSoft Push creates real CRM records with no confirmation
2. Single-click Run Now burns credits and sends email with no confirmation
3. Cron + manual Run Now can overlap, causing double credit spend and duplicate CRM leads
4. `lead_outcomes` table has no UNIQUE constraint — duplicate rows inflate calibration stats
5. `auto_run_triggered` flag not reset in `finally` block — button stays disabled after errors

## Design

### 1. Confirmation Dialog — VanillaSoft Push

**File:** `pages/4_CSV_Export.py`

Use `@st.dialog` pattern (already established in Geography workflow). Push button opens dialog showing lead count and operator. User must click "Push" inside dialog to proceed.

- Dialog sets `st.session_state.vs_push_confirmed = True` and reruns
- Main page checks flag, executes push, then clears flag
- Dialog shows: lead count, operator name, irreversibility warning

### 2. Confirmation Dialog — Run Now

**File:** `pages/9_Automation.py`

Same `@st.dialog` pattern. Run Now button opens dialog showing pipeline config (topics, target companies) and credit warning.

- Dialog sets `st.session_state.auto_run_confirmed = True` and reruns
- Main page checks flag, executes pipeline, then clears flag

### 3. Concurrent-Run Guard

**File:** `scripts/run_intent_pipeline.py`

At `run_pipeline()` start, query `pipeline_runs` for any row with `status='running'`. If found, return early with error. No file locks needed — Turso is the single source of truth.

### 4. UNIQUE Constraint on lead_outcomes

**File:** `turso_db.py`

Add migration: `CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_outcomes_unique ON lead_outcomes(batch_id, person_id)`.

Change `record_lead_outcomes_batch` INSERT to `INSERT OR IGNORE` so duplicates are silently skipped.

### 5. auto_run_triggered Finally Fix

**File:** `pages/9_Automation.py`

Wrap the Run Now execution block in `try/finally` so the flag always resets.

## Files Changed

| File | Change |
|------|--------|
| `pages/4_CSV_Export.py` | Add `@st.dialog` confirmation for Push |
| `pages/9_Automation.py` | Add `@st.dialog` confirmation for Run Now + `try/finally` fix |
| `scripts/run_intent_pipeline.py` | Add concurrent-run guard at pipeline start |
| `turso_db.py` | Add UNIQUE index migration + change INSERT to INSERT OR IGNORE |

## Testing

- Existing 578 tests must still pass
- Add tests for: concurrent-run guard, UNIQUE constraint (INSERT OR IGNORE behavior)
- Manual verification: dialogs appear on Push and Run Now clicks
