# HADES Engineering & UX Audit Report

**Date:** 2026-02-20 | **Session:** 30 | **Codebase:** 55 .py files, 25,840 lines, 579 tests | **Scope:** Full stack

---

## D1. Executive Summary — Top 10 Issues

| # | Issue | Why It Matters | Severity |
|---|-------|----------------|----------|
| 1 | **No concurrent-run guard on headless pipeline** — two simultaneous runs double-process and double-charge ZoomInfo credits | Production credit burn with no protection; cron + manual "Run Now" can overlap | P0 |
| 2 | **No confirmation before VanillaSoft push or "Run Now"** — single misclick sends data to external CRM or triggers expensive pipeline | Irreversible actions with no undo; accidental pushes create real CRM records | P0 |
| 3 | **Step 3 of intent pipeline makes N single-contact enrich calls** — burns 1 credit per uncached company purely for ID resolution, then re-enriches same contacts in Step 5 | Up to 25 wasted credits per run; the same personId may be enriched twice | P1 |
| 4 | **`exclude_org_exported=True` is a no-op** — the field exists in `ContactQueryParams` and cache hash but is never sent to ZoomInfo API | Users believe org-exported contacts are filtered; they are not | P1 |
| 5 | **Configuration sprawl** — accuracy threshold (95), employee max (5000), management levels hardcoded in 4-7 separate locations each | A business rule change requires editing 7 files; guaranteed drift | P1 |
| 6 | **No CI test workflow** — tests run only via local pre-commit hook; no GitHub Actions on PR/push | Broken code can reach production if developer skips hook | P1 |
| 7 | **Raw exception strings rendered to UI** — `st.error(f"...{e}")` in 15+ locations can expose DB URLs, hostnames, partial tokens | Internal infrastructure details visible to authenticated users | P1 |
| 8 | **Failed pipeline run records `credits_used=0`** — both exception handlers hardcode 0 even when enrichment credits were already consumed | Audit trail is wrong; budget reporting diverges from reality | P1 |
| 9 | **Non-atomic multi-step export flow** — push-and-log in CSV Export performs 4 independent writes with no transaction wrapping | Process crash mid-flow leaves DB in inconsistent state | P1 |
| 10 | **Geography 2-click search confirmation** — requires Preview Request + Confirm & Search where Intent does it in 1 click | 30-50% more task time for the primary workflow | P1 |

---

## D2. Findings Table (35 findings)

| # | Issue | Sev | Evidence | Impact | Fix | Effort | Risk |
|---|-------|-----|----------|--------|-----|--------|------|
| 1 | No concurrent pipeline run guard | P0 | `run_intent_pipeline.py` — no lock/status check at start | Double credit spend, duplicate leads | Add `SELECT ... WHERE status='running'` check + advisory lock at pipeline start | S | Low |
| 2 | No confirmation before VanillaSoft push | P0 | `4_CSV_Export.py:376` — `st.button` fires immediately | Accidental pushes to external CRM | Add `@st.dialog` or `ui.alert_dialog` confirmation | S | Low |
| 3 | No confirmation before "Run Now" | P0 | `9_Automation.py:189` — `st.button` fires immediately | Accidental credit spend + email | Same dialog pattern | S | Low |
| 4 | `intent_leads_staged`/`geo_leads_staged` not in defaults dict | P0 | `1_Intent_Workflow.py:1409`, `2_Geography_Workflow.py:1767` | Not reset on workflow Reset; duplicate staging on second run | Add to defaults dicts with `False` value | S | Low |
| 5 | Step 3 N single-contact enrich calls for ID resolution | P1 | `run_intent_pipeline.py:186-207` — loop with `person_ids=[pid]` | 25 wasted credits per run | Batch all pids into one `enrich_contacts_batch` call | M | Low |
| 6 | `exclude_org_exported` is a no-op | P1 | `zoominfo_client.py:1268` — in cache hash but not in request body | Users think org-exported contacts are filtered | Either send to API or remove from dataclass/docs | S | Low |
| 7 | Configuration sprawl: accuracy=95 in 7 places | P1 | `icp.yaml`, `zoominfo_client.py:141`, `expand_search.py:81`, 4 page files | Business rule change requires 7 file edits | `expand_search.py` constants should read from `utils.py` config accessors | M | Low |
| 8 | No CI test workflow on PR/push | P1 | `.github/workflows/` — only `intent-poll.yml` (no test step) | Broken code reaches production | Add `test.yml` workflow triggered on push/PR | S | Low |
| 9 | Raw `{e}` in `st.error()` — 15+ locations | P1 | `app.py:42`, `pages/3_Operators.py:240`, `9_Automation.py:211`, etc. | Exposes DB URLs, hostnames | Replace with generic user message + `logger.exception()` | M | Low |
| 10 | `pipeline_runs.credits_used` hardcoded to 0 on failure | P1 | `run_intent_pipeline.py:348,351` | Audit trail wrong; budget reporting diverges | Use `summary.get("credits_used", 0)` from the accumulated summary dict | S | Low |
| 11 | Non-atomic 4-step export write flow | P1 | `4_CSV_Export.py:446-463` — 4 independent `execute_write` calls | Partial state on crash | Wrap in single transaction or use `execute_many` | M | Med |
| 12 | Geography 2-click search confirmation | P1 | `2_Geography_Workflow.py:863-924` — Preview + Confirm | +30-50% task time vs Intent | Make Preview optional/collapsed; add direct "Search" button | S | Low |
| 13 | Contact radio labels unreadable | P1 | `1_Intent_Workflow.py:1024-1031`, `2_Geography_Workflow.py:1314-1348` | Manual mode contact selection breaks on long data | Replace with structured mini-card per company | M | Low |
| 14 | `auto_run_triggered` not reset in finally block | P1 | `9_Automation.py:193-212` | Button permanently disabled after error | Wrap in `try/finally` | S | Low |
| 15 | Password gate uses `==` not `hmac.compare_digest` | P1 | `utils.py:38` | Timing-safe comparison missing | Replace with `hmac.compare_digest()` | S | Low |
| 16 | ZoomInfo JWT persisted unencrypted in DB | P1 | `zoominfo_client.py:265-275` — stored in `sync_metadata` table | DB compromise yields live API token | Encrypt token at rest or skip persistence | M | Med |
| 17 | CSS typo `font_weight` (should be `font-weight`) | P1 | `ui_components.py:2187` | Style silently not applied on badges | Fix underscore to hyphen | S | Low |
| 18 | ZoomInfo API health check doesn't verify token | P1 | `10_Pipeline_Health.py:207-216` | False-positive "Healthy" status | Add lightweight API call or label "unverified" | S | Low |
| 19 | Read-only filter group looks identical to editable group | P1 | `1_Intent_Workflow.py:318-328` | Users try to interact with static filters | Visually distinguish with different component | S | Low |
| 20 | Batch ID generated on operator change, not on export | P1 | `4_CSV_Export.py:332-349` — `_export_cache_key` includes operator ID | Phantom batch IDs in DB | Decouple batch_id from CSV render | M | Low |
| 21 | Missing index: `lead_outcomes(exported_at, company_id)` | P1 | `turso_db.py:218,754` — composite index has wrong leading column | `get_exported_company_ids` does full table scan | Add reversed index or standalone `exported_at` index | S | Low |
| 22 | `get_operators()` loads all 3,041 records on every rerun | P2 | `turso_db.py:301`, `3_Operators.py:59` | 600KB Python objects rebuilt per rerun | Add SQL-level `WHERE`/`LIMIT` for search+pagination | M | Low |
| 23 | `get_zips_in_radius` scans 42K ZIPs on every rerun | P2 | `geo.py:82-96` — brute-force haversine over all centroids | ~42ms per rerun while ZIP input visible | Cache result in session_state keyed on (zip, radius) | S | Low |
| 24 | Vacuous tests in `test_expand_search.py:82-105` | P2 | Local variables shadow imports; tests always pass | Zero coverage on default constants | Import constants from module; assert against those | S | Low |
| 25 | `test_pipeline_health.py` tests copied function, not source | P2 | Lines 21-40 copy `time_ago` verbatim into test file | Tests can't detect source implementation drift | Extract `time_ago` to importable module | S | Low |
| 26 | Zoho integration cluster (3 files) has zero tests | P2 | `zoho_auth.py`, `zoho_client.py`, `zoho_sync.py` | Live production code is completely untested | Add async test suite with mocked httpx | L | Low |
| 27 | `.env` not in `.gitignore` | P2 | `.gitignore` — only `.streamlit/secrets.toml` excluded | `.env` with credentials could be committed | Add `.env` and `*.env` to `.gitignore` | S | Low |
| 28 | XSS in `health_indicator()` — `detail` not escaped | P2 | `10_Pipeline_Health.py:76-96` — raw exception text in HTML | API error bodies with HTML rendered in browser | Apply `html.escape()` to `detail` parameter | S | Low |
| 29 | XSS in `_friendly_error()` — output not escaped | P2 | `9_Automation.py:107-112` — `error_html` uses raw string | Same vector as above | Apply `html.escape()` before HTML insertion | S | Low |
| 30 | No PII retention policy on `staged_exports` | P2 | `turso_db.py` schema — no TTL on `leads_json` | Full contact records stored indefinitely | Add cleanup job or purge `leads_json` after 90 days | M | Low |
| 31 | Dependencies unpinned with `>=` only, no lock file | P2 | `requirements.txt` — all 10 deps use `>=` | Supply chain risk; `libsql-experimental` is pre-1.0 | Pin exact versions with `pip-compile` | S | Low |
| 32 | `turso_db.py` is a god object (37 methods, 11 domains) | P2 | `turso_db.py:17` — 932 lines, single class | Hard to test in isolation; high coupling | Extract domain-specific repositories | L | Med |
| 33 | `clear_expired_cache` never called automatically | P2 | `turso_db.py:418` — exists but no scheduled invocation | Expired cache entries accumulate | Call from `init_schema()` or add to cron | S | Low |
| 34 | Expired cache not evicted; ZIP lists stored redundantly | P2 | `turso_db.py:456,525` — query_params JSON includes full ZIP list | Bloated rows in credit_usage and query_history | Store ZIP count or hash instead of full list | M | Low |
| 35 | No rate limiting on auth password attempts | P2 | `utils.py:16-44` — no lockout or delay | Brute force feasible against weak password | Add attempt counter with exponential backoff | S | Low |

---

## D3. Architecture Map

```
┌──────────────────────────────────────────────────────────────────────┐
│                        STREAMLIT UI LAYER                          │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌───────┐  │
│  │ Intent  │  │  Geo    │  │ Operators│  │  Export  │  │ Usage │  │
│  │Workflow │  │Workflow │  │  CRUD    │  │CSV+Push │  │ Dash  │  │
│  │ 1427L   │  │ 1787L   │  │  373L    │  │  521L   │  │ 333L  │  │
│  └────┬────┘  └────┬────┘  └────┬─────┘  └────┬────┘  └───┬───┘  │
│       │            │            │              │           │       │
│  ┌────┴────────────┴────────────┴──────────────┴───────────┴────┐  │
│  │              ui_components.py (2549L) — Design System        │  │
│  │   COLORS · SPACING · FONT_SIZES · metric_card · styled_table │  │
│  │   action_bar · step_indicator · score_breakdown · status_badge│  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Exec Summary 304L│  │ Automation   │  │ Pipeline Health 344L │  │
│  │ Score Cal   325L │  │    301L      │  │ (Dev: Test, API Disc)│  │
│  └──────────────────┘  └──────┬───────┘  └──────────────────────┘  │
└───────────────────────────────┼──────────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  BUSINESS LOGIC │  │   API CLIENTS    │  │   PERSISTENCE    │
│                 │  │                  │  │                  │
│ scoring.py 524L │  │ zoominfo_client  │  │ turso_db.py 932L │
│  - intent score │  │   1297L          │  │  11 tables       │
│  - geo score    │  │  - OAuth2 token  │  │  37 methods      │
│  - contact score│  │  - Contact Search│  │  - operators     │
│                 │  │  - Intent Search │  │  - cache         │
│ expand_search   │  │  - Enrich batch  │  │  - credit_usage  │
│   588L          │  │  - Pagination    │  │  - query_history │
│  - auto-expand  │  │  - Rate limiting │  │  - lead_outcomes │
│  - threading    │  │                  │  │  - staged_exports│
│                 │  │ vanillasoft_client│  │  - pipeline_runs │
│ dedup.py   365L │  │   156L           │  │                  │
│  - phone fuzzy  │  │  - XML push      │  │ geo.py 140L      │
│  - company norm │  │  - Per-lead POST │  │  - ZIP centroids │
│                 │  │                  │  │  - haversine     │
│ export.py  212L │  │ zoho_client 282L │  │  - 42K rows      │
│  - CSV format   │  │  - COQL queries  │  │                  │
│  - 31 columns   │  │  - async httpx   │  │                  │
│                 │  │                  │  │                  │
│ cost_tracker    │  │                  │  │                  │
│   330L          │  │                  │  │                  │
│  - budget caps  │  │                  │  │                  │
│  - weekly alerts│  │                  │  │                  │
└────────┬────────┘  └────────┬─────────┘  └────────┬─────────┘
         │                    │                     │
         ▼                    ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                        │
│  ┌───────────┐  ┌──────────────┐  ┌──────────┐  ┌───────┐  │
│  │ ZoomInfo  │  │ VanillaSoft  │  │  Turso   │  │ Zoho  │  │
│  │ REST API  │  │  XML Push    │  │ libsql   │  │  CRM  │  │
│  │ OAuth JWT │  │  Per-lead    │  │ Cloud DB │  │ COQL  │  │
│  └───────────┘  └──────────────┘  └──────────┘  └───────┘  │
└─────────────────────────────────────────────────────────────┘

HOT PATH (Intent Pipeline):
  UI/Cron → search_intent_all_pages → score_intent_leads
  → build_contacts_by_company (threaded) → enrich_contacts_batch
  → score_intent_contacts → dedupe_leads → filter_previously_exported
  → export_leads_to_csv → push_leads (VanillaSoft)
  → record_lead_outcomes_batch → complete_pipeline_run

HOT PATH (Geography):
  UI → get_zips_in_radius (42K scan) → search_contacts_all_pages
  → score_geography_leads → enrich_contacts_batch
  → save_staged_export → export page → push_leads
```

---

## D4. Performance Hypotheses

| Hypothesis | Evidence | How to Measure | Expected Improvement |
|------------|----------|----------------|---------------------|
| `get_zips_in_radius` is slow on every Streamlit rerun | `geo.py:82-96` — 42K haversine calls, no caching | `time.perf_counter()` around the call | Cache in `st.session_state[(zip,radius)]`; ~42ms → <1ms |
| `get_operators()` full-table load is wasteful | `turso_db.py:301` — 3,041 rows on every rerun | Profile with `cProfile` on Operators page | SQL-level `WHERE LIKE ? LIMIT 25 OFFSET ?`; 600KB → 5KB |
| Intent pipeline Step 3 burns N credits for ID resolution | `run_intent_pipeline.py:186-207` — 25 individual calls | Count API calls via logger; compare to credit_usage | Batch all pids: 25 → 1 API call, saving 24 credits |
| `get_weekly_usage_by_workflow` issues 2 queries instead of 1 | `cost_tracker.py:285-286` — sequential per workflow | Profile DB round-trips | Single `GROUP BY`: 2 → 1 DB call |
| Trends tab issues 8 cumulative queries in loop | `6_Executive_Summary.py:195-214` — 4 weeks × 2 calls | Count DB queries; measure page load | Single `strftime` grouping query |
| `staged_exports.leads_json` blobs oversized | `turso_db.py:797` — 40-60 fields per lead | `SELECT LENGTH(leads_json)` in Turso | Trim to export fields; 60-80% size reduction |

---

## D5. Technical Debt Register

### API Layer
- `exclude_org_exported` no-op (`zoominfo_client.py:1268`)
- `directPhone` in required_fields but not enrich output (`zoominfo_client.py:157-195`)
- Step 3 single-contact enrich loop (`run_intent_pipeline.py:186-207`)
- No VanillaSoft retry (`vanillasoft_client.py:105-134`)

### DB Layer
- God object: 37 methods, 11 domains (`turso_db.py`)
- Missing indexes: `lead_outcomes.exported_at`, `query_history.workflow_type`
- Non-idempotent inserts rely on caller-side guards
- No transaction boundaries on multi-step export
- No cache eviction scheduled

### Scoring
- `import re` inside except blocks (`scoring.py:163,365`)
- Minor structural duplication across 3 scoring functions

### UI
- CSS typo `font_weight` → `font-weight` (`ui_components.py:2187`)
- Double `@st.cache_resource` wrapping suppresses TTL
- Orphaned session state keys: `intent_state_filter`, `_dedup_overrides`
- `st.cache_resource.clear()` clears all caches globally

### Testing
- Vacuous tests (`test_expand_search.py:82-105`)
- Copied function test (`test_pipeline_health.py:21-40`)
- No `conftest.py` for shared fixtures
- Zero coverage on Zoho cluster (3 files)

### Configuration
- 7 sources of truth for accuracy=95
- `expand_search.py` constants not reading from config

---

## D6. UI/UX Critique (Per-Page)

### Homepage (app.py)
- **P0**: Quick-action cards not clickable; separate button below
- **P2**: "Recent Runs" header renders even when empty

### Intent Workflow
- **P1**: No "Jump to Results" after enrichment; user must scroll
- **P1**: Read-only filters look identical to editable filters
- **P1**: Contact radio labels unreadable (6+ concatenated fields)
- **P1**: API errors show no Retry button
- **P2**: Filter dropdowns have collapsed labels
- **P2**: Step numbers mismatch on mode switch mid-workflow

### Geography Workflow
- **P1**: 2-click search (Preview → Confirm) is unnecessary friction
- **P1**: Contact radio labels same unreadable pattern
- **P2**: Welcome banner breaks visual flow
- **P2**: Export dedup banner shown twice
- **P2**: Step header styles inconsistent

### Operators
- **P1**: "..." toggle expands inline, shifting all rows
- **P2**: Save/Cancel button order reversed
- **P2**: Zoho sync expander provides no value when unconfigured

### CSV Export
- **P0**: VanillaSoft Push has no confirmation dialog
- **P1**: Batch ID regenerated on operator change
- **P1**: Failed push retry UI disappears on reload

### Automation
- **P0**: "Run Now" has no confirmation
- **P1**: Error leaves button permanently disabled
- **P2**: Run history capped at 10, no "show more"

### Pipeline Health
- **P1**: ZoomInfo health check doesn't verify token
- **P2**: Two separate tables confuse sales users
- **P2**: No refresh timestamp

---

## D7. Roadmap

### Quick Wins (1 day each)
1. Add confirmation dialogs to Push and Run Now
2. Fix CSS typo `font_weight` → `font-weight`
3. Add `.env` to `.gitignore`
4. Fix `pipeline_runs.credits_used` on failure
5. Add `intent_leads_staged`/`geo_leads_staged` to defaults dicts
6. Fix vacuous tests in `test_expand_search.py`
7. Add `try/finally` to `auto_run_triggered`
8. HTML-escape `detail` in `health_indicator()` and `_friendly_error()`

### 1 Week
1. Batch Step 3 ID resolution (saves ~24 credits/run)
2. Add GitHub Actions test workflow + linting
3. Centralize configuration (reduce 7 sources to 1)
4. Add concurrent-run guard on pipeline
5. Simplify Geography search flow (1-click search)

### 1 Month
1. Split `turso_db.py` into repository modules
2. Replace contact radio labels with structured cards
3. Add Zoho tests + pin all dependencies

---

## D8. If You Can Only Fix 3 Things

### 1. Add confirmation dialogs to Push and Run Now (2 hours)
Maximum user protection per line of code. Eliminates the highest-severity UX risk — irreversible external side effects from a single misclick.

### 2. Add concurrent-run guard + fix credits_used on failure (4 hours)
Prevents real dollar waste (ZoomInfo credits are a capped resource). Fixes audit trail reliability. The headless pipeline is the most credit-sensitive code path.

### 3. Batch Step 3 ID resolution + remove `exclude_org_exported` lie (3 hours)
Direct cost savings (~24 credits/run) + trust restoration. Removes a documented feature that silently does nothing.

---

*Generated by comprehensive audit across 6 parallel analysis agents. Every finding references specific file:line evidence.*
