# HADES — Thorough whole-codebase code review

## Project context (cold-start brief)

HADES is a Streamlit multi-page app for a vending-services sales team.
Workflow: query ZoomInfo → score against ICP → export to VanillaSoft.
Stack: Streamlit + Turso (libsql) + httpx clients for ZoomInfo / Zoho /
VanillaSoft. ~33 Python modules, ~775 tests, ~10 user-facing pages.
Production target: a single Streamlit Community Cloud pod at
hades-hlm.streamlit.app, used daily by 5 sales operators.

Architecture overview is in CLAUDE.md. Per-session change history is
in docs/SESSION_HANDOFF.md (top entry = most recent session).

You are NOT being asked to fix anything in this pass. You are
producing a prioritized findings report. Code changes happen in
follow-up sessions, scoped to individual findings.

## Why this review exists

The codebase has grown rapidly (sessions 1-51 in the handoff doc), with
several incident-driven fixes — including a data-corruption bug
(broken ZIP centroids, session 51), a silent-failure class fixed in
sessions 48-49, and a phone-column inversion (also session 51).
These were caught because operators complained. A proactive sweep
should surface the next batch BEFORE the next operator complaint.

## Review dimensions (cover each)

### 1. Correctness & data integrity (highest priority)
The most expensive bugs in this codebase have been silent data
corruption. Look hard for:
- Field-name mismatches between API response shapes and DB columns
  (search-time vs. enrich-time field names diverge — see CLAUDE.md
  "API Format Notes" and `utils.ZOOMINFO_TO_VANILLASOFT`).
- Mixed ID types (companyId/personId can be int or string across
  responses — always coerce to str before using as dict keys).
- ZIP+4 variants ("75201-1234", "75201 1234", "752011234").
- Numeric fields returned as strings (contactAccuracyScore="95%",
  distance="5.0 miles") — every parse must be try/except wrapped.
- Streamlit rerun scoping: a variable assigned inside one conditional
  block being referenced in a different rerun branch. This is the
  exact bug class that broke Company Enrich in session 48.
- Boolean ICP filters silently dropping leads when fields are missing
  (None vs. "" vs. 0).

### 2. Error handling discipline
Sessions 48-49 already did a silent-failure audit, but the codebase
keeps growing. Re-grep:
- `grep -rn "except Exception" --include="*.py" | grep -v tests/`
  Every one should re-raise, log with exc_info=True, OR have a written
  reason in the code for swallowing.
- `grep -rn "pass$" --include="*.py"` — any bare `pass` inside an
  except clause is a smell.
- `grep -rn "try:" --include="*.py"` — count and read; any try block
  longer than ~10 lines is hiding too much.
- Specifically check the headless scripts (scripts/run_*.py) and the
  background pipeline (.github/workflows/intent-poll.yml entry) — silent
  failures here go undetected for days because nobody reads the logs.

### 3. Security
This app handles operator PII, lead contact details, and API
credentials. Check:
- API key handling: are any secrets ever logged, returned in error
  messages, or sent to Sentry/SMTP/etc.?
- SQL injection: the DB layer in `db/` uses parameterized queries
  generally, but verify any f-string composition. Pay attention to
  `zoho_sync.py:125` — COQL queries are built via f-string with a
  validated timestamp, but the validation is critical.
- Streamlit secrets exposure: any `st.write(st.secrets)` or
  `st.json(st.secrets)` left in test/debug code?
- Password gate: `utils.require_auth()` — what happens if the
  password is wrong? Is there rate limiting? Session timeout?
- `pages/9_API_Discovery.py` and `pages/8_Pipeline_Test.py` — these
  are dev-feeling pages. Are they reachable in production? If yes,
  do they expose internals an attacker could mine for API behavior?

### 4. Cost control & rate limits
ZoomInfo charges per credit. Verify:
- Every API call path is gated by `CostTracker` (cost_tracker.py).
- Test Mode actually skips API calls everywhere it claims to.
- Auto-expansion in Geography Workflow (radius / accuracy / etc.)
  has a clear max-iterations stop; no infinite-retry loops on 429.
- Intent budget (500 credits/week) is enforced, not just displayed.
- ZoomInfo 429 backoff: does it respect Retry-After or use a
  fixed schedule?

### 5. Concurrency, caching, and state
The biggest landmine is in-process caches outliving the data they
mirror (session 51 lru_cache caveat).
- `@lru_cache` on file-loaders: list every one, confirm each is
  intentional and that file change → pod restart is the only path
  to invalidation.
- `@st.cache_resource` / `@st.cache_data`: any caches keyed by
  values that can change without code change?
- `st.session_state` reads where a key might not be initialized.
  The `if "x" not in st.session_state` pattern needs to cover every
  read in every page.
- The "Streamlit rerun guard" pattern (CLAUDE.md "Patterns") — any
  page that inserts into DB without a session-state flag to prevent
  double-insertion on rerun?

### 6. Database schema & queries
- All schema is `CREATE TABLE IF NOT EXISTS` in db/_schema.py. Are
  there migrations for schema changes after the table was first
  created? (Spoiler: the pattern is "ALTER if columns missing" —
  verify every column added later has its migration.)
- Indexes: are there any obvious WHERE / ORDER BY columns without
  indexes? `grep -n "CREATE INDEX" db/_schema.py`.
- The `staged_exports` table is the hottest write path. Check for
  N+1 queries against it.
- `db/_operators.py::search_operators` already uses SQL-level
  pagination — good. Are there other places loading 3K+ rows into
  Python and filtering there?

### 7. Test coverage and quality
- Run `python -m pytest tests/ --co -q | wc -l` to confirm 775.
- Run `python -m pytest tests/ --collect-only -q 2>&1 | head -50` to
  see test organization.
- Coverage gaps to look for:
  • Headless scripts (run_intent_pipeline.py, run_zoho_operator_sync.py)
    are they tested at all, or only smoke-imported?
  • Pages have very few tests by Streamlit convention, but the
    business-logic helpers extracted from pages should be tested.
    Find any logic still inlined in pages/*.py that should be lifted.
  • Tests with hardcoded numeric expectations that would break under
    correct future data (e.g., the 42k assertion we fixed in session 51).
- Look for `@pytest.skip` or `@pytest.xfail` decorators — every one
  needs a current reason.

### 8. Dead code, drift, and TODOs
- `grep -rn "TODO\|FIXME\|XXX\|HACK" --include="*.py"` — read every
  hit. Many will be legitimate; some will be forgotten.
- Imports never used: `python -m pyflakes *.py db/*.py pages/*.py
  scripts/*.py`.
- Functions defined but never called: this is hard to check perfectly
  but worth a pass with `grep` on suspicious-looking helpers.
- Comments that reference old behavior ("used to be X" — anywhere?).
- Anywhere the CLAUDE.md still claims something the code no longer
  does, or vice versa.

### 9. Recent change pressure (sessions 50-51 specifically)
The most recently shipped work has had the least time to surface bugs.
Pay extra attention to:
- RunLogger instrumentation (`db/_pipeline.py`, page integrations) —
  any orphaned run records? Status transitions correct in error paths?
- Cross-session export dedup (commit 6ed765f) — `export_dedup.py` —
  edge cases when company_id is missing or duplicated.
- Census ZCTA centroid replacement (commit 32bf351) — any tests or
  hardcoded ZIPs in the codebase that now miss?
- Phone column re-mapping (commit 32bf351) — was the change picked up
  by both the Streamlit pages AND the headless intent pipeline export?
- Zoho operator sync scheduled (commit 3a8802b) — does the script
  handle a stale refresh token gracefully? Does it run once per day
  without overlap if the prior run is still going?

### 10. UX / operator trust (Streamlit pages)
Not a code-quality dimension strictly, but bugs in operator trust
land in your inbox the same way:
- Every place a number is shown (lead count, credits, ZIPs in radius)
  — does it survive an empty/None case without breaking the layout?
- Error states: does every `try/except` in a page lead to a useful
  `st.error()` message, not just "Operation failed"?
- The "auth gate" page should mention that the app is being audited
  / under maintenance only if it actually is.

## Files / surfaces to read carefully

Priority order — read top to bottom:
1. `app.py`, `utils.py`, `errors.py`
2. `zoominfo_client.py`, `zoho_client.py`, `vanillasoft_client.py`
3. `export.py`, `export_dedup.py`, `dedup.py`, `scoring.py`
4. `expand_search.py` (Geography auto-expansion)
5. `db/` — every mixin (_core, _schema, _operators, _staged, _pipeline,
   _outcomes, _error_log) — 13 files total
6. `pages/1_Intent_Workflow.py`, `pages/2_Geography_Workflow.py` (long files)
7. `pages/4_CSV_Export.py`
8. `pages/10_Automation.py`, `pages/11_Pipeline_Health.py` (newest UI)
9. `scripts/run_intent_pipeline.py`, `scripts/run_zoho_operator_sync.py`
10. `.github/workflows/*.yml`

Skip on first pass (low risk per LOC):
- `_bmad/` (vendored framework, not HADES code)
- `docs/briefing/build_complexity_pdf.py` (build script)
- `tests/` (read alongside the file they cover, not standalone)
- Test fixtures and mock data

## Time-boxing

A thorough review of this codebase realistically takes 4-8 hours
of focused work. If your session budget is tighter:
- 30 min: just dimension 1 + dimension 2 (correctness + error handling)
- 90 min: + dimension 3 (security) + dimension 9 (recent change)
- 4+ hr: all dimensions

Always finish a dimension before starting another. Partial findings
across all 10 dimensions are less useful than complete findings on
the top 3.

## Deliverable

A single markdown report with this shape:

```
# HADES Code Review — <date>

## Summary
- N total findings: P0=<n>, P1=<n>, P2=<n>, P3=<n>
- Top 3 risks (one-line each)

## Findings

For each finding:

### [P0/P1/P2/P3] Title — file:line
**What:** one-paragraph description of the issue
**Why it matters:** concrete failure mode and operator impact
**Evidence:** code snippet OR command + output OR test that would fail
**Suggested fix:** approach, not full code (this is review, not implementation)
**Related:** other findings or sessions this connects to
```

Severity rubric:
- P0 — data loss, security exposure, or operator-visible failure
  shipping today; must fix before next deploy.
- P1 — silent correctness bug not yet observed; fix within 1 week.
- P2 — tech debt with no current user-facing symptom; fix opportunistically.
- P3 — style, naming, minor inefficiency; backlog.

## Constraints

- DO NOT modify code in this session. Read-only mode.
- DO NOT run network calls (no `gh`, no API hits) — local inspection only.
- DO NOT spawn parallel subagents for this; one cohesive reviewer voice
  produces a better report than 5 parallel scans stitched together.
- DO mention beads / `bd create` candidates inline, but don't create them
  — the beads DB state is unresolved (see session 51 handoff). Just list
  the issues so a human can decide.
- Verify the test suite still passes BEFORE starting
  (`python -m pytest tests/ -q | tail -3`). If it doesn't, that's
  finding #1 and the review pauses until it does.

## Complementary tools

This prompt is for a holistic, human-judgment review. For diff-based
per-PR review use the existing CodeRabbit integration
(`/coderabbit:code-review`). For security-specific review use
`/security-review` against the diff. The whole-codebase pass is
something neither of those does well.
