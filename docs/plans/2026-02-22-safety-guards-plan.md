# Safety Guards Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add safety guards for all irreversible actions — confirmation dialogs, concurrent-run protection, and data integrity constraints.

**Architecture:** Four isolated changes: `@st.dialog` confirmations on Push and Run Now buttons, a DB-level concurrent-run guard in the pipeline entry point, a UNIQUE index migration on `lead_outcomes`, and a `try/finally` fix on the automation page.

**Tech Stack:** Streamlit (`@st.dialog`), SQLite/Turso (migrations, UNIQUE index), Python

---

### Task 1: UNIQUE Constraint on lead_outcomes + INSERT OR IGNORE

**Files:**
- Modify: `turso_db.py:217-218` (add migration after existing indexes)
- Modify: `turso_db.py:657-663` (change INSERT to INSERT OR IGNORE)
- Test: `tests/test_turso_db.py`

**Step 1: Write the failing test**

In `tests/test_turso_db.py`, add to the existing lead outcomes test area:

```python
def test_record_lead_outcomes_rejects_duplicates(self):
    """Duplicate (batch_id, person_id) rows are silently ignored."""
    import sqlite3
    db = TursoDatabase.__new__(TursoDatabase)
    db._conn = sqlite3.connect(":memory:")
    db.url = ":memory:"
    db.init_schema()

    row = (
        "batch-1", "Acme Corp", "c-100", "p-200", "7011", 500,
        5.0, "75201", "TX", 85, "intent", "2026-02-22T10:00:00", None,
    )
    db.record_lead_outcomes_batch([row])
    db.record_lead_outcomes_batch([row])  # duplicate

    count = db.execute("SELECT COUNT(*) FROM lead_outcomes")[0][0]
    assert count == 1, f"Expected 1 row, got {count} — UNIQUE constraint missing"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_turso_db.py::TestLeadOutcomes::test_record_lead_outcomes_rejects_duplicates -v`
Expected: FAIL — `assert 2 == 1` (no UNIQUE, both inserts succeed)

Note: if TestLeadOutcomes doesn't exist as a class name, find the correct class or use `-k test_record_lead_outcomes_rejects_duplicates`.

**Step 3: Add UNIQUE index migration and change INSERT to INSERT OR IGNORE**

In `turso_db.py`, after line 218 (`idx_lead_outcomes_company_exported`), add the migration:

```python
"CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_outcomes_batch_person ON lead_outcomes(batch_id, person_id)",
```

In `turso_db.py` line 658, change:

```python
"""INSERT INTO lead_outcomes
```

to:

```python
"""INSERT OR IGNORE INTO lead_outcomes
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_turso_db.py::TestLeadOutcomes::test_record_lead_outcomes_rejects_duplicates -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 578+ passed

**Step 6: Commit**

```bash
git add turso_db.py tests/test_turso_db.py
git commit -m "fix: add UNIQUE(batch_id, person_id) on lead_outcomes + INSERT OR IGNORE"
```

---

### Task 2: Concurrent-Run Guard

**Files:**
- Modify: `turso_db.py` (add `has_running_pipeline` method)
- Modify: `scripts/run_intent_pipeline.py:104` (add guard before pipeline start)
- Test: `tests/test_turso_db.py`

**Step 1: Write the failing test**

In `tests/test_turso_db.py`, add to `TestPipelineRuns`:

```python
def test_has_running_pipeline(self):
    """Detect if a pipeline run is already in progress."""
    db = self._get_db()
    assert db.has_running_pipeline("intent") is False

    run_id = db.start_pipeline_run("intent", "scheduled", {})
    assert db.has_running_pipeline("intent") is True

    db.complete_pipeline_run(run_id, "success", {}, None, 0, 0, None)
    assert db.has_running_pipeline("intent") is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_turso_db.py::TestPipelineRuns::test_has_running_pipeline -v`
Expected: FAIL — `AttributeError: has_running_pipeline`

**Step 3: Add `has_running_pipeline` method to TursoDatabase**

In `turso_db.py`, after `get_pipeline_runs` method:

```python
def has_running_pipeline(self, workflow_type: str) -> bool:
    """Check if any pipeline run is currently in 'running' status."""
    rows = self.execute(
        "SELECT id FROM pipeline_runs WHERE workflow_type = ? AND status = 'running' LIMIT 1",
        (workflow_type,),
    )
    return len(rows) > 0
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_turso_db.py::TestPipelineRuns::test_has_running_pipeline -v`
Expected: PASS

**Step 5: Add guard to `run_pipeline()`**

In `scripts/run_intent_pipeline.py`, after line 103 (`run_id = db.start_pipeline_run(...)`) — actually, BEFORE that line (after `cost_tracker = CostTracker(db)` on line 101), add:

```python
# --- Concurrent-run guard ---
if db.has_running_pipeline("intent"):
    logger.warning("Pipeline already running — aborting to prevent overlap")
    return {
        "success": False, "csv_content": None, "csv_filename": None,
        "batch_id": None, "summary": summary, "error": "Pipeline already running",
    }
```

**Step 6: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 578+ passed

**Step 7: Commit**

```bash
git add turso_db.py scripts/run_intent_pipeline.py tests/test_turso_db.py
git commit -m "fix: add concurrent-run guard on intent pipeline"
```

---

### Task 3: Confirmation Dialog — VanillaSoft Push

**Files:**
- Modify: `pages/4_CSV_Export.py:376-404` (add dialog, gate push on confirmation flag)

**Step 1: Add `@st.dialog` and gate push execution**

In `pages/4_CSV_Export.py`, before the Push button (around line 370), add the dialog function:

```python
@st.dialog("Confirm Push to VanillaSoft")
def confirm_push_dialog(lead_count, operator_name):
    st.write(f"Push **{lead_count}** leads to VanillaSoft?")
    if operator_name:
        st.write(f"Operator: **{operator_name}**")
    st.caption("This creates real CRM records that cannot be undone.")
    st.markdown("")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Push", type="primary", use_container_width=True):
            st.session_state["vs_push_confirmed"] = True
            st.rerun()
    with col_no:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
```

Change the Push button click handler (line 376-394). The button should open the dialog instead of immediately pushing:

```python
with col2:
    push_clicked = st.button(
        "\U0001f4e4 Push to VanillaSoft",
        type="primary",
        use_container_width=True,
        disabled=not _vs_push_available,
        help=None if _vs_push_available else "Configure VANILLASOFT_WEB_LEAD_ID in .streamlit/secrets.toml",
    )

# Open dialog on button click
if push_clicked and _vs_push_available:
    _op_name = selected_operator.get("operator_name") if selected_operator else None
    confirm_push_dialog(len(leads_to_export), _op_name)

# Execute push only after dialog confirmation
if st.session_state.pop("vs_push_confirmed", False) and _vs_push_available:
    # ... existing push logic (lines 395-476) stays here, unchanged ...
```

The key change: replace `if push_clicked and _vs_push_available:` (line 394) with `if st.session_state.pop("vs_push_confirmed", False) and _vs_push_available:`.

**Step 2: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 578+ passed (page scripts aren't unit-tested directly)

**Step 3: Commit**

```bash
git add pages/4_CSV_Export.py
git commit -m "fix: add confirmation dialog before VanillaSoft push"
```

---

### Task 4: Confirmation Dialog — Run Now + try/finally Fix

**Files:**
- Modify: `pages/9_Automation.py:189-213` (add dialog, fix finally block)

**Step 1: Add `@st.dialog` and fix `try/finally`**

In `pages/9_Automation.py`, before the Run Now button (around line 175), add:

```python
@st.dialog("Confirm Pipeline Run")
def confirm_run_now_dialog(topics, target):
    st.write(f"Run intent pipeline now?")
    st.write(f"Search **{', '.join(topics)}** signals, find top **{target}** companies, enrich contacts, email CSV.")
    st.caption("Credits will be consumed from your weekly budget.")
    st.markdown("")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Run", type="primary", use_container_width=True):
            st.session_state["auto_run_confirmed"] = True
            st.rerun()
    with col_no:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
```

Change the Run Now button to open dialog, and gate execution on confirmation:

```python
with now_col2:
    run_now = st.button(
        "Run Now", type="primary", use_container_width=True, key="auto_run_now",
    )

# Open dialog on button click
if run_now:
    confirm_run_now_dialog(topics, target)

# Execute pipeline only after dialog confirmation
if st.session_state.pop("auto_run_confirmed", False) and not st.session_state.get("auto_run_triggered"):
    st.session_state["auto_run_triggered"] = True
    try:
        with st.spinner("Running intent pipeline..."):
            from scripts.run_intent_pipeline import run_pipeline
            from scripts._credentials import load_credentials

            creds = load_credentials()
            result = run_pipeline(auto_config, creds, trigger="manual", db=db)

            if result["success"]:
                exported = result.get("summary", {}).get("contacts_exported", 0)
                st.success(f"Pipeline complete — {exported} leads exported.")
                if result.get("batch_id"):
                    st.caption(f"Batch {result['batch_id']}")
            else:
                st.error(f"Pipeline failed: {result.get('error', 'Unknown error')}")
    except Exception as e:
        st.error(f"Pipeline error: {e}")
    finally:
        st.session_state["auto_run_triggered"] = False
    st.rerun()
```

Key changes:
1. Button opens dialog instead of immediately running
2. Execution gated on `auto_run_confirmed` flag (popped to prevent repeat)
3. `auto_run_triggered = False` moved to `finally` block

**Step 2: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 578+ passed

**Step 3: Commit**

```bash
git add pages/9_Automation.py
git commit -m "fix: add confirmation dialog for Run Now + try/finally on auto_run_triggered"
```

---

### Task 5: Final Verification + Close Bead

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass

**Step 2: Close bead and sync**

```bash
bd close HADES-dd6 --reason="All 5 safety guards implemented: Push dialog, Run Now dialog, concurrent-run guard, UNIQUE constraint, try/finally fix"
bd sync
```

**Step 3: Update SESSION_HANDOFF.md**
