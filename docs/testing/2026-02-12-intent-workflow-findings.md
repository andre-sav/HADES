# Intent Workflow Test Findings

**Date**: 2026-02-12
**Mode**: Manual Review, Test Mode (no credits)
**Search**: Topic "Vending Machines", Signal "High", Target 25 companies

---

## Summary

The Intent Workflow completes end-to-end (Search → Select Companies → Find Contacts → Results) without errors. The export dedup integration works correctly. However, several pre-existing UX and data issues reduce the workflow's effectiveness.

**Verdict**: Functional but has significant data quality and UX issues that predate the export dedup work.

---

## What Works Well

1. **Pipeline completes without errors** — All 4 steps execute, no Python exceptions in server logs
2. **Test Mode** — Clear "Using mock data" and "TEST MODE" banners, no credits consumed
3. **Step progression** — Stepper updates correctly (completed/current/pending states)
4. **Summary strip** — Shows mode, company count, budget clearly
5. **Export dedup integration** — Runs silently when no previously exported companies exist (correct behavior — no false banner)
6. **Company selection UX** — Select All / Select Top 25 / Clear buttons, multi-select with checkboxes, priority and freshness filters all work
7. **Results table** — Clean layout with Name, Title, Company, Score, Accuracy columns
8. **Download CSV and Full Export** — Both present and accessible
9. **API Request/Response expander** — Available for debugging, collapsed by default

---

## Issues Found

### P0 — Critical

#### 1. Duplicate contacts in radio lists
**Location**: Step 3 (Find Contacts), contact selection radio groups
**Symptom**: Metrie shows "110 contacts" but the radio list contains the same ~18 unique contacts repeated 6x. UC Riverside shows "5 contacts" but they're all the same person (Jonathan Ocab). Same for Kootenai Health (all Laurie Davis) and Southern Oregon University (all David Raco).
**Root cause**: `search_contacts_all_pages()` returns duplicates when searching by `company_ids` — the ZoomInfo API pagination returns the same contacts across pages. `build_contacts_by_company()` groups by company but does not deduplicate by `personId`.
**Impact**: Unusable contact selection — users see walls of identical radio buttons. Impossible to meaningfully choose between contacts.
**Fix**: Add `personId`-based deduplication in `build_contacts_by_company()` or in `search_contacts_all_pages()` when searching by company IDs.
**Pre-existing**: Yes, not related to export dedup changes.

### P1 — High

#### 2. No differentiation in intent scoring
**Location**: Step 2 (Select Companies)
**Symptom**: All 7 companies show identical scores: 70%, Medium priority, Cooling freshness, High signal, 12d age. The table provides zero decision-making value — every row looks the same.
**Root cause**: The intent scoring formula produces identical outputs when signal_strength and freshness are the same. With only "High" signal filter selected and all results having the same freshness, there's nothing to differentiate.
**Impact**: Users cannot make informed selections. "Select Top 25" is meaningless when all scores are tied.
**Suggestion**: Incorporate company size, SIC code match quality, or geographic factors into scoring to break ties.

#### 3. Companies metric is misleading in Results
**Location**: Step 4 (Results), metric cards
**Symptom**: Shows "Companies: 7" but only 4 companies have contacts. The 7 comes from Step 2 selections, not actual results.
**Impact**: User thinks they got results for 7 companies when 3 had zero ICP matches.
**Fix**: Show "4 companies with contacts" or "4 of 7 companies matched" in Step 4.

#### 4. Missing City/State data in Results table
**Location**: Step 4 (Results), data table
**Symptom**: City and State columns are empty for all 4 contacts.
**Root cause**: Contact Search preview data doesn't include location fields (they come from enrichment). In test mode, enrichment is skipped.
**Impact**: Users can't evaluate geographic fit. This is expected in test mode but could be confusing.
**Suggestion**: Hide City/State columns in test mode, or add a note explaining these populate after real enrichment.

### P2 — Medium

#### 5. No explanation when companies have zero contacts
**Location**: Step 3 (Find Contacts)
**Symptom**: Header says "Finding ICP-filtered contacts at **7** companies..." but result shows "125 contacts across **4** companies." The 3 companies that had zero ICP matches are silently dropped — no explanation.
**Impact**: User doesn't know why 3 companies disappeared. Were they too small? Wrong industry? No managers?
**Suggestion**: Show a "3 companies had no matching contacts" note with the filter criteria that excluded them.

#### 6. Page length / scroll fatigue
**Location**: Full page
**Symptom**: All 4 steps remain expanded on the page simultaneously. After completing Step 4, the user must scroll past Step 1 search config, Step 2 company table, and Step 3 contact selection to reach results.
**Impact**: The page becomes extremely long, especially with the Step 3 duplicate contacts bug making Metrie's radio list enormous.
**Suggestion**: Collapse completed steps automatically, or add anchor links to jump between steps.

#### 7. "Last run" indicator is stale
**Location**: Below header, before mode selector
**Symptom**: Shows "Last run: 16h ago · 7 leads · Intent" — this refers to a previous session's run, not the current search that just returned 4 leads. It updates only after the workflow completes, which can confuse users mid-workflow.
**Impact**: Minor confusion about which run is being referenced.

### P3 — Low

#### 8. "Search Companies" button still accessible after search
**Location**: Step 1 section (visible while on Step 3/4)
**Symptom**: The "Search Companies" button remains enabled and clickable even after progressing to Step 3. Clicking it would re-run the search and potentially lose all selections.
**Impact**: Low risk, but violates principle of least surprise.

#### 9. Intent signal filtering is limited
**Location**: Step 1 search config
**Symptom**: Only one topic ("Vending Machines") is available in the dropdown. Signal strength only has a few options. With "High" selected, only 7 companies returned — well below the target of 25.
**Impact**: Users may not understand that the intent data is sparse for their topic. No guidance on broadening the search (e.g., "Try adding Medium signal strength to find more companies").

---

## Export Dedup Integration Assessment

The export dedup feature (`apply_export_dedup()`) integrates correctly:
- Runs after `dedupe_leads()` in the search pipeline (line 405-411)
- Session state keys (`intent_include_exported`, `intent_dedup_result`) properly initialized
- Banner + toggle checkbox code is in place for Step 2 (lines visible in code review)
- With 0 previously exported companies, the banner correctly doesn't show
- No errors or exceptions during execution

**Cannot fully verify** the dedup banner and toggle because there are no previously exported companies in the database. This requires exporting a batch first, then re-searching. Unit tests (14 in `test_export_dedup.py`) cover this path.

---

## Test Environment

- Streamlit running locally, headless mode
- Test Mode enabled (search uses real ZoomInfo API, enrichment is skipped)
- ZoomInfo API returned real data (7 intent companies for "Vending Machines" + "High" signal)
- 376 unit tests passing
