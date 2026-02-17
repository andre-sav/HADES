# Intent Polling Automation Design

**Date**: 2026-02-16
**Status**: Approved

## Goal

Automated daily intent lead polling Mon–Fri at 7:00 AM ET. Runs the full Intent pipeline headlessly via GitHub Actions, writes results to Turso DB, emails a summary with VanillaSoft CSV attachment, and surfaces run history in a new Automation dashboard page.

## Architecture

```
GitHub Actions (cron: Mon-Fri 7:00 AM ET)
    │
    ▼
scripts/run_intent_pipeline.py
    │
    ├── ZoomInfo API (intent search → contact search → enrich)
    ├── Turso DB (pipeline_runs, lead_outcomes, credit_usage, staged_exports)
    └── Gmail SMTP (summary email + CSV attachment)

Streamlit App (pages/9_Automation.py)
    │
    └── Reads pipeline_runs table → displays history, metrics, config
        └── "Run Now" button → calls run_pipeline() in-process
```

## Section 1: GitHub Actions Workflow

**File**: `.github/workflows/intent-poll.yml`

- **Schedule**: `cron: '0 12 * * 1-5'` (12:00 UTC = 7:00 AM ET, Mon–Fri)
- **Steps**: checkout → setup Python → install deps → run script
- **Secrets** (GitHub repo settings): `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `ZOOMINFO_CLIENT_ID`, `ZOOMINFO_CLIENT_SECRET`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_RECIPIENTS`
- GitHub sends alerts on workflow failure (exit code 1)

## Section 2: Pipeline Runs Table

**New table in `turso_db.py:init_schema()`**:

```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_type TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    config_json TEXT,
    summary_json TEXT,
    batch_id TEXT,
    credits_used INTEGER DEFAULT 0,
    leads_exported INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

**Status values**: `running`, `success`, `failed`, `skipped` (budget exceeded)

**New `turso_db.py` methods**:
- `start_pipeline_run(workflow_type, trigger, config) -> int`
- `complete_pipeline_run(run_id, status, summary, batch_id, credits_used, leads_exported, error)`
- `get_pipeline_runs(workflow_type, limit=20) -> list[dict]`

## Section 3: Automation Dashboard Page

**File**: `pages/9_Automation.py`

**Layout**:
1. **Header** — Title, caption, "Run Now" button
2. **Metrics row** — Next scheduled run, last run time + status, weekly credit usage
3. **Run History table** — From `pipeline_runs`. Expandable rows for full summary, errors, config. Paginated (10/page).
4. **Configuration panel** — Read-only display of `automation.intent` from `config/icp.yaml`

**"Run Now"** imports `run_pipeline()` directly, runs in-process with `st.spinner`, logs with `trigger="manual"`.

## Section 4: Script Changes

**`scripts/run_intent_pipeline.py`**:
- Accept optional `db` parameter (reuse Streamlit's cached DB connection)
- Log to `pipeline_runs` table (start → complete/fail/skip)
- Add `--trigger` CLI arg (default: `"scheduled"`)
- Budget-exceeded → `status="skipped"` instead of `status="success"` with error

**`scripts/_credentials.py`**:
- Fallback to `st.secrets` when running inside Streamlit (for "Run Now")

## Section 5: Scope

**New files**: `.github/workflows/intent-poll.yml`, `pages/9_Automation.py`

**Modified files**: `turso_db.py`, `scripts/run_intent_pipeline.py`, `scripts/_credentials.py`

**Tests**: New tests for 3 `turso_db` methods, `_credentials.py` fallback, pipeline_runs logging in existing test file.

**Excluded (YAGNI)**: UI config editing, pause/resume scheduling, Geography automation, Slack notifications.
