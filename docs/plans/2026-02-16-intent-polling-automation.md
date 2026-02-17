# Intent Polling Automation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automated daily intent lead polling Mon–Fri at 7:00 AM ET via GitHub Actions, with a Streamlit Automation dashboard for run history and manual triggers.

**Architecture:** GitHub Actions runs `scripts/run_intent_pipeline.py` on a cron schedule. The script connects directly to Turso cloud DB and ZoomInfo API, writes results, and emails a CSV summary. A new `pipeline_runs` table tracks every run. A new Streamlit page reads this table to display history, metrics, and a "Run Now" button.

**Tech Stack:** GitHub Actions (cron), existing Python pipeline script, Turso DB (libsql), Streamlit, Gmail SMTP

---

## Task 1: Add `pipeline_runs` Table and DB Methods

**Files:**
- Modify: `turso_db.py:221-234` (init_schema, add table after staged_exports)
- Modify: `turso_db.py:700` (add methods after Staged Exports section)
- Test: `tests/test_turso_db.py`

**Step 1: Write failing tests for the 3 new DB methods**

Add a new test class to `tests/test_turso_db.py`:

```python
class TestPipelineRuns:
    """Test pipeline_runs table operations."""

    def _get_db(self):
        """Create an in-memory DB with schema."""
        db = TursoDatabase.__new__(TursoDatabase)
        import libsql_experimental as libsql
        db.connection = libsql.connect(":memory:")
        db.url = ":memory:"
        db.init_schema()
        return db

    def test_start_pipeline_run_returns_id(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {"topics": ["Vending"]})
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_complete_pipeline_run_success(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "manual", {})
        db.complete_pipeline_run(
            run_id, "success",
            summary={"contacts_exported": 10},
            batch_id="HADES-20260216-001",
            credits_used=10,
            leads_exported=10,
            error=None,
        )
        runs = db.get_pipeline_runs("intent")
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["batch_id"] == "HADES-20260216-001"
        assert runs[0]["credits_used"] == 10
        assert runs[0]["leads_exported"] == 10
        assert runs[0]["completed_at"] is not None

    def test_complete_pipeline_run_failed(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(
            run_id, "failed",
            summary={}, batch_id=None,
            credits_used=0, leads_exported=0,
            error="API timeout",
        )
        runs = db.get_pipeline_runs("intent")
        assert runs[0]["status"] == "failed"
        assert runs[0]["error_message"] == "API timeout"

    def test_complete_pipeline_run_skipped(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {"topics": ["Vending"]})
        db.complete_pipeline_run(
            run_id, "skipped",
            summary={"budget_exceeded": True}, batch_id=None,
            credits_used=0, leads_exported=0,
            error="Weekly cap reached",
        )
        runs = db.get_pipeline_runs("intent")
        assert runs[0]["status"] == "skipped"

    def test_get_pipeline_runs_ordered_newest_first(self):
        db = self._get_db()
        id1 = db.start_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(id1, "success", {}, "B1", 5, 5, None)
        id2 = db.start_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(id2, "success", {}, "B2", 10, 10, None)
        runs = db.get_pipeline_runs("intent", limit=10)
        assert len(runs) == 2
        assert runs[0]["id"] == id2  # Newest first

    def test_get_pipeline_runs_respects_limit(self):
        db = self._get_db()
        for i in range(5):
            rid = db.start_pipeline_run("intent", "scheduled", {})
            db.complete_pipeline_run(rid, "success", {}, None, 0, 0, None)
        runs = db.get_pipeline_runs("intent", limit=3)
        assert len(runs) == 3

    def test_get_pipeline_runs_filters_by_workflow(self):
        db = self._get_db()
        rid = db.start_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(rid, "success", {}, None, 0, 0, None)
        runs = db.get_pipeline_runs("geography")
        assert len(runs) == 0

    def test_start_run_stores_config(self):
        db = self._get_db()
        config = {"topics": ["Vending"], "target_companies": 25}
        run_id = db.start_pipeline_run("intent", "manual", config)
        runs = db.get_pipeline_runs("intent")
        assert runs[0]["config"] == config

    def test_start_run_sets_running_status(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {})
        runs = db.get_pipeline_runs("intent")
        assert runs[0]["status"] == "running"
        assert runs[0]["completed_at"] is None
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_turso_db.py::TestPipelineRuns -v`
Expected: FAIL — `TursoDatabase` has no attribute `start_pipeline_run`

**Step 3: Add table to `init_schema()` and implement methods**

In `turso_db.py`, add to `init_schema()` after the `staged_exports` table (before the closing `]` on line 234):

```python
            # Pipeline automation run history
            """
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
            """,
            "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_workflow ON pipeline_runs(workflow_type)",
            "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created ON pipeline_runs(created_at)",
```

Add methods after the Staged Exports section (~line 770):

```python
    # --- Pipeline Runs ---

    def start_pipeline_run(
        self, workflow_type: str, trigger: str, config: dict,
    ) -> int:
        """Record start of an automated pipeline run. Returns the row id."""
        return self.execute_write(
            "INSERT INTO pipeline_runs (workflow_type, trigger, status, config_json, started_at) "
            "VALUES (?, ?, 'running', ?, CURRENT_TIMESTAMP)",
            (workflow_type, trigger, json.dumps(config)),
        )

    def complete_pipeline_run(
        self, run_id: int, status: str, summary: dict,
        batch_id: str | None, credits_used: int, leads_exported: int,
        error: str | None,
    ) -> None:
        """Update a pipeline run with completion details."""
        self.execute_write(
            """UPDATE pipeline_runs
               SET status = ?, summary_json = ?, batch_id = ?,
                   credits_used = ?, leads_exported = ?,
                   error_message = ?, completed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (status, json.dumps(summary), batch_id, credits_used,
             leads_exported, error, run_id),
        )

    def get_pipeline_runs(self, workflow_type: str, limit: int = 20) -> list[dict]:
        """Get recent pipeline runs (newest first)."""
        rows = self.execute(
            "SELECT id, workflow_type, trigger, status, config_json, summary_json, "
            "batch_id, credits_used, leads_exported, error_message, "
            "started_at, completed_at, created_at "
            "FROM pipeline_runs WHERE workflow_type = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (workflow_type, limit),
        )
        return [
            {
                "id": r[0],
                "workflow_type": r[1],
                "trigger": r[2],
                "status": r[3],
                "config": json.loads(r[4]) if r[4] else {},
                "summary": json.loads(r[5]) if r[5] else {},
                "batch_id": r[6],
                "credits_used": r[7],
                "leads_exported": r[8],
                "error_message": r[9],
                "started_at": r[10],
                "completed_at": r[11],
                "created_at": r[12],
            }
            for r in rows
        ]
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_turso_db.py::TestPipelineRuns -v`
Expected: all 9 tests PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 447+ passed

**Step 6: Commit**

```bash
git add turso_db.py tests/test_turso_db.py
git commit -m "Add pipeline_runs table and DB methods for automation tracking"
```

---

## Task 2: Update Pipeline Script to Log Runs

**Files:**
- Modify: `scripts/run_intent_pipeline.py:60-325` (run_pipeline function)
- Modify: `scripts/run_intent_pipeline.py:448-549` (main function, add --trigger arg)
- Test: `tests/test_run_intent_pipeline.py`

**Step 1: Write failing tests for pipeline run logging**

Add to `tests/test_run_intent_pipeline.py`:

```python
class TestPipelineRunLogging:
    """Pipeline should log runs to pipeline_runs table."""

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_successful_run_logs_to_db(self, MockClient, MockDB, MockCostTracker):
        config = _make_config(target_companies=1)
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
        ]
        client.search_contacts_all_pages.return_value = [
            _make_contact("p1", "100", "Acme Corp"),
        ]
        client.enrich_contacts_batch.side_effect = [
            [{"company": {"id": 100, "name": "Acme Corp"}, "companyId": 100}],
            [_make_contact("p1", "100", "Acme Corp")],
        ]

        db = MockDB.return_value
        db.get_company_ids_bulk.return_value = {}
        db.get_exported_company_ids.return_value = {}
        db.execute_write = MagicMock()
        db.execute.return_value = [("1",)]
        db.start_pipeline_run.return_value = 42

        result = run_pipeline(config, creds, trigger="manual")

        db.start_pipeline_run.assert_called_once_with("intent", "manual", config)
        db.complete_pipeline_run.assert_called_once()
        call_args = db.complete_pipeline_run.call_args
        assert call_args[0][0] == 42  # run_id
        assert call_args[0][1] == "success"  # status

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_budget_exceeded_logs_skipped(self, MockClient, MockDB, MockCostTracker):
        config = _make_config()
        creds = _make_creds()

        budget = MagicMock()
        budget.alert_level = "exceeded"
        budget.alert_message = "Weekly cap reached"
        MockCostTracker.return_value.check_budget.return_value = budget

        db = MockDB.return_value
        db.start_pipeline_run.return_value = 7

        result = run_pipeline(config, creds, trigger="scheduled")

        db.complete_pipeline_run.assert_called_once()
        call_args = db.complete_pipeline_run.call_args
        assert call_args[0][1] == "skipped"

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_accepts_external_db(self, MockClient, MockDB, MockCostTracker):
        """When db is passed, should use it instead of creating new one."""
        config = _make_config()
        creds = _make_creds()
        external_db = MagicMock()
        external_db.start_pipeline_run.return_value = 1

        budget = MagicMock()
        budget.alert_level = "exceeded"
        budget.alert_message = "cap"
        MockCostTracker.return_value.check_budget.return_value = budget

        result = run_pipeline(config, creds, trigger="manual", db=external_db)

        # Should NOT have created a new TursoDatabase
        MockDB.assert_not_called()
        # Should have used external_db
        external_db.start_pipeline_run.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_intent_pipeline.py::TestPipelineRunLogging -v`
Expected: FAIL — `run_pipeline() got unexpected keyword argument 'trigger'`

**Step 3: Modify `run_pipeline()` signature and add logging**

In `scripts/run_intent_pipeline.py`, change the signature on line 60:

```python
def run_pipeline(config: dict, creds: dict, dry_run: bool = False,
                 trigger: str = "scheduled", db=None) -> dict:
```

Replace lines 83-91 (dry_run check + db init) with:

```python
    if dry_run:
        logger.info("Dry run — validating config and module imports only")
        return {"success": True, "csv_content": None, "csv_filename": None,
                "batch_id": None, "summary": summary, "error": None}

    # --- Init clients (use provided db or create new) ---
    if db is None:
        db = TursoDatabase(url=creds["TURSO_DATABASE_URL"],
                           auth_token=creds["TURSO_AUTH_TOKEN"])
        db.init_schema()

    client = ZoomInfoClient(
        client_id=creds["ZOOMINFO_CLIENT_ID"],
        client_secret=creds["ZOOMINFO_CLIENT_SECRET"],
    )

    cost_tracker = CostTracker(db)

    # --- Log pipeline start ---
    run_id = db.start_pipeline_run("intent", trigger, config)
```

Replace the budget check (lines 100-107) to use "skipped" status:

```python
    # --- Budget check ---
    budget = cost_tracker.check_budget("intent", config["target_companies"])
    if budget.alert_level == "exceeded":
        msg = f"Budget exceeded: {budget.alert_message}"
        logger.warning(msg)
        summary["budget_exceeded"] = True
        db.complete_pipeline_run(run_id, "skipped", summary, None, 0, 0, msg)
        return {"success": True, "csv_content": None, "csv_filename": None,
                "batch_id": None, "summary": summary, "error": msg}
```

Before the final `return` at line 318, add:

```python
    db.complete_pipeline_run(
        run_id, "success", summary, batch_id,
        summary.get("credits_used", 0), len(scored_contacts), None,
    )
```

Wrap the pipeline body in try/except to catch failures (around lines 109-325). After the existing `except` blocks at the end of `run_pipeline`, add a top-level handler:

The simplest approach: wrap the entire section from Step 1 through the return in a try/except:

```python
    try:
        # ... existing pipeline steps 1-5 ...
        db.complete_pipeline_run(
            run_id, "success", summary, batch_id,
            summary.get("credits_used", 0), len(scored_contacts), None,
        )
        return {
            "success": True,
            "csv_content": csv_content,
            "csv_filename": csv_filename,
            "batch_id": batch_id,
            "summary": summary,
            "error": None,
        }
    except Exception as e:
        db.complete_pipeline_run(run_id, "failed", summary, None, 0, 0, str(e))
        raise
```

**Step 4: Update `main()` to accept `--trigger` arg**

Add to argparse section (~line 454):

```python
    parser.add_argument("--trigger", default="scheduled",
                        help="Run trigger source (scheduled, manual)")
```

Pass it to `run_pipeline` (~line 488):

```python
        result = run_pipeline(config, creds, dry_run=args.dry_run, trigger=args.trigger)
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_intent_pipeline.py -v`
Expected: All tests PASS (existing + new)

**Step 6: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: all pass

**Step 7: Commit**

```bash
git add scripts/run_intent_pipeline.py tests/test_run_intent_pipeline.py
git commit -m "Log pipeline runs to DB with status tracking and trigger source"
```

---

## Task 3: Update `_credentials.py` for Streamlit Fallback

**Files:**
- Modify: `scripts/_credentials.py`
- Test: `tests/test_run_intent_pipeline.py`

**Step 1: Write failing test**

Add to `tests/test_run_intent_pipeline.py` in `TestCredentialLoading`:

```python
    @patch.dict("os.environ", {}, clear=True)
    @patch("scripts._credentials.Path.exists", return_value=False)
    def test_streamlit_secrets_fallback(self, _mock_exists):
        """When running inside Streamlit, should use st.secrets."""
        mock_secrets = {
            "TURSO_DATABASE_URL": "libsql://st-secrets.turso.io",
            "TURSO_AUTH_TOKEN": "st-token",
            "ZOOMINFO_CLIENT_ID": "st-id",
            "ZOOMINFO_CLIENT_SECRET": "st-secret",
        }
        mock_st = MagicMock()
        mock_st.secrets = mock_secrets
        # Make st.secrets behave like a dict for .get()
        mock_st.secrets.get = mock_secrets.get

        with patch.dict("sys.modules", {"streamlit": mock_st}):
            # Need to reload to pick up the mocked streamlit
            import importlib
            import scripts._credentials as cred_mod
            importlib.reload(cred_mod)
            creds = cred_mod.load_credentials()
            assert creds["TURSO_DATABASE_URL"] == "libsql://st-secrets.turso.io"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_run_intent_pipeline.py::TestCredentialLoading::test_streamlit_secrets_fallback -v`
Expected: FAIL

**Step 3: Add Streamlit fallback to `_credentials.py`**

In `scripts/_credentials.py`, add Streamlit secrets as a source after the secrets.toml fallback (after line 31):

```python
    # Try Streamlit secrets (when running inside Streamlit app)
    st_secrets = {}
    try:
        import streamlit as st
        if hasattr(st, "secrets") and st.secrets:
            st_secrets = dict(st.secrets)
    except Exception:
        pass
```

Update the `_get` function to check `st_secrets`:

```python
    def _get(key: str, required: bool = False) -> str | None:
        val = os.environ.get(key) or secrets.get(key) or st_secrets.get(key)
        if required and not val:
            raise ValueError(f"Missing required credential: {key}. "
                             f"Set via environment or .streamlit/secrets.toml")
        return val
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_run_intent_pipeline.py::TestCredentialLoading -v`
Expected: all PASS

**Step 5: Run full suite**

Run: `python -m pytest tests/ -x -q --tb=short`

**Step 6: Commit**

```bash
git add scripts/_credentials.py tests/test_run_intent_pipeline.py
git commit -m "Add Streamlit secrets fallback to credentials loader for Run Now"
```

---

## Task 4: Create GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/intent-poll.yml`

**Step 1: Create the workflow file**

```yaml
name: Intent Lead Poll

on:
  schedule:
    # 12:00 UTC = 7:00 AM ET (Mon-Fri)
    - cron: '0 12 * * 1-5'
  workflow_dispatch:
    # Allow manual trigger from GitHub UI
    inputs:
      dry_run:
        description: 'Dry run (no API calls)'
        type: boolean
        default: false

jobs:
  poll-intent:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run intent pipeline
        env:
          TURSO_DATABASE_URL: ${{ secrets.TURSO_DATABASE_URL }}
          TURSO_AUTH_TOKEN: ${{ secrets.TURSO_AUTH_TOKEN }}
          ZOOMINFO_CLIENT_ID: ${{ secrets.ZOOMINFO_CLIENT_ID }}
          ZOOMINFO_CLIENT_SECRET: ${{ secrets.ZOOMINFO_CLIENT_SECRET }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
          EMAIL_RECIPIENTS: ${{ secrets.EMAIL_RECIPIENTS }}
        run: |
          python scripts/run_intent_pipeline.py \
            --trigger scheduled \
            --verbose \
            ${{ github.event.inputs.dry_run == 'true' && '--dry-run' || '' }}
```

**Step 2: Validate YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/intent-poll.yml'))"`
Expected: no error

**Step 3: Commit**

```bash
git add .github/workflows/intent-poll.yml
git commit -m "Add GitHub Actions workflow for daily intent polling (Mon-Fri 7AM ET)"
```

---

## Task 5: Create Automation Dashboard Page

**Files:**
- Create: `pages/9_Automation.py`

**Step 1: Create the page**

Reference patterns from existing pages:
- `pages/5_Usage_Dashboard.py` for metric cards and table layout
- `pages/6_Executive_Summary.py` for summary display
- All pages start with `inject_base_styles()`
- Session state keys prefixed `auto_`

The page should:

1. Import and call `inject_base_styles()`, `page_header()`, `metric_card()`, `status_badge()`, `labeled_divider()` from `ui_components.py`
2. Import `get_database` from `turso_db`, `CostTracker` from `cost_tracker`, `get_automation_config` from `utils`
3. Show header with "Run Now" button
4. Show 3 metric cards: Next Run, Last Run, Weekly Credits
5. Show run history table from `db.get_pipeline_runs("intent")`
6. Show read-only config from `get_automation_config("intent")`
7. "Run Now" button:
   - Import `run_pipeline` from `scripts.run_intent_pipeline`
   - Import `load_credentials` from `scripts._credentials`
   - Call with `trigger="manual"`, `db=db` (reuse cached connection)
   - Show results inline

Key implementation details:
- Next run: compute from current time — next weekday at 7:00 AM ET
- Status badges: green "success", red "failed", yellow "skipped", blue "running"
- Expandable rows: use `st.expander` for each run showing full summary JSON
- Run Now rerun guard: `auto_run_triggered` session state flag

**Step 2: Verify page loads**

Open `http://localhost:8501/Automation` in browser — should show empty history with config panel.

**Step 3: Commit**

```bash
git add pages/9_Automation.py
git commit -m "Add Automation dashboard page with run history and manual trigger"
```

---

## Task 6: Integration Test and Final Verification

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: all pass (450+)

**Step 2: Manual smoke test — Run Now in browser**

1. Start Streamlit: `streamlit run app.py`
2. Navigate to Automation page
3. Verify config panel shows automation settings from `icp.yaml`
4. Enable Test Mode if available, or click "Run Now"
5. Verify run appears in history table with correct status
6. Verify metrics update (weekly credits, last run)

**Step 3: Verify GitHub Actions YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/intent-poll.yml')); print('Valid')"`

**Step 4: Update CLAUDE.md with new page**

Add `pages/9_Automation.py` to the file structure section and note the automation feature.

**Step 5: Final commit**

```bash
git add CLAUDE.md
git commit -m "Update docs for Automation page and intent polling feature"
```
