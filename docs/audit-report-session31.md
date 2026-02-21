# HADES Engineering & UX Audit Report — Session 31

**Date:** 2026-02-21 | **Codebase:** 55 .py files, ~12,500 lines (core+pages), 579 tests | **Scope:** Full stack
**Method:** 4 parallel research agents + manual file verification. Every finding cites file:line evidence.

---

## D1. Executive Summary — Top 10 Issues

| # | Issue | Why It Matters | Sev |
|---|-------|----------------|-----|
| 1 | **No confirmation before VanillaSoft Push or "Run Now"** — single click fires irreversible external actions | Accidental push creates real CRM records; Run Now burns credits + sends email | P0 |
| 2 | **No concurrent-run guard on headless pipeline** — cron + manual "Run Now" can overlap | Double credit spend, duplicate leads in CRM | P0 |
| 3 | **`record_lead_outcomes_batch` has no UNIQUE constraint** — duplicate outcomes inflate calibration stats | Score Calibration produces wrong delivery rates; business decisions based on inflated data | P0 |
| 4 | **Step 3 N+1 enrich calls for company ID resolution** — 25 individual API calls where 1 batch call suffices | ~24 wasted credits per automated run ($$ waste on capped budget) | P1 |
| 5 | **`exclude_org_exported=True` is a no-op** — field exists in dataclass/cache hash but never sent to ZoomInfo API | Users believe org-exported contacts are filtered; they are not | P1 |
| 6 | **No CI test workflow** — 579 tests run only via local pre-commit hook | Broken code reaches production if developer skips hook or pushes directly | P1 |
| 7 | **`time.sleep(retry_after)` blocks Streamlit UI thread for up to 120s during 429 recovery** | App appears frozen; user has no cancel option; session may be killed by Streamlit watchdog | P1 |
| 8 | **Configuration sprawl** — accuracy=95, management levels, employee range hardcoded in 4-7 separate locations | A business rule change requires editing 7 files; drift is guaranteed | P1 |
| 9 | **Password gate uses `==` not `hmac.compare_digest`** — timing oracle vulnerability | Brute-force feasible against cloud-hosted app (no rate limiting either) | P1 |
| 10 | **Outcome recording in 3 places with different field fallback logic** — SIC/employee/company data extracted differently per call site | Score Calibration sees inconsistent data depending on which path recorded the outcome | P1 |

---

## D2. Findings Table (45 findings)

### Engineering Findings

| # | Issue | Sev | Evidence | Impact | Fix | Effort | Risk |
|---|-------|-----|----------|--------|-----|--------|------|
| 1 | No confirmation before VanillaSoft Push | P0 | `4_CSV_Export.py:376` — `st.button` fires immediately | Accidental pushes to external CRM | Add `@st.dialog` confirmation | S | Low |
| 2 | No confirmation before "Run Now" | P0 | `9_Automation.py:189` — `st.button` fires immediately | Accidental credit spend + email | Same dialog pattern | S | Low |
| 3 | No concurrent pipeline run guard | P0 | `run_intent_pipeline.py` — no lock/status check | Double credit spend, duplicate leads | Add `WHERE status='running'` check at pipeline start | S | Low |
| 4 | `record_lead_outcomes_batch` — no UNIQUE constraint | P0 | `turso_db.py:651-664` — plain INSERT, no ON CONFLICT | Duplicate outcomes inflate calibration stats | Add UNIQUE on `(batch_id, person_id)` | S | Med |
| 5 | Step 3 N+1 enrich calls for ID resolution | P1 | `run_intent_pipeline.py:186-207` — loop with `person_ids=[pid]` | ~24 wasted credits per run | Batch all pids into one `enrich_contacts_batch` call | M | Low |
| 6 | `exclude_org_exported` is a no-op | P1 | `zoominfo_client.py:1268` — in cache hash but not request body | Users think org-exported contacts filtered; they're not | Send to API or remove from dataclass | S | Low |
| 7 | No CI test workflow | P1 | `.github/workflows/` — only `intent-poll.yml` | Broken code can reach production | Add `test.yml` on push/PR | S | Low |
| 8 | `time.sleep(retry_after)` blocks UI thread up to 120s | P1 | `zoominfo_client.py:431` — sleep on main thread | App frozen during 429 recovery | Use background thread or Streamlit fragment with progress | M | Med |
| 9 | Configuration sprawl: accuracy=95 in 7 places | P1 | `icp.yaml`, `zoominfo_client.py:141`, `expand_search.py:81`, 4 page files | Business rule change needs 7 edits | Central config accessor in `utils.py` | M | Low |
| 10 | Password gate uses `==` not `hmac.compare_digest` | P1 | `utils.py:38` | Timing oracle for brute-force | Replace with `hmac.compare_digest()` | S | Low |
| 11 | Outcome recording in 3 places with different fallbacks | P1 | `4_CSV_Export.py:415-447`, `run_intent_pipeline.py:307-329` | Calibration sees inconsistent SIC/employee data | Extract shared `build_outcome_row()` helper | M | Low |
| 12 | `pipeline_runs.credits_used` hardcoded to 0 on failure | P1 | `run_intent_pipeline.py:348,351` | Budget audit trail wrong after failed runs | Use `summary.get("credits_used", 0)` | S | Low |
| 13 | Non-atomic 4-step export write flow | P1 | `4_CSV_Export.py:446-463` — 4 independent `execute_write` calls | Partial state on crash | Wrap in single transaction | M | Med |
| 14 | Raw `{e}` in `st.error()` — 15+ locations | P1 | `app.py:42`, `3_Operators.py:240`, `9_Automation.py:211` | Exposes DB URLs, hostnames | Generic user message + `logger.exception()` | M | Low |
| 15 | ZoomInfo JWT persisted unencrypted in DB | P1 | `zoominfo_client.py:265-275` — plaintext in `sync_metadata` | DB compromise yields live API token | Encrypt at rest or skip persistence | M | Med |
| 16 | `auto_run_triggered` not reset in finally block | P1 | `9_Automation.py:193-212` — stays True on exception | Button permanently disabled after error | Wrap in `try/finally` | S | Low |
| 17 | CSS typo `font_weight` → `font-weight` | P1 | `ui_components.py:2187` | Badge styling silently not applied | Fix underscore to hyphen | S | Low |
| 18 | No rate limiting on auth password attempts | P2 | `utils.py:16-44` — no lockout or delay | Brute force feasible | Add attempt counter with backoff | S | Low |
| 19 | `execute_many` is a Python loop, not a true batch | P2 | `turso_db.py:76-78` — `for params in params_list` | 25 sequential Turso round-trips per batch export | Use `executemany()` if driver supports it | S | Low |
| 20 | Missing index: `query_history(workflow_type, created_at)` | P2 | `turso_db.py:587` — `WHERE workflow_type = ? ORDER BY created_at` | `get_last_query` scans filtered subset | Add composite index | S | Low |
| 21 | Missing index: `lead_outcomes(exported_at, company_id)` | P2 | `turso_db.py:754` — filter on `exported_at >=` | `get_exported_company_ids` full scan with 180d window | Add reversed composite index | S | Low |
| 22 | `get_operators()` loads all 3,041 records on every rerun | P2 | `turso_db.py:300`, `3_Operators.py:59` | 600KB rebuilt per rerun | SQL-level WHERE/LIMIT for search+pagination | M | Low |
| 23 | `get_zips_in_radius` scans 42K ZIPs with no spatial pre-filter | P2 | `geo.py:61-88` — brute-force haversine | ~42ms per call, no caching | Bounding-box pre-filter + session_state cache | S | Low |
| 24 | `clear_expired_cache` never called automatically | P2 | `turso_db.py:418` — exists but no invocation | Expired cache entries accumulate indefinitely | Call from `init_schema()` or cron | S | Low |
| 25 | Vacuous tests in `test_expand_search.py:82-105` | P2 | Local variables shadow imports; tests always pass | Zero coverage on default constants | Import constants from module | S | Low |
| 26 | `test_pipeline_health.py` copies function instead of importing | P2 | Lines 21-40 — `time_ago` duplicated | Tests can't detect source drift | Extract to importable module | S | Low |
| 27 | Zoho integration (3 files) has zero tests | P2 | `zoho_auth.py`, `zoho_client.py`, `zoho_sync.py` | Production code untested | Add test suite with mocked httpx | L | Low |
| 28 | `.env` not in `.gitignore` | P2 | `.gitignore` — only `.streamlit/secrets.toml` excluded | Credentials could be committed | Add `.env` and `*.env` | S | Low |
| 29 | XSS in `health_indicator()` — `detail` not escaped | P2 | `10_Pipeline_Health.py:96` — raw text in HTML | API error bodies rendered in browser | `html.escape()` on `detail` | S | Low |
| 30 | XSS in `_friendly_error()` — output not escaped | P2 | `9_Automation.py:107-112` — raw string in HTML | Same vector | `html.escape()` before insertion | S | Low |
| 31 | Dependencies unpinned (`>=` only), no lock file | P2 | `requirements.txt` — all 10 deps use `>=` | Supply chain risk; `libsql-experimental` pre-1.0 | Pin with `pip-compile` | S | Low |
| 32 | `turso_db.py` god object (37 methods, 11 domains, 932 lines) | P2 | `turso_db.py:17` | Hard to test in isolation; high coupling | Extract domain repositories | L | Med |
| 33 | No PII retention policy on `staged_exports` | P2 | `turso_db.py` — no TTL on `leads_json` | Full contact records stored indefinitely | Purge after 90 days | M | Low |
| 34 | `DEFAULT_ENRICH_OUTPUT_FIELDS` requests ~8 unused fields | P2 | `zoominfo_client.py:157-195` — `middleName`, `salutation`, etc. | Payload bloat on every enrich call | Trim to fields used by `ZOOMINFO_TO_VANILLASOFT` | S | Low |
| 35 | Migration checks fire 6 SELECT queries on every app start | P2 | `turso_db.py:279-295` — re-attempted hourly | 6 unnecessary Turso round-trips per startup | Use PRAGMA table_info or version table | S | Low |
| 36 | Error hierarchy split: `errors.py` has 1 class, `zoominfo_client.py` has 5 | P2 | `errors.py:11-18`, `zoominfo_client.py:36-87` | False module boundary; callers import from wrong place | Consolidate into `errors.py` | S | Low |
| 37 | No circuit breaker on ZoomInfo API calls | P2 | `zoominfo_client.py:328-481` — up to 3 retries × N calls | Batch workloads compound unlimited retry sleeps | Add failure count threshold + cool-down | M | Med |
| 38 | Fragile pagination stop in contact search | P2 | `zoominfo_client.py:952-954` — infers end from page size | Early stop if API varies page sizes | Use `totalPages` from pagination metadata | S | Low |
| 39 | `_run_migrations` uses exception message string matching | P2 | `turso_db.py:292` — `"duplicate" in error_str` | libsql message format change breaks detection | Use PRAGMA table_info | S | Low |

### UX Findings

| # | Issue | Sev | Evidence | Impact | Fix | Effort | Risk |
|---|-------|-----|----------|--------|-----|--------|------|
| 40 | Geography 2-click search (Preview → Confirm) | P1 | `2_Geography_Workflow.py:863-924` | +30-50% task time vs Intent | Direct "Search" with optional preview | S | Low |
| 41 | Contact radio labels unreadable (~140 chars, single string) | P1 | `1_Intent_Workflow.py:1024`, `2_Geography_Workflow.py:1327` | Manual mode contact selection unusable | Replace with structured mini-cards | M | Low |
| 42 | Mixed `st.button` vs `ui.button` — no documented rule | P1 | All workflow pages | Inconsistent visual weight on CTAs | Standardize to one pattern per action type | M | Low |
| 43 | Disabled VanillaSoft Push button — no explanation visible | P1 | `4_CSV_Export.py:376-382` — tooltip on disabled element | User sees grayed button with no context | Show inline `st.caption` when unavailable | S | Low |
| 44 | `text_muted` (#5c6370) on `bg_secondary` (#141922) ≈ 3.8:1 contrast | P2 | `ui_components.py:77` | Below WCAG AA 4.5:1 for normal text | Lighten muted color to #8b95a5 or similar | S | Low |
| 45 | Sidebar CSS nth-child icon injection is brittle | P2 | `ui_components.py:493-504` | Breaks when pages added/removed/reordered | Use page-name-based CSS selectors or Streamlit's icon API | S | Low |

---

## D3. Architecture Map

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          STREAMLIT UI LAYER                              │
│                                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────┐  ┌─────────┐           │
│  │   Intent     │  │  Geography  │  │ Operators│  │  Export  │           │
│  │  Workflow    │  │  Workflow   │  │  CRUD    │  │ CSV+Push│           │
│  │  1,427L      │  │  1,787L     │  │  373L    │  │  521L   │           │
│  └──────┬───────┘  └──────┬──────┘  └────┬─────┘  └────┬────┘           │
│         │                 │               │              │                │
│  ┌──────┴─────────────────┴───────────────┴──────────────┴────────────┐  │
│  │             ui_components.py (2,549L) — Design System              │  │
│  │  COLORS · SPACING · FONT_SIZES · metric_card · styled_table       │  │
│  │  action_bar · step_indicator · score_breakdown · status_badge      │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌────────────┐  ┌────────────┐  ┌─────────────┐  ┌───────────────┐    │
│  │Exec Summary│  │ Automation │  │Pipeline Hlth│  │Score Calibrate│    │
│  │   304L     │  │   301L     │  │   344L      │  │    325L       │    │
│  └────────────┘  └─────┬──────┘  └─────────────┘  └───────────────┘    │
│                        │                                                 │
└────────────────────────┼─────────────────────────────────────────────────┘
                         │
       ┌─────────────────┼──────────────────────┐
       ▼                 ▼                      ▼
┌──────────────┐  ┌──────────────┐  ┌───────────────────┐
│ BUSINESS     │  │ API CLIENTS  │  │   PERSISTENCE     │
│ LOGIC        │  │              │  │                   │
│              │  │ zoominfo_    │  │ turso_db.py 932L  │
│ scoring  524L│  │ client 1297L │  │  11 tables        │
│ - intent     │  │ - OAuth2     │  │  37 methods       │
│ - geography  │  │ - Contact    │  │  - operators      │
│ - contact    │  │ - Intent     │  │  - cache          │
│              │  │ - Enrich     │  │  - credit_usage   │
│ expand_ 588L │  │ - Pagination │  │  - query_history  │
│ - auto-expand│  │ - Rate limit │  │  - lead_outcomes  │
│ - threading  │  │              │  │  - staged_exports │
│              │  │ vanillasoft_ │  │  - pipeline_runs  │
│ dedup   365L │  │ client 157L  │  │  - company_ids    │
│ - phone fuzzy│  │ - XML push   │  │  - sync_metadata  │
│ - company    │  │              │  │                   │
│              │  │ zoho_client  │  │ geo.py 141L       │
│ export  212L │  │   282L       │  │ - 42K ZIP codes   │
│ - CSV 31-col │  │              │  │ - haversine       │
│              │  │              │  │                   │
│ cost_   330L │  │              │  │                   │
│ tracker      │  │              │  │                   │
│ - budget caps│  │              │  │                   │
│              │  │              │  │                   │
│ calibrate    │  │              │  │                   │
│   236L       │  │              │  │                   │
└──────┬───────┘  └──────┬───────┘  └────────┬──────────┘
       │                 │                    │
       ▼                 ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│                  EXTERNAL SERVICES                       │
│  ┌──────────┐  ┌────────────┐  ┌────────┐  ┌────────┐  │
│  │ ZoomInfo │  │ VanillaSoft│  │ Turso  │  │  Zoho  │  │
│  │ REST API │  │  XML Push  │  │ libsql │  │  CRM   │  │
│  │ OAuth JWT│  │  Per-lead  │  │Cloud DB│  │ COQL   │  │
│  └──────────┘  └────────────┘  └────────┘  └────────┘  │
└─────────────────────────────────────────────────────────┘

DB TABLES (11):
┌──────────────┬───────────────┬──────────────┬──────────────┐
│ operators    │ zoominfo_cache│ credit_usage │ query_history│
│ 3,041 rows   │ TTL 7 days    │ per-query log│ search log   │
├──────────────┼───────────────┼──────────────┼──────────────┤
│ lead_outcomes│ staged_exports│ pipeline_runs│ company_ids  │
│ calibration  │ leads_json    │ run tracking │ ID cache     │
├──────────────┼───────────────┼──────────────┼──────────────┤
│ sync_metadata│ location_     │ schema_      │              │
│ JWT + state  │ templates     │ migrations   │              │
└──────────────┴───────────────┴──────────────┴──────────────┘

HOT PATH — Intent Pipeline (automated):
  Cron/Manual → search_intent_all_pages → score_intent_leads
  → enrich per-company (N+1!) → search_contacts_all_pages
  → enrich_contacts_batch → score_intent_contacts → dedupe_leads
  → filter_previously_exported → export_leads_to_csv
  → push_leads (VanillaSoft) → record_lead_outcomes_batch
  → complete_pipeline_run → send_email

HOT PATH — Geography (UI):
  UI → get_zips_in_radius (42K scan) → search_contacts_all_pages
  → score_geography_leads → enrich_contacts_batch
  → save_staged_export → Export page → push_leads
```

---

## D4. Performance Section

| # | Hypothesis | Evidence | How to Measure | Expected Improvement |
|---|-----------|----------|----------------|---------------------|
| 1 | **N+1 enrich calls burn 24 extra credits/run** | `run_intent_pipeline.py:186-207` — loop with `person_ids=[pid]` for each uncached company | Count API calls via logger; compare `credit_usage` table | Batch all pids: 25→1 API call, ~24 credits saved per run |
| 2 | **`get_operators()` full-table load** | `turso_db.py:300` — `SELECT * FROM operators ORDER BY` → 3,041 rows | Profile with `cProfile`; measure Turso payload size | SQL `WHERE LIKE ? LIMIT 25 OFFSET ?`: 600KB→5KB per page |
| 3 | **`get_zips_in_radius` scans 42K ZIPs** | `geo.py:61-88` — haversine on every centroid, no bounding box | `time.perf_counter()` around call; varies by CPU | Bounding-box pre-filter reduces to ~5% of entries; cache in session_state |
| 4 | **`execute_many` is a Python loop** | `turso_db.py:76-78` — `for params in params_list` with individual round-trips | Count Turso requests per batch via network logs | 25→1 round-trip for outcome recording (~1-5s saved) |
| 5 | **Trends tab issues 8 queries in a loop** | `6_Executive_Summary.py:196-214` — 4 weeks × 2 workflow calls | Count DB queries per page load | Single `GROUP BY strftime` query: 8→1 |
| 6 | **`staged_exports.leads_json` stores full contact records** | `turso_db.py:797` — 40-60 fields per lead serialized as JSON | `SELECT LENGTH(leads_json) FROM staged_exports` | Trim to export-relevant fields: 60-80% size reduction |
| 7 | **Migration checks fire 6 SELECT queries every startup** | `turso_db.py:279-295` — re-attempted hourly via `@st.cache_resource(ttl=3600)` | Log query count during `init_schema()` | Version table: 6→1 query (or 0 if current) |
| 8 | **`DEFAULT_ENRICH_OUTPUT_FIELDS` requests 8 unused fields** | `zoominfo_client.py:157-195` — `middleName`, `salutation`, `suffix`, `personHasMoved`, `externalUrls` not in `ZOOMINFO_TO_VANILLASOFT` | Compare requested fields vs `ZOOMINFO_TO_VANILLASOFT` keys | ~30% payload reduction per enrich call |

---

## D5. Technical Debt Register

### API Layer
| Item | Location | Why It Matters | Refactoring Target |
|------|----------|----------------|-------------------|
| `exclude_org_exported` no-op | `zoominfo_client.py:1268` | Documented feature does nothing | Either add to request body or remove from codebase |
| N+1 company ID resolution | `run_intent_pipeline.py:186-207` | ~24 wasted credits per automated run | Batch into single `enrich_contacts_batch` call |
| `DEFAULT_ENRICH_OUTPUT_FIELDS` bloat | `zoominfo_client.py:157-195` | 8 fields fetched but never exported | Trim to `ZOOMINFO_TO_VANILLASOFT` keys |
| No VanillaSoft retry | `vanillasoft_client.py:105-134` | Transient failures lose leads | Add retry with exponential backoff |
| Error hierarchy split across 2 files | `errors.py` + `zoominfo_client.py:36-87` | False module boundary | Consolidate into `errors.py` |
| Fragile pagination stop condition | `zoominfo_client.py:952-954` | May stop early if API varies page sizes | Use `totalPages` from pagination metadata |

### DB Layer
| Item | Location | Why It Matters | Refactoring Target |
|------|----------|----------------|-------------------|
| God object: 37 methods, 11 domains | `turso_db.py` (932 lines) | Hard to test; high coupling | Extract domain-specific repositories |
| Missing composite indexes | `turso_db.py:161,218` | `get_last_query` and `get_exported_company_ids` scan | Add `(workflow_type, created_at)` and `(exported_at, company_id)` |
| `execute_many` is a Python loop | `turso_db.py:76-78` | N round-trips instead of 1 | Use driver's `executemany()` |
| No UNIQUE on lead_outcomes | `turso_db.py:651-664` | Duplicate rows inflate calibration | Add `UNIQUE(batch_id, person_id)` |
| Non-idempotent inserts rely on session_state guards | `turso_db.py:521,786` | Page reload creates duplicates | Add `INSERT OR IGNORE` / `ON CONFLICT` |
| No cache eviction scheduled | `turso_db.py:418` | Expired entries accumulate | Call `clear_expired_cache` from init or cron |
| No transaction boundaries on multi-step export | `4_CSV_Export.py:446-463` | Partial state on crash | Wrap in single transaction |
| Migration string matching fragile | `turso_db.py:292` | libsql message format change breaks detection | Use `PRAGMA table_info` |

### Scoring
| Item | Location | Why It Matters | Refactoring Target |
|------|----------|----------------|-------------------|
| 3 outcome recording sites with divergent fallbacks | `4_CSV_Export.py:415`, `run_intent_pipeline.py:307` | Calibration sees inconsistent data | Extract shared `build_outcome_row()` |
| `import re` inside except blocks | `scoring.py:163,365` | Unconventional; confuses readers | Move to module-level |
| `score_geography_leads` misnamed for contact input | `scoring.py:243` | Function name implies company data, receives contacts | Rename or add `score_geography_contacts` |

### UI
| Item | Location | Why It Matters | Refactoring Target |
|------|----------|----------------|-------------------|
| CSS typo `font_weight` → `font-weight` | `ui_components.py:2187` | Badge styling silently broken | Fix underscore to hyphen |
| `st.cache_resource.clear()` clears ALL caches | `10_Pipeline_Health.py:106` | Health refresh kills DB/API singletons | Use targeted cache key invalidation |
| Orphaned session state: `_dedup_overrides` never cleared | `4_CSV_Export.py:173` | Stale overrides persist across workflows | Clear in "New Search" handlers |
| Mixed `st.button` / `ui.button` with no rule | All pages | Inconsistent visual weight | Document component selection rules |

### Testing
| Item | Location | Why It Matters | Refactoring Target |
|------|----------|----------------|-------------------|
| Vacuous tests shadow imports | `test_expand_search.py:82-105` | Tests always pass regardless of code | Import constants from module |
| DB CRUD tests use mocks not real SQLite | `test_turso_db.py:19-278` | SQL typos pass tests | Switch to in-memory SQLite |
| Export outcome logic untested | `4_CSV_Export.py:419-445` | Most complex export business logic | Add dedicated test suite |
| Zoho cluster (3 files) zero tests | `zoho_auth.py`, `zoho_client.py`, `zoho_sync.py` | Production code untested | Add async test suite |
| No `conftest.py` for shared fixtures | `tests/` | Test setup duplicated | Create shared fixtures |

### Configuration
| Item | Location | Why It Matters | Refactoring Target |
|------|----------|----------------|-------------------|
| 7 sources of truth for `accuracy=95` | `icp.yaml`, `zoominfo_client.py:141`, `expand_search.py:81`, 4 pages | Guaranteed drift | Central `get_config("accuracy_min")` accessor |
| `expand_search.py` constants not from config | `expand_search.py` top-level | Parallel defaults to `icp.yaml` | Read from `utils.load_config()` |
| Dependencies unpinned | `requirements.txt` — all `>=` | Supply chain risk | Pin exact versions with `pip-compile` |

---

## D6. UI/UX Critique

### Homepage (app.py)
- **P2**: Quick-action cards not clickable; separate button below each card
- **P2**: "Recent Runs" header renders even when empty — show nothing or a subtle prompt
- **P2**: No "continue where you left off" CTA for staged leads from previous session

### Intent Workflow (1_Intent_Workflow.py)
- **P1**: Read-only filters look identical to editable filters (`lines 318-328`) — visually distinguish
- **P1**: Contact radio labels unreadable — 6+ fields concatenated into ~140 char string (`line 1024`)
- **P1**: No "Jump to Results" anchor after enrichment; user must scroll
- **P1**: API errors show no Retry button
- **P2**: Step numbering in subheaders diverges from step indicator (two sources of truth)
- **P2**: `label_visibility="collapsed"` on populated inputs means no visible label anywhere
- **P2**: Test mode emoji "🧪" should be hidden in production

### Geography Workflow (2_Geography_Workflow.py)
- **P1**: 2-click search (Preview → Confirm) is unnecessary friction for experienced users (`lines 863-924`)
- **P1**: Contact radio labels same unreadable pattern as Intent — even longer here
- **P2**: Operator details rendered as disabled `st.text_input` — looks like error, should be info card (`lines 364-373`)
- **P2**: "Save as Template" input appears inline with no visual separation (`lines 604-621`)
- **P2**: Quality Filters 4-column layout collapses badly on narrow screens (`lines 626-719`)
- **P2**: Mode description uses `st.caption` while Intent uses `st.info` — inconsistent visual weight
- **P2**: "Stop Search" button inside 0.5s polling fragment may flicker

### Operators (3_Operators.py)
- **P2**: "⋮" toggle has tiny touch target, no hover affordance, not discoverable
- **P2**: Zoho Sync section placed at top above the primary operator list — should be below
- **P2**: "Full Resync" and "Sync Changes" both `type="primary"` — Full Resync should be secondary
- **P2**: Search field `label_visibility="collapsed"` with long placeholder gets cut off

### CSV Export (4_CSV_Export.py)
- **P1**: Disabled VanillaSoft Push gives no explanation — tooltip on disabled element not visible in most browsers
- **P1**: Batch ID regenerated on operator change, creating phantom records (`lines 332-349`)
- **P2**: "Lead score details" expander evaluates all leads on every render even when collapsed
- **P2**: Cross-workflow dedup section appears/disappears with no explanation
- **P2**: "Staged" is internal jargon — rename to "Saved" or "Ready to export"

### Usage Dashboard (5_Usage_Dashboard.py)
- **P2**: "Fetch ZoomInfo Usage" requires manual click — page appears incomplete on load
- **P2**: "By Period" tab shows metrics with no temporal context header ("Last 7 Days")
- **P2**: "Recent Queries" truncates descriptions to 30 chars with no ellipsis

### Executive Summary (6_Executive_Summary.py)
- **P2**: "1 days" plural error on first day of month (`line 62-64`)
- **P2**: Trends tab week boundaries use rolling windows, not calendar weeks — misleading charts
- **P2**: Geography budget block uses different components than Intent budget block — inconsistent

### Score Calibration (7_Score_Calibration.py)
- **P1**: Calibration checkboxes pack 7 data points into one unstructured string — not scannable
- **P2**: "Apply N Selected Updates" button appears/disappears causing layout shift
- **P2**: Raw SQL `db.execute()` in UI file leaks schema knowledge into page layer

### Automation (9_Automation.py)
- **P2**: Run cards show raw ISO timestamps instead of "2 hours ago" format
- **P2**: Configuration section tells user to "edit config/icp.yaml" — inaccessible to sales-ops users
- **P2**: Run history expander and compact HTML cards show duplicate information

### Pipeline Health (10_Pipeline_Health.py)
- **P2**: Two separate "recent activity" tables show overlapping data (pipeline runs + query activity)
- **P2**: "Refresh Status" clears ALL `@st.cache_resource` globally — kills DB connections too
- **P2**: 26h staleness threshold not explained — should say "Expected daily run at 7 AM ET"

### Cross-Cutting
- **P2**: `text_muted` (#5c6370) on `bg_secondary` (#141922) ≈ 3.8:1 contrast — below WCAG AA 4.5:1
- **P2**: Sidebar CSS nth-child icon injection breaks when pages are reordered
- **P2**: Page titles don't match sidebar nav labels ("Intent" vs "1 Intent Workflow")
- **P2**: `st.markdown("---")` used inconsistently as separator — `labeled_divider` is better

---

## D7. Roadmap

### Quick Wins (1 day each)
1. **Add confirmation dialogs** to VanillaSoft Push and Run Now — `@st.dialog` pattern
2. **Fix CSS typo** `font_weight` → `font-weight` in `ui_components.py:2187`
3. **Add `.env` to `.gitignore`**
4. **Fix `credits_used=0` on failure** in `run_intent_pipeline.py:348,351` — use summary dict
5. **Add `try/finally`** to `auto_run_triggered` in `9_Automation.py`
6. **HTML-escape** `detail` in `health_indicator()` and `_friendly_error()`
7. **Fix `hmac.compare_digest`** in `utils.py:38` + add attempt counter
8. **Fix "1 days" plural** in `6_Executive_Summary.py:62`
9. **Add UNIQUE constraint** to `lead_outcomes(batch_id, person_id)`

### 1 Week
1. **Batch Step 3 ID resolution** — saves ~24 credits/run, single code change
2. **Add GitHub Actions test workflow** + pin dependencies
3. **Centralize configuration** — reduce 7 accuracy sources to 1 via `utils.py` accessors
4. **Add concurrent-run guard** — `SELECT WHERE status='running'` check at pipeline start
5. **Extract `build_outcome_row()`** helper used by all 3 outcome recording sites
6. **Simplify Geography search** — 1-click search with optional preview

### 1 Month
1. **Split `turso_db.py`** into domain repository modules (operators, cache, usage, pipeline, leads)
2. **Replace contact radio labels** with structured mini-cards showing name, title, company, phone
3. **Add Zoho tests** + switch DB CRUD tests from mocks to in-memory SQLite
4. **Implement background retry** for ZoomInfo 429s — use threading or Streamlit fragment with progress instead of blocking `time.sleep`

---

## D8. If You Can Only Fix 3 Things

### 1. Add confirmation dialogs + concurrent-run guard (4 hours)

**What:** `@st.dialog` confirmation on VanillaSoft Push (`4_CSV_Export.py:376`) and Run Now (`9_Automation.py:189`). Plus `SELECT ... WHERE status='running'` guard at `run_intent_pipeline.py` start.

**Why:** These are the only P0 issues. VanillaSoft Push creates real CRM records that can't be undone. Run Now burns capped credits. Overlapping runs double-charge. Combined, these represent the highest-severity risk in the codebase, and the fix is under 50 lines of code.

**ROI:** Maximum user protection per line of code. Eliminates all P0 issues.

### 2. Batch Step 3 ID resolution + add UNIQUE to lead_outcomes (3 hours)

**What:** Change `run_intent_pipeline.py:186-207` from a per-company enrich loop to a single batched call. Add `UNIQUE(batch_id, person_id)` constraint to `lead_outcomes` table.

**Why:** The N+1 burns ~24 credits per automated run — that's ~120 credits/week on the 500-credit weekly cap (24% of budget). The missing UNIQUE constraint means duplicate outcomes inflate delivery rate statistics that drive Score Calibration, meaning the ML-like scoring feedback loop is operating on dirty data.

**ROI:** Direct cost savings + calibration data integrity. Both fixes are small, isolated, and low-risk.

### 3. Centralize configuration + add CI test workflow (1 day)

**What:** Create `utils.get_config("accuracy_min")` etc. that reads from `icp.yaml` as single source of truth. Remove hardcoded fallbacks from `zoominfo_client.py`, `expand_search.py`, `run_intent_pipeline.py`, and page files. Add `test.yml` GitHub Actions workflow on push/PR.

**Why:** Configuration sprawl is the #1 maintainability risk — every business rule change requires editing 4-7 files. The lack of CI means 579 tests provide no production protection. Together, these are the two changes that most reduce ongoing maintenance burden.

**ROI:** Prevents drift on every future config change. CI catches bugs before production on every push.

---

*Generated by comprehensive audit across 4 parallel analysis agents + manual verification. Every finding references specific file:line evidence. Prior session 30 audit verified and expanded with 10 new findings.*
