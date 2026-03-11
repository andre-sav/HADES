# Pipeline Log Panel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a two-tier run history to Pipeline Health — summary for sales user, expandable detail for developer.

**Architecture:** `RunLogger` collects structured events during pipeline execution, stores them in the existing `summary_json` column of `pipeline_runs`, and Pipeline Health renders them as expandable rows.

**Tech Stack:** Python, Streamlit, Turso (existing `pipeline_runs` table), existing `ui_components` helpers.

---

### Task 1: RunLogger class

**Files:**
- Modify: `db/_pipeline.py:1-76`
- Test: `tests/test_pipeline_db.py` (create if not exists, or find existing)

**Step 1: Write failing tests**

Find the existing pipeline DB test file. If none exists, create `tests/test_run_logger.py`:

```python
"""Tests for RunLogger event collection."""
import time
from db._pipeline import RunLogger


class TestRunLogger:
    def test_info_event(self):
        rl = RunLogger()
        rl.info("Contact Search: 45 contacts")
        assert len(rl.events) == 1
        assert rl.events[0]["level"] == "info"
        assert rl.events[0]["msg"] == "Contact Search: 45 contacts"
        assert "ts" in rl.events[0]

    def test_warn_event(self):
        rl = RunLogger()
        rl.warn("2 companies not found")
        assert rl.events[0]["level"] == "warn"

    def test_error_event_with_detail(self):
        rl = RunLogger()
        rl.error("Push failed", detail="HTTP 500: Internal Server Error")
        assert rl.events[0]["level"] == "error"
        assert rl.events[0]["detail"] == "HTTP 500: Internal Server Error"

    def test_error_event_without_detail(self):
        rl = RunLogger()
        rl.error("Something broke")
        assert "detail" not in rl.events[0]

    def test_set_metric(self):
        rl = RunLogger()
        rl.set_metric("contacts_searched", 45)
        rl.set_metric("companies_enriched", 28)
        assert rl.metrics == {"contacts_searched": 45, "companies_enriched": 28}

    def test_to_summary_combines_events_and_metrics(self):
        rl = RunLogger()
        rl.info("Step 1 done")
        rl.set_metric("contacts_searched", 10)
        summary = rl.to_summary()
        assert "log_events" in summary
        assert len(summary["log_events"]) == 1
        assert summary["contacts_searched"] == 10

    def test_to_summary_includes_duration(self):
        rl = RunLogger()
        time.sleep(0.05)
        summary = rl.to_summary()
        assert "duration_seconds" in summary
        assert summary["duration_seconds"] >= 0

    def test_has_errors(self):
        rl = RunLogger()
        assert rl.has_errors is False
        rl.error("broke")
        assert rl.has_errors is True
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_logger.py -v`
Expected: FAIL — `ImportError: cannot import name 'RunLogger'`

**Step 3: Implement RunLogger**

Add to `db/_pipeline.py` before the `PipelineRunsMixin` class:

```python
import time
from datetime import datetime, timezone


class RunLogger:
    """Collects structured log events during a pipeline run.

    Usage:
        rl = RunLogger()
        rl.info("Contact Search: 45 contacts from 12 ZIPs")
        rl.set_metric("contacts_searched", 45)
        ...
        summary = rl.to_summary()  # pass to complete_pipeline_run()
    """

    def __init__(self):
        self.events: list[dict] = []
        self.metrics: dict = {}
        self._start = time.monotonic()

    def info(self, msg: str) -> None:
        self.events.append({"ts": self._now(), "level": "info", "msg": msg})

    def warn(self, msg: str) -> None:
        self.events.append({"ts": self._now(), "level": "warn", "msg": msg})

    def error(self, msg: str, detail: str | None = None) -> None:
        event = {"ts": self._now(), "level": "error", "msg": msg}
        if detail:
            event["detail"] = detail
        self.events.append(event)

    def set_metric(self, key: str, value) -> None:
        self.metrics[key] = value

    @property
    def has_errors(self) -> bool:
        return any(e["level"] == "error" for e in self.events)

    def to_summary(self) -> dict:
        duration = round(time.monotonic() - self._start, 1)
        return {
            "log_events": self.events,
            "duration_seconds": duration,
            **self.metrics,
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_logger.py -v`
Expected: All 8 PASS

**Step 5: Run full suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 764+ passed

**Step 6: Commit**

```bash
git add db/_pipeline.py tests/test_run_logger.py
git commit -m "feat: add RunLogger for structured pipeline event collection"
```

---

### Task 2: Instrument headless intent pipeline

**Files:**
- Modify: `scripts/run_intent_pipeline.py`
- Depends on: Task 1

**Step 1: Write a failing integration test**

In `tests/test_run_logger.py`, add:

```python
def test_run_logger_integrates_with_summary_json():
    """RunLogger output is valid for complete_pipeline_run summary param."""
    rl = RunLogger()
    rl.info("Intent search: 15 results")
    rl.set_metric("intent_results", 15)
    rl.warn("2 stale signals")
    summary = rl.to_summary()

    # Verify it's JSON-serializable (complete_pipeline_run calls json.dumps)
    import json
    serialized = json.dumps(summary)
    parsed = json.loads(serialized)
    assert parsed["intent_results"] == 15
    assert len(parsed["log_events"]) == 2
```

**Step 2: Run test — should pass** (RunLogger is already implemented)

Run: `python -m pytest tests/test_run_logger.py::test_run_logger_integrates_with_summary_json -v`

**Step 3: Instrument `run_pipeline()` in `scripts/run_intent_pipeline.py`**

Changes to make (add `run_logger` parameter and calls at each step):

1. Add import at top: `from db._pipeline import RunLogger`
2. At `run_pipeline()` function start (after `summary = {}`): `run_logger = RunLogger()`
3. After each major step, add a `run_logger` call alongside the existing `logger.info`:

| Location (after line) | run_logger call |
|---|---|
| 198 (intent search results) | `run_logger.info(f"Intent Search: {len(intent_results)} results")` and `run_logger.set_metric("intent_results", len(intent_results))` |
| 220 (dedup) | `run_logger.info(f"Dedup: {len(new_leads)} new, {len(filtered_leads)} previously exported")` |
| 309 (contact search) | `run_logger.info(f"Contact Search: {len(contacts)} contacts")` and `run_logger.set_metric("contacts_found", len(contacts))` |
| 345 (enrich) | `run_logger.info(f"Contact Enrich: {len(enriched)} contacts")` and `run_logger.set_metric("contacts_enriched", len(enriched))` |
| 360 (company enrich success) | `run_logger.info(f"Company Enrich: {len(company_data)} companies merged")` and `run_logger.set_metric("companies_enriched", len(company_data))` |
| 362 (company enrich failure) | `run_logger.warn(f"Company Enrich failed (non-fatal): {e}")` |
| 395 (export) | `run_logger.info(f"Exported {len(scored_contacts)} contacts")` and `run_logger.set_metric("contacts_exported", len(scored_contacts))` |

4. At each `complete_pipeline_run()` call, merge run_logger summary into the existing `summary` dict:

Replace patterns like:
```python
db.complete_pipeline_run(run_id, "success", summary, None, 0, 0, None)
```
With:
```python
summary.update(run_logger.to_summary())
db.complete_pipeline_run(run_id, "success", summary, None, 0, 0, None)
```

Do this for ALL `complete_pipeline_run()` calls in the function (there are ~6 of them: budget exceeded, no intent results, no company IDs, no contacts, success, and the except block).

5. In the `except` block (around line 420), add:
```python
run_logger.error(f"Pipeline failed: {e}", detail=traceback.format_exc())
```

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass (no behavior change, just additive logging)

**Step 5: Commit**

```bash
git add scripts/run_intent_pipeline.py
git commit -m "feat: instrument headless intent pipeline with RunLogger"
```

---

### Task 3: Add `get_all_pipeline_runs` query

**Files:**
- Modify: `db/_pipeline.py:35-62`
- Test: existing pipeline DB tests or `tests/test_run_logger.py`

The current `get_pipeline_runs()` requires a `workflow_type` filter. The UI needs an "All" option.

**Step 1: Write failing test**

```python
def test_get_all_pipeline_runs(mock_db):
    """get_all_pipeline_runs returns all workflow types."""
    # This test needs a mock DB or uses the existing test DB fixture.
    # If no fixture exists, test the SQL pattern directly.
    pass
```

Skip formal TDD here — this is a one-line SQL variant. Add the method directly.

**Step 2: Add method to `PipelineRunsMixin` in `db/_pipeline.py`**

After the existing `get_pipeline_runs` method (line 62), add:

```python
def get_all_pipeline_runs(self, limit: int = 20) -> list[dict]:
    """Get recent pipeline runs across all workflow types (newest first)."""
    rows = self.execute(
        "SELECT id, workflow_type, trigger, status, config_json, summary_json, "
        "batch_id, credits_used, leads_exported, error_message, "
        "started_at, completed_at, created_at "
        "FROM pipeline_runs "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
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

**Step 3: Run full suite**

Run: `python -m pytest tests/ -x -q --tb=short`

**Step 4: Commit**

```bash
git add db/_pipeline.py
git commit -m "feat: add get_all_pipeline_runs for cross-workflow queries"
```

---

### Task 4: Run History UI on Pipeline Health page

**Files:**
- Modify: `pages/11_Pipeline_Health.py:232-304`

**Step 1: Replace the "Recent Pipeline Runs" section**

Replace the section from line 232 (`# RECENT ERRORS` comment with `labeled_divider("Recent Pipeline Runs")`) through line 304 with a new two-tier Run History section.

The new section:

```python
# =============================================================================
# RUN HISTORY
# =============================================================================
labeled_divider("Run History")

_wf_filter = st.radio(
    "Workflow", ["All", "Intent", "Geography"],
    horizontal=True, label_visibility="collapsed",
)

try:
    if _wf_filter == "All":
        _runs = db.get_all_pipeline_runs(limit=20)
    else:
        _runs = db.get_pipeline_runs(_wf_filter.lower(), limit=20)

    if _runs:
        for run in _runs:
            _status = run.get("status", "unknown")
            _summary = run.get("summary", {})
            _log_events = _summary.get("log_events", [])
            _duration = _summary.get("duration_seconds")
            _ts = run.get("started_at", "")
            _ago = time_ago(_ts) if _ts else "—"
            _wf = run.get("workflow_type", "—").title()
            _trigger = (run.get("trigger") or "manual").title()
            _leads = run.get("leads_exported", 0) or 0
            _credits = run.get("credits_used", 0) or 0
            _error = run.get("error_message")

            # Status icon
            if _status == "completed":
                _icon = "✅"
            elif _status == "failed":
                _icon = "❌"
            elif _status == "running":
                _icon = "🔄"
            elif _status == "skipped":
                _icon = "⏭️"
            else:
                _icon = "•"

            # Summary line
            _parts = [f"**{_wf}** · {_trigger}"]
            if _leads:
                _parts.append(f"{_leads} leads")
            if _credits:
                _parts.append(f"{_credits} credits")
            if _duration:
                _parts.append(f"{_duration}s")
            if _error:
                _parts.append(f"⚠️ {_error[:60]}")
            _summary_line = " · ".join(_parts)

            with st.expander(f"{_icon} {_ago} — {_summary_line}"):
                # Detail tier: log events timeline
                if _log_events:
                    for evt in _log_events:
                        _lvl = evt.get("level", "info")
                        _badge = {"info": "ℹ️", "warn": "⚠️", "error": "🔴"}.get(_lvl, "•")
                        _evt_ts = evt.get("ts", "")[:19].replace("T", " ")
                        st.markdown(f"`{_evt_ts}` {_badge} {html.escape(evt.get('msg', ''))}")
                        if evt.get("detail"):
                            st.code(evt["detail"], language="text")
                else:
                    st.caption("No detailed log events recorded for this run.")

                # Run config (collapsed)
                _config = run.get("config")
                if _config:
                    with st.popover("Run Config"):
                        st.json(_config)
    else:
        empty_state(
            "No pipeline runs recorded",
            hint="Runs are logged by automated pipelines and manual workflow searches.",
        )
except Exception:
    logger.exception("Failed to load run history")
    st.caption("Run history not available")
```

**Step 2: Verify the existing "Query History" and "Recent Errors" sections below are NOT removed** — they stay as-is after the new Run History section.

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`

**Step 4: Manual test** — Run `streamlit run app.py`, navigate to Pipeline Health, verify:
- Workflow filter radio buttons appear
- Existing pipeline runs show in collapsed rows
- Expanding a row shows log events (if any) or "No detailed log events" message
- No errors in browser console

**Step 5: Commit**

```bash
git add pages/11_Pipeline_Health.py
git commit -m "feat: two-tier run history on Pipeline Health page"
```

---

### Task 5: Instrument Geography Workflow

**Files:**
- Modify: `pages/2_Geography_Workflow.py`
- Depends on: Task 1

This is the most complex instrumentation because Geography runs happen interactively in Streamlit with fragment polling and expansion. The approach: create a `RunLogger` in session state when a search starts, append events during execution, and persist via `summary_json` when results are staged/exported.

**Step 1: Add RunLogger to session state at search start**

Near the search button handler (where `geo_results` gets set), add:
```python
from db._pipeline import RunLogger
st.session_state["geo_run_logger"] = RunLogger()
```

**Step 2: Add `run_logger` calls at key points**

| Event | run_logger call |
|---|---|
| Search starts | `rl.info(f"Search: {len(zip_codes)} ZIPs, radius={radius}mi")` |
| Results returned | `rl.info(f"Found {len(contacts)} contacts")` and `rl.set_metric("contacts_found", len(contacts))` |
| Each expansion step | `rl.info(f"Expansion: {expansion_desc}")` |
| Company Enrich | `rl.info(f"Company Enrich: {len(companies)} merged")` or `rl.warn(...)` on failure |
| Export/stage | `rl.info(f"Staged {count} leads")` and `rl.set_metric("leads_staged", count)` |

Access the logger from session state: `rl = st.session_state.get("geo_run_logger")` — if None, skip (backward compatible with runs that started before this feature).

**Step 3: Persist summary when saving pipeline run**

At the point where `db.complete_pipeline_run()` is called for geography (or if geography doesn't currently use pipeline_runs, add a `start_pipeline_run` / `complete_pipeline_run` pair), merge `run_logger.to_summary()` into the summary dict.

**Note:** Geography workflow may not currently create pipeline_runs entries (those were added for the automated intent pipeline). Check if geography calls `start_pipeline_run` — if not, add it. The pattern is:
```python
run_id = db.start_pipeline_run("geography", "manual", config_dict)
# ... at completion ...
summary.update(rl.to_summary())
db.complete_pipeline_run(run_id, status, summary, batch_id, credits, leads, error)
```

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`

**Step 5: Manual test** — Run a geography search in test mode, check Pipeline Health for the new run entry.

**Step 6: Commit**

```bash
git add pages/2_Geography_Workflow.py
git commit -m "feat: instrument Geography Workflow with RunLogger"
```

---

### Task 6: Instrument Intent Workflow (Streamlit UI)

**Files:**
- Modify: `pages/1_Intent_Workflow.py`
- Depends on: Task 1

Same pattern as Task 5 but for the manual Intent workflow page. Follow the same approach:

1. Create `RunLogger` in session state when intent search starts
2. Add `run_logger` calls at: intent search results, scoring, contact search, enrich, company enrich, export
3. Persist via `start_pipeline_run` / `complete_pipeline_run`

**Step 1-4:** Mirror Task 5 pattern for Intent Workflow.

**Step 5: Commit**

```bash
git add pages/1_Intent_Workflow.py
git commit -m "feat: instrument Intent Workflow UI with RunLogger"
```

---

### Task 7: Final verification and cleanup

**Files:** None new

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 764+ tests passing

**Step 2: Manual end-to-end test**

1. Run a Geography search (test mode) — verify run appears in Pipeline Health
2. Check the expanded view shows log events with timestamps
3. Filter by workflow type — verify it filters correctly
4. Verify old runs (without `log_events`) still render gracefully with "No detailed log events" message

**Step 3: Update CLAUDE.md test count if changed**

**Step 4: Commit any final tweaks**

```bash
git commit -m "chore: pipeline log panel verification and cleanup"
```
