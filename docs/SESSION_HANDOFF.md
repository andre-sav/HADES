# Session Handoff - ZoomInfo Lead Pipeline

**Date:** 2026-02-17
**Status:** Intent automation shipped, design system extracted, 451 tests passing

## What's Working

1. **Authentication** - Legacy JWT from `/authenticate`, token persisted to Turso DB across restarts
2. **Contact Search** - All filters working, including companyId-based search (`/search/contact`)
3. **Contact Enrich** - 3-level nested response parsing fixed (needs production test)
4. **Intent Search** - Legacy `/search/intent` with proper field normalization (nested `company` object + null field fallbacks)
5. **Two-Phase Intent Pipeline** - Phase 1: Resolve hashed→numeric company IDs (enrich 1 contact, cache in Turso). Phase 2: Contact Search with ICP filters (management level, accuracy, phone)
6. **Scoring** - Data-calibrated per-SIC scores from HLM delivery data (N=3,136). Inverted employee scale. 25 SIC codes.
7. **CSV Export** - VanillaSoft format, supports both workflows + validation checklist + mobile phone formatting
8. **Test Mode** - Skips enrichment step only (search calls still use real API)
9. **Target Contacts Expansion** - Auto-expand search to meet target count (Geography)
10. **Combined Location Search** - Toggle to merge PersonAndHQ + Person results (Geography)
11. **UX Overhaul** - Full-width layout, action bar, summary strip, run logs, export validation
12. **Shadcn UI** - `streamlit-shadcn-ui` adopted across all pages
13. **API Debug Panel** - Intent Workflow shows raw API keys, raw first item, normalized sample, request/response
14. **Turso Reconnect** - Auto-reconnects on stale Hrana stream errors (survives idle timeouts)
15. **Token Persistence** - ZoomInfo JWT saved to Turso `sync_metadata` table, loaded on restart
16. **Company ID Cache** - Turso `company_id_mapping` table persists hashed→numeric ID resolutions across sessions
17. **Editable Contact Filters** - Management level, accuracy minimum, phone fields editable in Intent Workflow Filters expander
18. **Calibration Script** - `calibrate_scoring.py` analyzes enriched delivery data and outputs per-SIC scores
19. **Intent Polling Automation** - Headless pipeline script, GitHub Actions cron (Mon-Fri 7AM ET), manual Run Now button, pipeline_runs DB tracking, Automation dashboard page
20. **Design System** - Extracted from `ui_components.py` into `.interface-design/system.md` — color tokens, typography, spacing, component patterns
21. **Staged Exports** - Workflow results persist to `staged_exports` table, survive browser refresh

## Known Issues

- **v2 Intent API requires OAuth2 PKCE** — The new `/gtm/data/v1/intent/search` endpoint rejects legacy JWT. Using legacy endpoint instead.
- **`@st.cache_resource` gotcha** — Code changes to cached classes require Streamlit restart.
- **Contact Enrich** — Response parsing fixed but never tested with real production data.
- **Intent search is free** — Only enrichment costs credits. Intent search `credits_used` set to 0.
- **Valid intent topics** — Must use exact ZoomInfo taxonomy: "Vending Machines", "Breakroom Solutions", "Coffee Services", "Water Coolers" (not "Vending", "Break Room", etc.)
- **GitHub Actions secrets not configured** — The intent-poll.yml workflow is deployed but repo needs 7 secrets set: TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, ZOOMINFO_CLIENT_ID, ZOOMINFO_CLIENT_SECRET, SMTP_USER, SMTP_PASSWORD, EMAIL_RECIPIENTS

---

## Session Summary (2026-02-17, Sessions 10-11)

### Intent Polling Automation (Full Feature)

Designed, planned, and implemented automated intent lead polling. 6-task TDD plan executed via subagent-driven development with two-stage review (spec compliance + code quality) per task.

**Commits:**
- `3854e2b` — `pipeline_runs` table + 3 DB methods + 9 tests
- `0d25203` — Pipeline run logging with status tracking and trigger source
- `c3535c8` — Credentials fallback to `st.secrets` for Run Now button
- `3612af8` — GitHub Actions workflow (`intent-poll.yml`, Mon-Fri 7AM ET, `workflow_dispatch` with dry_run)
- `6bbcee8` — Automation dashboard page (initial build)
- `21e0c54` — CLAUDE.md updated (file structure, 451 tests)

### Design System & UI Critique

- `d4079c8` — Extracted design system from `ui_components.py` into `.interface-design/system.md`. Rebuilt Automation page with custom HTML run cards, budget progress bar, structured config display.
- `bb985da` — Automation config block in `icp.yaml` + SMTP template
- `3fa4a6a` — Zoho sync: ISO timestamp format fix + duplicate name guard
- `c86e220` — Operators page: replaced unreliable `ui.button` with `st.button`
- `76451bf` — Fixed `empty_state` rendering raw HTML (indented tags treated as code blocks by markdown parser)

### Key Files Modified (Sessions 10-11)
```
turso_db.py                    - pipeline_runs table + 3 CRUD methods
scripts/run_intent_pipeline.py - Headless intent pipeline with DB logging
scripts/_credentials.py        - Env → secrets.toml → st.secrets fallback
.github/workflows/intent-poll.yml - Cron + manual dispatch workflow
pages/9_Automation.py          - Dashboard: metrics, Run Now, history, config
.interface-design/system.md    - Formalized design system
ui_components.py               - empty_state HTML rendering fix
config/icp.yaml                - automation.intent config block
zoho_sync.py                   - ISO timestamp + duplicate name guard
pages/3_Operators.py           - st.button for sync actions
.streamlit/secrets.toml.template - SMTP credential placeholders
tests/test_turso_db.py         - 9 pipeline_runs tests
tests/test_run_intent_pipeline.py - Pipeline logging + credential tests
CLAUDE.md                      - File structure, test count 451
```

### Test Count
451 tests passing (up from 438 at session 9)

### What Needs Doing Next Session
1. **Configure GitHub secrets** — 7 repo secrets needed for Actions cron to run
2. **Live test all pipelines** — Intent, Geography, Enrich, Export end-to-end (beads HADES-1ln, HADES-kyi, HADES-5c7, HADES-kbu)
3. **Zoho CRM dedup check at export** — P4 backlog (bead HADES-iic)

### Beads Status
```
HADES-1ln [P2] Live test Intent pipeline end-to-end
HADES-5c7 [P2] Live test Contact Enrich with real data
HADES-kyi [P2] Live test Geography pipeline end-to-end
HADES-kbu [P2] Live test all 4 pipelines with Streamlit running
HADES-iic [P4] Add Zoho CRM dedup check at export time
```

---

## Session Summary (2026-02-16, Session 9)

### Staged Exports — Persist Leads for CSV Re-Export

Implemented `staged_exports` table so workflow results survive browser refresh. Users can now re-export past runs without re-running the workflow.

- **turso_db.py** — Added `staged_exports` table to `init_schema()` (auto-creates on app start), plus 4 methods: `save_staged_export()`, `get_staged_exports()`, `get_staged_export()`, `mark_staged_exported()`
- **pages/1_Intent_Workflow.py** — Persist leads to `staged_exports` after scoring, with `intent_leads_staged` rerun guard
- **pages/2_Geography_Workflow.py** — Same pattern with `geo_leads_staged` guard, includes `operator_id`
- **pages/4_CSV_Export.py** — When session state empty, shows staged exports table with Load buttons. Loaded leads populate session state, existing export flow works unchanged. Mark-as-exported updates the staged row.

### Messy Data Hardening (HADES-20n — CLOSED)

Ran comprehensive code exploration across all API boundary code. Found and fixed 4 bugs, added 28 edge case tests.

**Bugs fixed:**
1. **scoring.py:156** — `float("5.0 miles")` crash in geography scoring → try/except + regex digit extraction
2. **scoring.py:350** — `"95%" >= 95` type mismatch in contact scoring → int coercion + regex fallback
3. **utils.py:316** — ZIP+4 with space `"75201 1234"` and 9-digit `"752011234"` → split/truncate to 5 digits
4. **expand_search.py:119** — Mixed int/string company/person IDs → normalize to `str()` for dedup

**28 new tests across:** test_scoring.py (17), test_utils.py (4), test_expand_search.py (4), test_dedup.py (3)

### CLAUDE.md Updated

- Test count 288 → 438
- Documented schema auto-creation pattern and Streamlit rerun guard pattern
- Added ZoomInfo messy data specifics (mixed ID types, string numerics, ZIP+4 variants)
- Reviewed all available skills; identified `/commit`, `/code-review`, `systematic-debugging`, `dispatching-parallel-agents` as most relevant for HADES

### Key Files Modified (This Session)
```
turso_db.py                    - staged_exports table + 4 CRUD methods
scoring.py                     - Distance/accuracy defensive parsing
utils.py                       - ZIP+4 space/9-digit handling
expand_search.py               - Normalize company/person IDs to str
pages/1_Intent_Workflow.py     - Persist leads to staged_exports
pages/2_Geography_Workflow.py  - Persist leads to staged_exports
pages/4_CSV_Export.py          - Load staged exports from DB
tests/test_scoring.py          - 17 messy data edge case tests
tests/test_utils.py            - 4 ZIP format edge case tests
tests/test_expand_search.py    - 4 mixed ID edge case tests
tests/test_dedup.py            - 3 HTML entity / unicode tests
CLAUDE.md                      - Updated patterns, test count, messy data docs
```

### Uncommitted Changes (from prior sessions)
4 modified files + 3 untracked from sessions before this one:
- `.streamlit/secrets.toml.template` — Zoho/SMTP credential placeholders
- `config/icp.yaml` — ICP config changes
- `pages/3_Operators.py` — Operator page updates
- `zoho_sync.py` — Sync logic changes
- `scripts/_credentials.py`, `scripts/run_intent_pipeline.py`, `tests/test_run_intent_pipeline.py` — Untracked scripts

### Test Count
438 tests passing (up from 410 at session start)

### What Needs Doing Next Session
1. **Live test all pipelines** — Intent, Geography, Enrich, Export end-to-end (beads HADES-1ln, HADES-kyi, HADES-5c7, HADES-kbu)
2. **Commit prior session changes** — 4 modified + 3 untracked files from sessions 6-8
3. **Zoho CRM dedup check at export** — P4 backlog (bead HADES-iic)

### Beads Status
```
HADES-1ln [P2] Live test Intent pipeline end-to-end
HADES-5c7 [P2] Live test Contact Enrich with real data
HADES-kyi [P2] Live test Geography pipeline end-to-end
HADES-kbu [P2] Live test all 4 pipelines with Streamlit running
HADES-iic [P4] Add Zoho CRM dedup check at export time
HADES-20n [P2] CLOSED — 4 bugs fixed + 28 edge case tests
HADES-bk3 [P2] CLOSED — Production test UX (visual audit + 10 fixes)
```

---

## Session Summary (2026-02-12, Session 7)

### Data-Driven Scoring Calibration (Plan Implementation)

Replaced all intuition-based scoring with empirically derived values from 3,136 HLM Locating delivery records:

1. **Created `data/sic_manual_overrides.csv`** — 29 manual SIC classifications for Delivered records with no `vs_sic` match (100% SIC coverage on delivered records)
2. **Created `calibrate_scoring.py`** — Standalone analysis script: reads enriched CSV + overrides, computes per-SIC delivery rates, min-max scales to 20-100 scores, analyzes employee scale
3. **Updated `config/icp.yaml`** — Replaced tier-based `onsite_likelihood` (high=100/medium=70/low=40) with per-SIC score map (16 SICs with 10+ records). Inverted `employee_scale` (50-100emp→100, 501+→20). Added 3 new SIC codes (4213 Trucking, 4581 Aviation, 4731 Freight). Total: 22→25 SICs.
4. **Rewrote `utils.py:get_onsite_likelihood_score()`** — From tier-iteration to single dict lookup against `sic_scores` map
5. **Updated all tests** — New per-SIC score assertions, inverted employee scale, recalculated composite scores

**Key data insights:**
- Hotels (7011) dropped from 100→40 (only 6.8% delivery rate)
- Residential Care (8361) rose to 71 (17.4% rate)
- Aviation Services (4581) top performer at 100 (27.3% rate)
- Small companies (50-100emp) convert at 10% vs large (501+) at 1% — completely inverted from prior assumption

### Full Project Code Review (13 Issues Fixed)

Ran comprehensive code review, identified and fixed all 13 issues:

**Critical (2):**
- DataFrame index mismatch in Intent/Geography workflows — added `_idx` column for safe filtered-row mapping
- Parameter mutation in ZoomInfo pagination — added `dataclasses.replace()` copies in all 3 methods

**High (4):**
- Redundant `(ValueError, Exception)` catch → simplified to `Exception` in turso_db.py
- `execute_many` replay risk — added rollback + docstring explaining reconnect safety
- CLAUDE.md stale "22 SIC codes" → updated to 25 in 3 locations
- Mobile phone unformatted in export — added `format_phone()` call

**Medium (7):**
- Hardcoded SIC sets in calibration script → reads from icp.yaml via `load_icp_sics()`
- `lru_cache` on `load_config()` prevents hot-reload → added docstring note
- Missing combined search integration tests → added 2 tests
- Hardcoded proximity default 70 → config-driven `get_proximity_score(15.0)`
- `_last_auth_response` not initialized in `__init__` → added
- Budget alert scale inconsistency → normalized to `threshold_percent`
- Missing enrich response format tests → added 2 tests for uncovered paths

### Key Files Modified
```
config/icp.yaml               - Per-SIC scores, inverted employee scale, 3 new SIC codes
utils.py                       - Rewrote get_onsite_likelihood_score(), 3 new SIC descriptions
scoring.py                     - Config-driven proximity default
calibrate_scoring.py           - NEW: calibration analysis script
data/sic_manual_overrides.csv  - NEW: 29 manual SIC classifications
pages/1_Intent_Workflow.py     - _idx column for safe index mapping
pages/2_Geography_Workflow.py  - _idx column for safe index mapping
zoominfo_client.py             - replace(params) copies, _last_auth_response init
turso_db.py                    - Simplified exception handling, execute_many rollback
export.py                      - Mobile phone formatting
cost_tracker.py                - Budget alert scale normalization
CLAUDE.md                      - Updated SIC count 22→25
tests/test_utils.py            - Empirical score assertions, inverted employee scale
tests/test_scoring.py          - Recalculated composite scores
tests/test_export.py           - Mobile phone formatting test
tests/test_expand_search.py    - 2 combined search integration tests
tests/test_zoominfo_client.py  - 2 enrich response format tests
```

### Uncommitted Changes
21 modified files + untracked files from sessions 6-8. All uncommitted — needs commit.

### What Needs Doing Next Session
1. **Commit all changes** — 21 modified files + new files from sessions 6-8
2. **Live test all pipelines** — Intent, Geography, Enrich, Export end-to-end (beads HADES-1ln, HADES-kyi, HADES-5c7, HADES-kbu)
3. **Harden API clients** — Edge case tests for messy data (bead HADES-20n)
4. **Continue brainstorming session** — Morphological Analysis in progress (see `_bmad-output/brainstorming/brainstorming-session-2026-02-13.md`)

---

## Session Summary (2026-02-13, Session 8)

### Intent Workflow Findings Fix (6 of 9 issues, P0-P2)

Implemented fixes for 9 issues found during manual testing of the Intent Workflow (documented in `docs/testing/2026-02-12-intent-workflow-findings.md`). P3 issues deferred.

1. **P0 — Deduplicate contacts by personId** — Added `seen_person_ids` set in `_search_contacts_single_batch()` to filter duplicates during pagination. Added defensive dedup in `build_contacts_by_company()`. Both layers with tests.
2. **P1 — Use numeric signalScore for intent scoring** — `calculate_intent_score()` now prefers numeric `signalScore` (0-100) over categorical `intentStrength` bucket. Added `audienceStrength` bonus (0-10 pts) and employee scale bonus (0-5 pts) as tiebreakers. 4 new tests.
3. **P1 — Fix Companies metric in Results** — Shows "4 of 7" (contacts found vs selected) instead of just the selected count.
4. **P2 — Show zero-contact explanation** — After contact search, shows caption explaining missing companies.
5. **P2 — Collapse completed steps** — When results showing, Step 1 form + debug panel hidden, replaced with collapsed pipeline summary expander.
6. **P1 — Hide City/State columns in test mode** — City/State excluded from results table in test mode with explanatory caption.

**Deferred (P3):** #8 Search button stays accessible, #9 Intent signal filtering limited.

### Brainstorming Session Started

Began BMAD brainstorming session on maximizing lead quantity AND quality. AI-recommended techniques: Morphological Analysis → Cross-Pollination → Reverse Brainstorming. Paused during Phase 1 (parameter grid building).

### Key Files Modified (This Session)
```
zoominfo_client.py            - personId dedup in _search_contacts_single_batch()
expand_search.py              - personId dedup in build_contacts_by_company()
scoring.py                    - Numeric signalScore + audience/employee tiebreakers
pages/1_Intent_Workflow.py    - Companies metric, zero-contact msg, step collapsing, City/State test mode
tests/test_zoominfo_client.py - Pagination dedup test
tests/test_expand_search.py   - build_contacts_by_company dedup test
tests/test_scoring.py         - 4 new scoring tests (numeric signal, fallback, audience, employee)
_bmad-output/brainstorming/   - NEW: brainstorming session document
```

### Test Count
382 tests passing (up from ~296 in session 7)

---

## Session Summary (2026-02-12, Session 7)

### Data-Driven Scoring Calibration (Plan Implementation)

(Moved from top-level — see below)

---

## Session Summary (2026-02-11, Session 6)

### Visual UX Audit & Fixes (10 issues)

Chrome MCP working — performed visual audit of all 6 pages + home. Identified 10 cross-cutting UX issues and fixed all of them:

1. **White metric cards** — Replaced all `ui.metric_card()` (shadcn iframe, white bg) with custom `metric_card()` across 7 files
2. **Chart theming** — Executive Summary Plotly charts: per-workflow colors (indigo=Intent, cyan=Geography), transparent bg, dotted gridlines, Urbanist font
3. **Table styling** — Added `styled_table()` helper with alternating rows, hover, monospace numbers, status pills. Updated home page and Export tables
4. **Empty states** — Improved Export empty state, Usage weekly context caption, Geography operator count hint
5. **Button hierarchy** — Verified CSS already correct, no changes needed
6. **Font loading** — Verified Urbanist + IBM Plex Mono loading correctly via Chrome JS
7. **Sidebar icons** — CSS pseudo-elements for sidebar nav items
8. **Color palette** — Progress bar success color changed from green to indigo→cyan gradient
9. **Loading states** — Consolidated shimmer keyframe to global CSS
10. **Information density** — Operators pagination (20/page), card-style home quick actions, styled Executive Summary table

### CodeRabbit Review & Fixes (6 applied)

Ran full project review. Applied 6 fixes:
- Bare `except:pass` → logs error with `st.caption()` (Intent workflow)
- SQLite parameter limit → batches `IN` clause to 900 params (turso_db.py)
- Missing delete error handling → try/except with `st.error()` (Operators)
- `ui.button()` None guard → `bool()` wrapper (ui_components.py)
- Unreachable geo "selecting" state → changed key from `geo_contacts_by_company` to `geo_preview_contacts`
- "Coffee services" → "Coffee Services" (icp.yaml)

### Outcome-Driven Scoring Design

Brainstormed and designed a feedback loop system for data-calibrated lead scoring:
- **Batch ID tracking**: HADES export → VanillaSoft "Import Notes" → Zoho CRM custom field
- **Outcome tables**: `historical_outcomes` (3,000+ existing leads) + `lead_outcomes` (ongoing)
- **Historical bootstrap**: Import 319 delivery records + 3,000+ total VanillaSoft-sourced leads from Zoho
- **Calibration engine**: Conversion rates by SIC code, employee range, proximity, state → replace hardcoded weights
- **Score Calibration page**: Review suggested vs current weights, approve before applying
- **Future path**: Graduate to logistic regression at 500+ HADES-originated outcomes
- Design doc: `docs/plans/2026-02-11-outcome-driven-scoring-design.md`

### Committed All Sessions

First commit since initial: `9b03af0` — 34 files, +4,346/-697 lines covering sessions 1-6. 293 tests pass (pre-commit hook verified).

### Key Files Modified
```
ui_components.py               - styled_table(), sidebar icons, progress bar color, shimmer consolidation
app.py                         - Custom metric cards, styled recent runs table, card-style quick actions
pages/1_Intent_Workflow.py     - Custom metric cards, enrichment error logging
pages/2_Geography_Workflow.py  - Custom metric cards, operator count hint
pages/3_Operators.py           - Custom metric cards, pagination (20/page), delete error handling
pages/4_CSV_Export.py          - Custom metric cards, styled table, improved empty state
pages/5_Usage_Dashboard.py     - Custom metric cards, budget context caption
pages/6_Executive_Summary.py   - Custom metric cards, per-workflow chart colors, styled table, rgba fix
turso_db.py                    - get_company_ids_bulk batching (900 per query)
config/icp.yaml                - "Coffee Services" capitalization fix
docs/plans/2026-02-11-outcome-driven-scoring-design.md  - NEW: outcome scoring design
docs/ux-audit-2026-02-11.md    - NEW: visual UX audit with 10 findings
```

### Uncommitted Changes
None — working tree clean.

### What Needs Doing Next Session
1. **Implement outcome-driven scoring** — Follow design doc, start with batch ID generation + outcome tables
2. **Live test all pipelines** — Intent, Geography, Enrich, Export end-to-end (beads HADES-1ln, HADES-kyi, HADES-5c7, HADES-kbu)
3. **Harden API clients** — Edge case tests for messy data (bead HADES-20n)

---

## Session Summary (2026-02-11, Session 5)

### CSS Theme Overhaul (Priority 1 — "Mission Control" aesthetic)

**Design assessment** performed across all 6 pages and `ui_components.py` (1,711 lines). Identified 10 pain points: visual fragmentation (3 competing styling systems), default typography, no motion/transitions, unpolished native widgets, passive home page.

**Implemented:**
1. **Google Fonts** — Urbanist (display/body) + IBM Plex Mono (data values) loaded via `<link>` tag
2. **Global font override** — CSS selectors for all Streamlit elements: headings, inputs, labels, tabs, sidebar, captions, metrics
3. **Monospace data values** — IBM Plex Mono with `font-variant-numeric: tabular-nums` on all metric cards, summary strips, deltas, pagination
4. **Input labels** — uppercase, letter-spaced, smaller text ("Mission Control" console feel)
5. **Primary buttons** — indigo→cyan gradient, hover glow (`box-shadow`), press scale (`transform: scale(0.98)`)
6. **Secondary buttons** — indigo border + text highlight on hover
7. **Input focus states** — primary color border + 2px glow ring
8. **Dataframe** — rounded corners, consistent border
9. **Expander** — card-like background, hover border
10. **Sidebar** — active page indigo left-border indicator, hover background
11. **Dividers** — gradient fade (transparent→border→transparent) replacing hard `<hr>` lines
12. **Metric cards** — 2px gradient accent line at top, box-shadow elevation, hover lift
13. **Step indicator** — active step gets gradient + glow; completed connectors use gradient
14. **Contact cards** — selection glow ring, hover shadow
15. **Scrollbar** — 6px thin dark scrollbar
16. **Background** — subtle radial vignette with primary/accent color tints
17. **Page load animation** — 300ms fade-in-up (respects `prefers-reduced-motion`)
18. **Color refinement** — deeper backgrounds (`#0a0e14`, `#141922`), subtler borders, softer text white
19. **Accent color family** — cyan (#06b6d4) added for gradient endpoints
20. **CSS custom properties** — `--accent-gradient`, `--card-shadow`, `--radius`, `--transition` for consistency

### Chrome Extension Debugging
- Diagnosed competing native messaging hosts (Claude Desktop + Claude Code both claim extension ID `fcoeoabgfenejglbffodgkkbkcdhcgfn`)
- Renamed Desktop host to `.bak` — extension still not connecting
- Native host binary verified working (creates socket at `/tmp/claude-mcp-browser-bridge-boss/`)
- Likely needs extension reload at `chrome://extensions` or full reinstall

### Key Files Modified
```
ui_components.py          - FONTS dict, accent colors, deepened palette, full inject_base_styles() rewrite (+770 lines of CSS)
.streamlit/config.toml    - Updated background/text colors, removed invalid color options
docs/SESSION_HANDOFF.md   - This update
```

### Uncommitted Changes
All changes from sessions 1-5 remain uncommitted (22 modified + 9 untracked files, +3052/-666 lines). Theme overhaul needs visual verification before committing.

### What Needs Doing Next Session
1. **Visual verification** — Get Chrome extension working or manually open localhost:8502 and review all 6 pages
2. **Priority 2: Home page redesign** — Active dashboard with pipeline status, next actions
3. **Priority 3: Table styling** — Inline score bars, row emphasis, better column formatting
4. **Priority 4: Page load animations** — Staggered fade-in for cards and sections
5. **Priority 5: Standardize headers/action bars** across all 6 pages
6. **Live test all pipelines** — Intent, Geography, Enrich, Export (beads HADES-1ln through HADES-kbu)

---

## Session Summary (2026-02-10, Session 4)

### Intent Pipeline Debugging (6 cascading bugs fixed)
1. **`sicCodes` array vs string** — Streamlit cached old code; restart fixed
2. **Invalid topic "Vending"** — Queried `/lookup/intent/topics`, found correct name "Vending Machines". Updated `config/icp.yaml` and default in UI
3. **Hashed companyId** — Intent API returns hashed IDs incompatible with Contact Search. Built two-phase pipeline: enrich 1 recommended contact → get numeric ID → cache → Contact Search
4. **Date parsing** — Legacy API returns `"1/24/2026 12:00 AM"` format. Added US date parsing branch to `_calculate_age_days()`
5. **Nested company object** — API returns `company.name` not `companyName`. Updated normalization to check nested `company` object
6. **Null field fallback bug** — `dict.get("intentDate", fallback)` returns `None` when key exists with null value. Changed all fallbacks to `or` pattern: `item.get("intentDate") or item.get("signalDate", "")`

### Two-Phase Contact Pipeline
- Phase 1: Resolve hashed company IDs via Turso cache or enrich 1 recommended contact
- Phase 2: Contact Search with full ICP filters (Manager level, 95+ accuracy, phone required)
- Company ID mapping cached in Turso `company_id_mapping` table

### UI Improvements
- Full-width layout (removed `max-width: 1200px` constraint)
- Editable Contact Search filters in Filters expander (management level, accuracy, phone fields)
- Step 2 table cleaned: removed empty columns (City, State, Employees), added Age column
- Raw API response display in API Request/Response expander for debugging
- Intent search credits set to 0 (search is free)

### Code Review
- Ran 5 parallel review agents, found 2 actionable issues
- Fixed: outdated pipeline comment, added 3 US date format tests

### Key Files Modified
```
config/icp.yaml                - Real ZoomInfo intent topics
pages/1_Intent_Workflow.py     - Two-phase pipeline, editable filters, table cleanup, raw API display
scoring.py                     - US date format parsing in _calculate_age_days()
turso_db.py                    - company_id_mapping table and CRUD methods
zoominfo_client.py             - Nested company object normalization, null field fallbacks, raw key capture
ui_components.py               - Full-width layout (max-width: 100%)
tests/test_scoring.py          - 3 US date format tests
tests/test_zoominfo_client.py  - 2 tests (nested company, null fallback)
.claude/commands/              - Copied skills from .claude/skills/ to correct location
```

### Uncommitted Changes
All changes from sessions 1-4 remain uncommitted (22 modified + 9 untracked files, +2531/-594 lines). Intent pipeline needs live verification before committing.

### What Needs Live Testing Next Session
- **Re-run intent search** after null fallback fix — should now show company names and proper scoring
- Verify two-phase pipeline: resolve IDs → Contact Search → Enrich → Export
- Confirm editable filters flow through to Contact Search params

---

## Session Summary (2026-02-10, Session 3)

### Insights-Driven Improvements
- Reviewed `/insights` report (177 sessions, 227 commits analyzed)
- Created **global `~/.claude/CLAUDE.md`** with behavioral rules: root-cause debugging, efficient planning, messy data handling, schema consistency, start-work-immediately
- Added **project-specific sections** to `HADES/CLAUDE.md`: Testing, External APIs (Zoho + ZoomInfo)
- Created **`/session-close` skill** (`.claude/skills/session-close.md`) — one-command session close protocol
- Created **`/session-start` skill** (`.claude/skills/session-start.md`) — one-command session start protocol
- Added **pre-commit test hook** (`.git/hooks/pre-commit`) — runs full pytest suite before every commit, blocks on failure (~1.4s)
- Created beads: HADES-20n (harden API edge cases), HADES-kbu (live test all pipelines)

### Key Files Modified/Created
```
~/.claude/CLAUDE.md                    - NEW: global behavioral rules
CLAUDE.md                              - Added Testing + External APIs sections
.claude/skills/session-close.md        - NEW: session close skill
.claude/skills/session-start.md        - NEW: session start skill
.git/hooks/pre-commit                  - Added pytest gate before beads hook
```

### Uncommitted Changes
All changes from sessions 1-3 remain uncommitted (16 modified + 7 untracked files, +2196/-523 lines). No commit made this session — work was tooling/config focused.

---

## Session Summary (2026-02-10, Session 2)

### Turso Stale Connection Fix
- `turso_db.py`: Added `_reconnect()` and `_is_stale_stream_error()` to `TursoDatabase`
- `execute()`, `execute_write()`, `execute_many()` all auto-reconnect on "stream not found" 404 errors
- Root cause: Turso closes idle Hrana streams server-side; cached connection goes stale

### ZoomInfo Token Persistence
- `zoominfo_client.py`: Added `_load_persisted_token()` and `_persist_token()` to `ZoomInfoClient`
- Token stored in Turso `sync_metadata` table (key: `zoominfo_token`, value: JSON with jwt + expires_at)
- `_get_token()` flow: check in-memory → check DB → call `/authenticate`
- Prevents auth rate limits on Streamlit restarts

### Intent Search: Legacy API Migration
- **Problem**: v2 endpoint `/gtm/data/v1/intent/search` requires OAuth2 PKCE tokens (scope `api:data:intent`), incompatible with legacy JWT from `/authenticate`
- **Fix**: Switched to legacy `/search/intent` endpoint which works with JWT auth
- Legacy endpoint supports ICP filters: `employeeRangeMin` (string), `sicCodes` (comma-separated string)
- Response normalization handles both legacy field names (`companyId`, `intentStrength`) and fallbacks
- All 5 intent search tests updated for legacy format

### Auth Error Guard
- `_authenticate()` now raises `ZoomInfoAuthError` if response is 200 but JWT is missing
- Previously silently set `access_token = None`, causing all subsequent API calls to fail with 401

### API Debug Panel (Intent Workflow)
- Shows full request: method, URL, query params, request body
- Shows full response: HTTP status, headers (checkbox toggle), response body as JSON
- Shows errors: message, attempt count, auth response body when relevant
- `ZoomInfoClient.last_exchange` captures every HTTP request/response for debugging
- Auto-expands on error for immediate visibility

### Key Files Modified

```
turso_db.py                   - Stale stream reconnect logic
zoominfo_client.py            - Token persistence, legacy intent endpoint, last_exchange debug, auth guard
pages/1_Intent_Workflow.py    - API debug panel (request/response/error display)
tests/test_zoominfo_client.py - 5 intent tests updated for legacy format
```

## Previous Session (2026-02-10, Session 1)

- Shadcn UI adoption across all pages
- Intent Search migrated to v2 JSON:API (later reverted to legacy in Session 2)
- UX overhaul: action bar, summary strip, run logs, export validation
- Beads issue tracker initialized
- 288 tests passing

## Test Coverage

- **451 tests passing** (all green, run `python -m pytest tests/ -v`)

## API Usage

| Limit | Used | Total | Remaining |
|-------|------|-------|-----------|
| Unique IDs (Credits) | ~566 | 30,000 | ~29,434 |
| API Requests | ~107 | 3,000,000 | ~3M |

## Next Steps (Priority Order)

1. **Configure GitHub secrets** — 7 repo secrets for intent polling cron
2. **Live test all pipelines** — Intent, Geography, Enrich, Export end-to-end
3. **Zoho CRM dedup check at export** — P4 backlog

## Beads Status

```
HADES-1ln [P2] Live test Intent pipeline end-to-end
HADES-5c7 [P2] Live test Contact Enrich with real data
HADES-kyi [P2] Live test Geography pipeline end-to-end
HADES-bk3 [P2] CLOSED - Production test UX (visual audit + 10 fixes applied)
HADES-20n [P2] CLOSED — 4 bugs fixed + 28 edge case tests
HADES-kbu [P2] Live test all 4 pipelines with Streamlit running
HADES-iic [P4] Add Zoho CRM dedup check at export time
```

## Chrome Extension Fix

Claude Desktop's native host was renamed to `.bak`:
```
~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.anthropic.claude_browser_extension.json.bak
```
To restore: rename back (remove `.bak`). Extension still not connecting after rename — try reloading extension at `chrome://extensions` or reinstalling.

## Commands

```bash
streamlit run app.py          # Run app (currently running on port 8502)
python -m pytest tests/ -v    # Run tests (296 passing)
bd ready                      # See available work
bd list                       # All issues
python calibrate_scoring.py   # Re-run calibration analysis
```

---
*Last updated: 2026-02-17 (Session 11)*
