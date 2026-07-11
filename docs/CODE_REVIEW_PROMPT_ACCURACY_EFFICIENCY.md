# HADES Whole-Project Code Review — Accuracy & Efficiency

> Paste this entire prompt into a fresh Claude Code session opened at
> `/Users/boss/Projects/HADES`. It assumes full tool access (Read, Grep, Bash,
> subagents) — this is NOT a paste-the-codebase prompt; you will read the code
> yourself.

---

## Role and mission

You are conducting a thorough, adversarial code review of the entire HADES
codebase (~21k LOC Python, 840 passing tests). Two lenses only, in priority
order:

1. **Accuracy** — code that computes, filters, matches, scores, or persists the
   *wrong thing* while appearing to work. Wrong-answer bugs outrank crash bugs:
   a crash gets noticed; a silently mis-scored or silently dropped lead costs
   revenue invisibly. This app's entire failure history is silent-failure
   class (see `docs/HARDENING_LEDGER.md`, `docs/INCIDENT-2026-06-15-blank-enrichment.md`).
2. **Efficiency** — wasted ZoomInfo credits (credits = real money), wasted
   Turso round-trips, O(n²) hot paths, redundant API calls, cache misuse.
   Efficiency findings matter most where they scale with lead volume or burn
   the weekly credit budget.

You are **not** fixing anything in this pass. You produce a prioritized,
evidence-backed findings report. No style nits, no rewrites, no "consider
using dataclasses" — every finding must name a concrete wrong output or a
concrete quantified waste.

## Project context (cold-start brief)

- Streamlit multi-page app: query ZoomInfo → score leads vs ICP → dedup →
  export to VanillaSoft (CSV or push API). ~5 sales reps use it daily on
  Streamlit Community Cloud.
- Stack: Python 3.13, Streamlit, Turso/libsql (cloud SQLite), ZoomInfo REST
  (OAuth JWT), VanillaSoft Incoming Web Leads (push-only XML), Zoho CRM.
- Architecture map: `CLAUDE.md`. DB is mixin-based under `db/`. Pages under
  `pages/`. Headless automation in `scripts/run_intent_pipeline.py` (GitHub
  Actions, cron).
- Budget reality: ~500 intent credits/week; a bug that re-queries or
  re-enriches needlessly burns money. Exports are 25–100 leads/batch.

## Ground rules

- **Evidence or it didn't happen.** Every finding cites `file:line`, states
  the failure scenario (concrete input/state → concrete wrong output), and is
  labeled **CONFIRMED** (you traced the full path / wrote a throwaway repro)
  or **PLAUSIBLE** (strong reading, unverified). Findings you cannot state a
  failure scenario for do not go in the report.
- **Adversarially verify before reporting.** For each candidate finding, try
  to refute it: re-read callers, check whether a guard upstream already
  handles it, check whether a test already pins the behavior. Kill anything
  refuted. Target: zero false positives at P0–P2.
- **Don't trust docs or comments — trust code.** CLAUDE.md and docstrings
  have drifted before (e.g. `exclude_org_exported` is documented as an API
  param but is cache-keying only).
- **Run the suite first** (`python -m pytest tests/ -q`) to confirm the
  baseline is green before you start; run it again at the end to confirm you
  changed nothing.
- Read-only pass: no production DB access, no live API calls, no code edits.

## Known scar tissue (bug classes with prior incidents — hunt for siblings)

1. **Silent truncation/omission** — Contact Search page-cap truncation shipped
   silently (HADES-4u2); blank enrichment shipped silently (2026-06-15
   incident). Look for any code path that catches-and-continues, returns
   partial results without flagging, or caps/limits without surfacing it.
2. **Messy ZoomInfo data** — IDs arrive as int OR str (`str()` coercion
   required before dict keys); numerics arrive as `"95%"` / `"5.0 miles"`;
   ZIPs arrive as 4-digit, 9-digit, `"75201-1234"`, `"75201 1234"`. Any parse
   without defensive coercion is a finding. Check every `.get()` chain that
   feeds arithmetic or keying.
3. **Streamlit rerun traps** — `st.file_uploader` returns a reused BytesIO
   with retained read position (must `seek(0)`); DB inserts need
   session-state rerun guards or they double-insert. Audit every page for
   side effects that run on rerun.
4. **Config/constant drift** — the 180-vs-365 dedup window lived hardcoded in
   5 places (HADES-fqw). Grep for magic numbers duplicated across
   pages/scripts/signatures that encode one business rule.
5. **`lru_cache` staleness** — `load_config`, `_get_fuzzy_threshold`,
   `get_dedup_days_back`, `geo.load_zip_centroids` are process-lifetime
   cached. Verify nothing mutates what they return (a cached mutable dict
   mutated by a caller poisons every later reader).
6. **API format contract** — all ZoomInfo search params must be
   comma-separated STRINGS, never arrays; `state` is REQUIRED. Verify every
   param builder.

## High-risk hotspots (allocate depth here)

| Area | Files | What to interrogate |
|---|---|---|
| Scoring math | `scoring.py`, `calibration.py`, `calibrate_scoring.py` | Weight normalization sums to 1? Clamps? Score of missing field = 0 or skewed? Intent vs geography weight sets applied to the right workflow? |
| Geo math | `geo.py`, `utils.py` (ZIP maps) | Haversine correctness, ZIP normalization at every entry point, state derivation from ZIP-3, radius=0 semantics when sending explicit ZIP lists |
| Dedup chain | `dedup.py`, `export_dedup.py`, `db/_outcomes.py` | Key construction (`phone\|company`) — what collides? what never matches? Fuzzy threshold false-match risk; O(n²) `find_duplicates`/`merge_lead_lists` at 100+ leads; SQLite `date('now')` is UTC — window boundary drift; name-normalization asymmetry between write path and read path |
| ZoomInfo client | `zoominfo_client.py`, `expand_search.py` | Pagination completeness, retry/backoff double-spend of credits, token refresh races (client is shared — thread-safety was patched once, verify), dedup-by-personId across expansion rounds, cache keying vs actual request params |
| Export path | `export.py`, `vanillasoft_client.py`, `pages/4_CSV_Export.py` | 31-column contract, XML escaping, per-lead POST failure handling (partial-batch semantics: what is recorded in `lead_outcomes` when lead 40/80 fails?), round-robin owner assignment fairness |
| DB layer | `db/_core.py`, `db/_schema.py`, all mixins | execute-per-row vs batch (N round-trips to Turso is network, not local SQLite), missing indexes for actual query patterns, `INSERT OR IGNORE` masking real failures, migration/schema drift vs queries |
| Automation | `scripts/run_intent_pipeline.py`, `.github/workflows/intent-poll.yml` | Headless path diverging from UI path (two implementations of one pipeline = drift), credit budget enforcement actually blocking, failure alerting reachability |
| Cost tracking | `cost_tracker.py`, `db/_usage.py` | Are credits counted where they're actually spent? Under-counting = silent budget overrun |
| Pages | `pages/*.py` (esp. 1, 2, 4) | Rerun side effects, session-state key collisions between workflows, stale `st.session_state` carried across searches |

## Efficiency-specific checklist

- Count Turso round-trips per user action on the hot paths (search → dedup →
  stage → export). Each `execute` is a network call. Flag per-row loops.
- Find every ZoomInfo call that can fire twice for the same data (rerun
  without guard, retry after partial success, cache key mismatch).
- `find_duplicates` and `merge_lead_lists` are O(n×m) with a fuzzy scorer in
  the inner loop — measure/estimate at realistic n (100 leads × 365 days of
  outcomes) and say whether it matters or not. If it doesn't, say so.
- Flag any `load_config()`-style call inside a per-lead loop that isn't
  cached.
- Do NOT report micro-optimizations (string concat, comprehension vs loop)
  unless they sit on a hot path with measured impact.

## Method (phased; use subagents for parallel coverage)

1. **Map** (30 min): read `CLAUDE.md`, `docs/HARDENING_LEDGER.md`, skim every
   module's docstring + public surface. Build the actual data-flow graph:
   search → score → dedup → stage → export → outcomes.
2. **Deep read by subsystem**: fan out parallel review agents, one per
   hotspot row above, each returning findings in the evidence format. Give
   each agent the relevant scar-tissue classes to hunt.
3. **Cross-cutting passes** (sequential, whole-repo greps): rerun-safety
   audit of all pages; every `except` block (what is swallowed?); every
   default-parameter constant (drift check); every `date/datetime/'now'`
   (UTC vs local); every `lru_cache` (mutation check).
4. **Adversarial verification**: for each candidate finding, a fresh pass
   (or agent) attempts refutation. Kill or confirm. Where cheap, write a
   5-line throwaway repro under scratchpad — never into `tests/`.
5. **Report.**

## Output contract

- Write the full report to `docs/CODE_REVIEW_<date>-accuracy-efficiency.md`.
  Chat gets only a summary table + file path (long output rule).
- Report structure: executive summary (≤10 lines) → findings ranked by
  severity, each with: ID, severity (P0 data-loss/wrong-data-in-prod …
  P4 polish), CONFIRMED/PLAUSIBLE, `file:line`, failure scenario, suggested
  fix direction (one line, no patches).
- File `bd create` issues for every CONFIRMED finding at P2 or higher
  (`--type=bug`, description = failure scenario + file:line). Do not file
  PLAUSIBLE ones — list them in the report only.
- End with a coverage statement: what you did NOT review and why, so the
  next session knows the blind spots. Silent partial coverage in a review
  about silent failures would be ironic.
- Do not commit anything except the report file (and beads state) —
  and only after the suite is green.
