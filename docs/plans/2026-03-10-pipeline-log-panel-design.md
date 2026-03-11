# Pipeline Log Panel Design

**Date:** 2026-03-10
**Status:** Approved
**Bead:** HADES-bdr

## Problem

Pipeline runs complete silently. Mike (sales user) has no visibility into what happened — how many leads were found, whether enrichment worked, if any pushes failed. Developer has no persistent record of expansion steps, API errors, or timing without checking ephemeral Python logs.

## Approach

Extend the existing Pipeline Health page (`11_Pipeline_Health.py`) with a Run History section. Two-tier display: summary for Mike, expandable detail for developer. No new tables — enriches the existing `summary_json` column in `pipeline_runs`.

## Data Model

Enrich `summary_json` with structured log events and summary metrics:

```json
{
  "log_events": [
    {"ts": "2026-03-10T15:30:01", "level": "info", "msg": "Contact Search: 45 contacts from 12 ZIPs"},
    {"ts": "2026-03-10T15:30:03", "level": "info", "msg": "Expansion: +Director level, 12 more contacts"},
    {"ts": "2026-03-10T15:30:05", "level": "warn", "msg": "Company Enrich: 2 of 30 companies not found"},
    {"ts": "2026-03-10T15:30:06", "level": "error", "msg": "VanillaSoft push failed for 1 lead", "detail": "HTTP 500: ..."}
  ],
  "contacts_searched": 45,
  "companies_enriched": 28,
  "expansions_applied": ["management_levels"],
  "duration_seconds": 12
}
```

Error events carry an optional `detail` field for tracebacks.

## Event Collection

`RunLogger` class in `db/_pipeline.py` accumulates events during execution:

```python
class RunLogger:
    def __init__(self): ...
    def info(self, msg): ...
    def warn(self, msg): ...
    def error(self, msg, detail=None): ...
    def set_metric(self, key, value): ...
    def to_summary(self) -> dict: ...
```

Pipeline code passes `run_logger` through and calls it at key moments. At completion, `run_logger.to_summary()` feeds into `complete_pipeline_run()`.

**Instrumentation points:**
- Contact Search start/results count
- Each expansion step applied
- Company Enrich results (matched vs not found)
- Contact Enrich results
- VanillaSoft push results (succeeded/failed)
- Errors with traceback in `detail`
- Total duration

## UI Rendering

New **Run History** section at bottom of Pipeline Health page.

**Collapsed row (Mike):** Status icon (green/yellow/red), relative timestamp, workflow type, leads exported, credits used, duration.

**Expanded row (developer):** `log_events` timeline with level badges, error tracebacks in code blocks, run config (ZIPs, radius, filters).

**Controls:** Workflow type filter (Intent / Geography / All). Last 20 runs by default.

Uses existing `styled_table`, `labeled_divider`, and `st.expander` components.

## Scope Boundaries

- No real-time streaming — logs written at run completion
- No log retention/cleanup — rows accumulate; pruning added later if needed
- No email notifications — in-app only
- No new DB tables or migrations
- No changes to existing Python `logger.*` calls — `RunLogger` is additive

## Files Changed

| File | Change |
|---|---|
| `db/_pipeline.py` | Add `RunLogger` class |
| `scripts/run_intent_pipeline.py` | Instrument with `run_logger.*` calls |
| `pages/1_Intent_Workflow.py` | Instrument manual workflow runs |
| `pages/2_Geography_Workflow.py` | Instrument manual workflow runs |
| `pages/11_Pipeline_Health.py` | Add Run History section |
