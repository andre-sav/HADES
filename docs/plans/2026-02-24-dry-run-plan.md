# Dry-Run for Automation Run Now — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "Dry Run" button to the Automation page that runs intent search + scoring without consuming credits, showing a preview of what a full pipeline run would produce.

**Architecture:** Refactor the existing `dry_run` early-exit in `run_pipeline()` to execute Steps 1-2 (intent search + score + dedup) before returning. Add a "Dry Run" button to the Automation page that calls `run_pipeline(dry_run=True)` and renders the preview inline.

**Tech Stack:** Python, Streamlit, existing HADES modules (scoring, dedup, export_dedup, ZoomInfoClient)

---

### Task 1: Backend — Move dry_run exit to after scoring

**Files:**
- Modify: `scripts/run_intent_pipeline.py:85-88` (dry_run branch)
- Modify: `scripts/run_intent_pipeline.py:69-83` (summary dict — add `top_companies`)

**Step 1: Write the failing tests**

Add three tests to `tests/test_run_intent_pipeline.py` inside the existing `TestDryRun` class (after line 173):

```python
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_dry_run_returns_real_counts(self, MockClient):
        """Dry run should execute intent search + scoring and return real numbers."""
        config = _make_config(target_companies=2)
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
            _make_intent_lead("c2", "Beta Inc"),
            _make_intent_lead("c3", "Gamma LLC"),
        ]

        result = run_pipeline(config, creds, dry_run=True)

        assert result["success"] is True
        assert result["csv_content"] is None
        assert result["batch_id"] is None
        # Real counts from intent search + scoring
        assert result["summary"]["intent_results"] == 3
        assert result["summary"]["scored_results"] > 0
        assert result["summary"]["companies_selected"] <= 2  # capped at target
        # Top companies populated
        assert isinstance(result["summary"]["top_companies"], list)
        assert len(result["summary"]["top_companies"]) > 0
        assert "companyName" in result["summary"]["top_companies"][0]

    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_dry_run_does_not_call_contacts_or_enrich(self, MockClient):
        """Dry run must NOT call contact search, enrich, or export."""
        config = _make_config()
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
        ]

        run_pipeline(config, creds, dry_run=True)

        # Intent search SHOULD be called
        client.search_intent_all_pages.assert_called_once()
        # These should NOT be called
        client.search_contacts_all_pages.assert_not_called()
        client.enrich_contacts_batch.assert_not_called()

    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_dry_run_does_not_log_pipeline_run(self, MockClient):
        """Dry run must NOT create a pipeline run record in the DB."""
        config = _make_config()
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
        ]

        # Provide a mock DB to verify it's not called
        mock_db = MagicMock()
        result = run_pipeline(config, creds, dry_run=True, db=mock_db)

        assert result["success"] is True
        mock_db.start_pipeline_run.assert_not_called()
        mock_db.complete_pipeline_run.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_intent_pipeline.py::TestDryRun -v`
Expected: 1 existing test passes, 3 new tests FAIL (dry_run returns zeroes, no `top_companies` key)

**Step 3: Implement the backend change**

In `scripts/run_intent_pipeline.py`:

1. Add `"top_companies": []` to the summary dict (line 82, after `"top_leads": []`).

2. Replace the dry_run stub (lines 85-88) with:

```python
    if dry_run:
        logger.info("Dry run — running intent search + scoring (no credits consumed)")

        client = ZoomInfoClient(
            client_id=creds["ZOOMINFO_CLIENT_ID"],
            client_secret=creds["ZOOMINFO_CLIENT_SECRET"],
        )

        # Step 1: Intent Search (free)
        intent_params = IntentQueryParams(
            topics=config["topics"],
            signal_strengths=config["signal_strengths"],
            sic_codes=get_sic_codes(),
            employee_min=get_employee_minimum(),
        )
        intent_results = client.search_intent_all_pages(intent_params, max_pages=10)
        summary["intent_results"] = len(intent_results)

        if not intent_results:
            return {"success": True, "csv_content": None, "csv_filename": None,
                    "batch_id": None, "summary": summary, "error": None}

        # Step 2: Score + dedup
        scored_leads = score_intent_leads(intent_results)
        scored_leads, _ = dedupe_leads(scored_leads)
        summary["scored_results"] = len(scored_leads)

        # Cross-session dedup
        if db is not None:
            dedup_days = config.get("dedup_days_back", 180)
            lookup = get_previously_exported(db, days_back=dedup_days)
            new_leads, filtered_leads = filter_previously_exported(scored_leads, lookup)
            summary["dedup_filtered"] = len(filtered_leads)
        else:
            new_leads = scored_leads

        # Select top N
        target = config["target_companies"]
        selected = new_leads[:target]
        summary["companies_selected"] = len(selected)

        # Top companies for preview
        summary["top_companies"] = [
            {
                "companyName": lead.get("companyName", ""),
                "companyId": str(lead.get("companyId", "")),
                "_score": lead.get("_score", 0),
                "_priority": lead.get("_priority", ""),
                "intentTopic": lead.get("intentTopic", ""),
                "intentStrength": lead.get("intentStrength", ""),
            }
            for lead in selected
        ]

        return {"success": True, "csv_content": None, "csv_filename": None,
                "batch_id": None, "summary": summary, "error": None}
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_intent_pipeline.py::TestDryRun -v`
Expected: All 4 tests PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: 704+ tests pass (existing test_dry_run_no_api_calls still passes since it doesn't mock ZoomInfoClient — but now it will try to instantiate one. We need to also patch it in the existing test.)

**Step 6: Fix the existing dry-run test**

The existing `test_dry_run_no_api_calls` (line 166) doesn't mock `ZoomInfoClient`, so it will fail now that dry_run actually creates one. Add the mock:

```python
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_dry_run_no_api_calls(self, MockClient):
        config = _make_config()
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = []

        result = run_pipeline(config, creds, dry_run=True)

        assert result["success"] is True
        assert result["csv_content"] is None
        assert result["batch_id"] is None
```

**Step 7: Run full test suite again**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass

**Step 8: Commit**

```bash
git add scripts/run_intent_pipeline.py tests/test_run_intent_pipeline.py
git commit -m "feat: dry-run executes intent search + scoring (HADES-epj)"
```

---

### Task 2: Frontend — Add Dry Run button and inline results

**Files:**
- Modify: `pages/10_Automation.py:204-248` (Run Now section)

**Step 1: Add the Dry Run button next to Run Now**

Replace the current two-column layout (lines 210-219) with a three-column layout:

```python
now_col1, now_col2, now_col3 = st.columns([5, 1, 1])
with now_col1:
    st.markdown(
        f"Search **{', '.join(topics)}** intent signals, select top **{target}** "
        f"companies, find contacts, enrich, and email CSV."
    )
with now_col2:
    dry_run = st.button(
        "Dry Run", use_container_width=True, key="auto_dry_run",
    )
with now_col3:
    run_now = st.button(
        "Run Now", type="primary", use_container_width=True, key="auto_run_now",
    )
```

**Step 2: Add dry-run execution logic**

After the button layout, before the dialog open (before line 222), add:

```python
# Execute dry run
if dry_run:
    try:
        with st.spinner("Running preview..."):
            from scripts.run_intent_pipeline import run_pipeline
            from scripts._credentials import load_credentials

            creds = load_credentials()
            result = run_pipeline(auto_config, creds, dry_run=True, db=db)

            if result["success"]:
                st.session_state["dry_run_result"] = result["summary"]
            else:
                st.error(f"Preview failed: {result.get('error', 'Unknown error')}")
    except Exception as e:
        logger.error(f"Dry run error: {e}")
        st.error("Preview failed. Please try again or check the logs.")
    st.rerun()
```

**Step 3: Add inline results rendering**

After the dry-run execution block, render results if they exist:

```python
# Render dry-run preview
if "dry_run_result" in st.session_state:
    preview = st.session_state["dry_run_result"]

    st.markdown("")
    st.markdown(
        f'<div style="background:{COLORS["bg_secondary"]};border:1px solid {COLORS["border"]};'
        f'border-radius:10px;padding:{SPACING["md"]};">',
        unsafe_allow_html=True,
    )

    st.markdown("**Preview Results**")

    p1, p2, p3, p4 = st.columns(4)
    with p1:
        metric_card("Intent Results", preview.get("intent_results", 0))
    with p2:
        metric_card("Scored (non-stale)", preview.get("scored_results", 0))
    with p3:
        metric_card("After Dedup", preview.get("scored_results", 0) - preview.get("dedup_filtered", 0))
    with p4:
        metric_card("Would Select", preview.get("companies_selected", 0))

    # Estimated credits
    est_credits = preview.get("companies_selected", 0)
    remaining = weekly_cap - weekly_used
    if est_credits > 0:
        credit_color = COLORS["error_light"] if est_credits > remaining else COLORS["text_muted"]
        st.markdown(
            f'<div style="color:{credit_color};font-size:{FONT_SIZES["sm"]};margin-top:{SPACING["xs"]};">'
            f'Estimated credits: ~{est_credits} of {remaining:,} remaining'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Top companies table
    top_cos = preview.get("top_companies", [])
    if top_cos:
        st.markdown(f"**Top {len(top_cos)} Companies**")
        header = (
            f'<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:{SPACING["xs"]};'
            f'padding:{SPACING["xs"]} 0;border-bottom:1px solid {COLORS["border"]};'
            f'color:{COLORS["text_muted"]};font-size:{FONT_SIZES["xs"]};">'
            f'<div>Company</div><div>Score</div><div>Topic</div><div>Strength</div></div>'
        )
        rows = "".join(
            f'<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:{SPACING["xs"]};'
            f'padding:{SPACING["xs"]} 0;border-bottom:1px solid {COLORS["border"]}40;'
            f'font-size:{FONT_SIZES["sm"]};">'
            f'<div style="color:{COLORS["text_primary"]};">{html.escape(co.get("companyName", ""))}</div>'
            f'<div style="color:{COLORS["text_primary"]};font-family:\'IBM Plex Mono\',monospace;">'
            f'{co.get("_score", 0)}</div>'
            f'<div style="color:{COLORS["text_muted"]};">{html.escape(co.get("intentTopic", ""))}</div>'
            f'<div>{status_badge("success" if co.get("intentStrength") == "High" else "warning", co.get("intentStrength", ""))}</div>'
            f'</div>'
            for co in top_cos[:5]
        )
        st.markdown(header + rows, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Action buttons
    act1, act2, _ = st.columns([1, 1, 4])
    with act1:
        if st.button("Run Full Pipeline", type="primary", key="dry_run_proceed"):
            del st.session_state["dry_run_result"]
            confirm_run_now_dialog(topics, target)
    with act2:
        if st.button("Dismiss", key="dry_run_dismiss"):
            del st.session_state["dry_run_result"]
            st.rerun()
```

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass (UI code is not unit tested, but must not break imports)

**Step 5: Commit**

```bash
git add pages/10_Automation.py
git commit -m "feat: add Dry Run button with inline preview (HADES-epj)"
```

---

### Task 3: Final verification and bead closure

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass

**Step 2: Verify CLI dry-run still works**

Run: `python scripts/run_intent_pipeline.py --dry-run --verbose 2>&1 | head -5`
Expected: Shows "Dry run — running intent search + scoring" log line (will fail on creds in CI, but validates the code path is reached)

**Step 3: Close bead**

```bash
bd update HADES-epj --status=in_progress
bd close HADES-epj
bd sync
```

**Step 4: Final commit if any remaining changes**

```bash
git add -A && git commit -m "chore: close HADES-epj dry-run feature"
```
