# Autonomous work order — 2026-07-11 (user away)

> Self-directive for an unattended work session on branch
> `fix/hades-silent-failure-hardening`. Also serves as the handoff document:
> each item is marked ⬜/✅ as it lands. If the session ends mid-list, resume
> from the first ⬜.
>
> **SESSION RESULT (2026-07-11): 12 of 13 items landed** (item 13's five quick
> wins included). Item 12 (R-27 caching) deferred — needs an invalidation
> story for operator mutations; see HADES-fpd notes. Suite: 892 → 924 tests.

## Mission

Work down the remaining P2 findings from `docs/CODE_REVIEW_2026-07-11-accuracy-efficiency.md`
(R-16 … R-27) plus safe P3 quick wins, in the feasibility×risk order below.

## Operating rules (non-negotiable)

1. **TDD**: failing regression test before each fix; full suite (`python -m pytest tests/ -q`)
   green before each commit. One commit per finding (or tight cluster), each
   closing its bd issue with a reason.
2. **Push after every commit** (`git pull --rebase && git push`). Work stranded
   locally is work lost.
3. **No production access** (Turso prod, live ZoomInfo/VS calls) — code + tests only.
4. **Skip, don't block**: anything needing a user decision or a live API check
   gets a bd note and is skipped. Do not ask questions; there is nobody to answer.
5. **No architecture expansions**: HADES-dio (VS lead-history ingestion) and the
   insurance/mutation-log items are design-gated — do not start them.
6. **Stop conditions**: context nearly exhausted or the list is done → update
   this file's checkboxes, update docs/SESSION_HANDOFF.md, commit, push.

## Work queue (in order)

| # | Issue | Item | Approach |
|---|-------|------|----------|
| ✅ | — | Work order written | this file |
| 1 ✅ | HADES-eke | R-22 freshness badge TypeError | Extract a tz-safe DB-timestamp parser to utils (`parse_db_timestamp`), use in app.py freshness/automation badges; naive timestamps are UTC. Tests with real `CURRENT_TIMESTAMP`-format strings. |
| 2 ✅ | HADES-8s5 | R-17 cache expiry format mismatch | db/_cache.py: write `expires_at`/comparisons in one format (UTC, SQLite space format via `datetime('now')` computation in SQL or normalized Python UTC). Fix read filter, `clear_expired_cache`, `get_cache_stats`. Tests pin T-vs-space and tz cases. |
| 3 ✅ | HADES-h83 | R-18 intent cache key omits filters | Move key builder to utils (`intent_cache_key(topics, signals, sic_codes, employee_min, max_pages)`); page 1 uses it. Test: config change → different key. |
| 4 ✅ | HADES-mms | R-25 intent truncation silent | Mirror HADES-4u2: truncation signal in `search_intent_all_pages` (+ `last_search_truncated` set); surface in page 1 (caption/warning) and headless (`run_logger.warn` + summary flag). Client tests. |
| 5 ✅ | HADES-709 | R-23 geo search error flash-wipe | Persist error in `geo_search_error` session key (mirror `_intent_api_error`), render after rerun, clear on new search/reset. |
| 6 ✅ | HADES-mq5 | R-20 stuck 'running' pipeline runs | Complete the run in pages/1 contact-search + enrichment `PipelineError` handlers (mirror the generic-Exception handlers); intent search block completes any prior open run before `start_pipeline_run` (geo already fixed via reset-on-search). |
| 7 ✅ | HADES-1lq | R-26 expansion radius no-op | `expand_search`: skip radius steps when `center_zip` is falsy; note "radius expansion unavailable (manual ZIP mode)" in the expansion log. Tests. |
| 8 ✅ | HADES-c44 | R-24 hidden selections dropped | Page 1 Step-2 sync loop: merge — keep prior selections for companies NOT currently displayed; only displayed rows can change state. |
| 9 ✅ | HADES-0r7 | R-16 fuzzy false-match drops | Fuzzy tier in `find_duplicates`/`flag_duplicates_in_list` additionally requires state agreement when both leads carry a state (different known states = never a fuzzy match). Measured false pairs (atria/artis…) become tests. |
| 10 ✅ | HADES-638 | R-19 DB thread-safety | `threading.RLock` around execute/execute_write/execute_many/transaction in db/_core.py; stale-stream reconnect inside an open transaction raises instead of replaying (partial-commit hole). Tests for the raise path. |
| 11 ✅ | HADES-n7u | R-21 credit accounting | Log resolution enriches to cost tracker (UI per-company loop + headless batch); budget check before enrichment spends (UI both workflows: warn+block when exceeded). |
| 12 ⏭️ deferred | HADES-fpd | R-27 per-rerun Turso fan-out | `@st.cache_data(ttl=60)` wrappers for operators list, templates, title prefs, weekly usage reads on hot pages; session-memo the page-4 dedup lookup keyed on lead-set hash + window. Invalidate operators cache on Operators-page mutations. |
| 13 ✅ | HADES-7qi (partial) | P3 quick wins, only if context allows | (a) CSV utf-8-sig BOM for Excel; (b) wire `clear_expired_cache` + `purge_old_error_logs` into init_schema alongside staged purge; (c) `get_recent_operator_ids` GROUP BY/MAX fix; (d) Automation Run-Now outcome persisted across rerun; (e) pages/10 re-export uses returned staged id. Each tiny, tested, own commit or one grouped commit. |

## Explicitly out of scope (bd-noted, untouched)

- HADES-dio (non-HADES VS lead history) — needs VS export sample + design pass.
- R-19's full connection-pool redesign; the lock is the contained fix.
- HTML-entity normalization changes to dedup matching (behavior shift needs
  operator sign-off — affects what gets filtered).
- Anything requiring live API verification (sort_order transmission, VS
  duplicate semantics).

## End-of-session protocol

1. Checkboxes updated here; brief session note in docs/SESSION_HANDOFF.md.
2. `bd` issues closed/annotated; `git pull --rebase && git push`; verify clean.
