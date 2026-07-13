# HADES Whole-Project Code Review — 2026-07-12

**Method:** 5 parallel deep-read domain agents (API clients / pipeline logic / DB layer / Streamlit UI / scripts+CI) + CodeRabbit on the full `fix/hades-silent-failure-hardening` diff vs `main`, followed by manual verification of every P1-and-above claim against source. Baseline: 953 tests green before review; 956 after (two findings in same-day code were fixed during the review, TDD).

**Context:** This follows the 2026-07-11 accuracy/efficiency review (`docs/CODE_REVIEW_2026-07-11-accuracy-efficiency.md`), whose 2 P0s, 11 P1s, and 9 P2s were all fixed on this branch. This review verifies nothing regressed, checks the fixes themselves, and sweeps for what both passes missed. Findings already known and tracked in the HADES-7qi tail are marked KNOWN, not re-counted.

---

## Executive summary

- **No P0s.** The catastrophic classes from the last review (mid-batch push crashes, dead scoring components) are fixed and stayed fixed. Auth, HTML-escaping, thread/lock discipline, and credential handling all survived independent re-scrutiny.
- **8 verified P1s**, in three themes:
  1. **Dedup key hygiene** — the exact-match dedup key ignores the phone fields contacts actually carry (and its empty-phone fallback bypasses the state veto); ZoomInfo pagination dedup uses un-coerced int-vs-str IDs; `lead_outcomes.exported_at` is written in three different timestamp formats, one naive-local, skewing the 1-year window it anchors.
  2. **The hardening campaign's own edges** — three of the new fail-loud blocks call `complete_pipeline_run` unguarded inside exception handlers (a DB hiccup turns the graceful error into a crash and leaves the run "running"); the budget-skip path is still invisible in two places.
  3. **Enrichment blind spot** — `enrich_companies()` has none of the fail-loud protections its sibling `enrich_contacts()` gained; a blank company-enrich batch (the HADES-1d3 incident class) is still silent on the company side.
- **2 findings were in code written TODAY (HADES-dio VS dedup) and are already fixed** (956 tests green): the phone-match path accepted chain-wide switchboard numbers as dedup proof (franchise false-drop), and ZIP corroboration ignored `companyZipCode`.
- The DB layer's `execute_many` leaves uncommitted statements on the shared connection when a non-stale error hits mid-batch — a later unrelated write silently commits the stragglers.

---

## Fixed during this review (same-session code, HADES-dio)

| ID | Finding | Status |
|----|---------|--------|
| F-A | `export_dedup._match_vs_lead` treated `companyPhone`/`companyHQPhone` (chain-wide switchboard numbers) as unconditional dup proof — every other location of a hotel/nursing/gym chain sharing the HQ number would be silently dropped. | **FIXED**: person-level phones (`phone`/`directPhone`/`mobilePhone`) remain proof on their own; switchboard phones now require exact-ZIP corroboration. Tests added. |
| F-B | VS name-match ZIP corroboration read `zip`/`zipCode` but not `companyZipCode` (false-negative direction). | **FIXED**: fallback chain now mirrors `ZOOMINFO_TO_VANILLASOFT`. Test added. |

---

## P1 — verified correctness defects

### N-01 · `execute_many` leaks uncommitted writes onto the shared connection on non-stale failures
`db/_core.py:156-173` (`_execute_many_fallback`), `:180-213` (`_execute_multi_row_insert_locked`) · **CONFIRMED (code path)**
Both helpers execute multiple statements/batches then commit once. The except path handles only stale-stream errors (rollback+reconnect); any other exception (constraint violation on batch 2, binding error from messy data) re-raises **without rollback**. The earlier statements stay pending on the singleton connection, and the next unrelated `execute_write` anywhere in the app commits them along with itself — phantom partial batches with no error trail. (Process restart before that instead silently discards them.)
**Fix:** mirror `transaction()`'s except→rollback→raise in both helpers.

### N-02 · `lead_outcomes.exported_at` written in three formats — one naive local time
`pages/4_CSV_Export.py:659` (`datetime.now().isoformat()` — naive local, T-separated) vs `export.py:360` and `scripts/run_intent_pipeline.py:575` (UTC, T-separated, offset) · **CONFIRMED**
All three feed the same column that `get_exported_company_ids` compares against `date('now')` for the 365-day dedup window and `get_recent_batches` sorts on. The naive-local writer is hours off UTC; the T-separator itself is the exact drift class HADES-8s5 eliminated for the cache table. Boundary-window leads dedup incorrectly; recent-batch ordering skews.
**Fix:** all three call sites → `datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")` (the `db/_cache.py` / `db/_vs_leads.py` convention).

### N-03 · ZoomInfo pagination/one-per-company dedup keys never `str()`-coerced
`zoominfo_client.py:1052-1057` (`seen_person_ids`), `:1204-1208` (`seen_companies`); also `:1006-1008`, `:1132-1134` · **CONFIRMED**
CLAUDE.md's own rule: IDs may be int or string across responses — coerce before keying. These four sites key sets on raw values while the enrich builders (`:1231`, `:1369`) coerce. Mixed types across pages → the same person/company under two keys → duplicate rows, duplicate enrich credit spend, duplicate leads downstream.
**Fix:** `str()` at all four sites.

### N-04 · `get_dedup_key` ignores `directPhone`/`mobilePhone`; empty-phone exact match bypasses the state veto
`dedup.py:129-138` · **CONFIRMED**
The key reads only `phone` (often absent — `required_fields` is an OR across three phone types) and `Business` (a VanillaSoft CSV column that never exists on raw API dicts, confirmed at the live call sites `pages/4_CSV_Export.py:271,316`). Consequences: (a) phone-based dedup rarely fires → duplicate leads slip; (b) when both sides lack `phone`, keys collapse to `"|companyname"` — and tier-1 exact matches deliberately skip the `states_conflict` veto, so two different-state franchise locations exact-match on name alone and the lower-scored one is dropped/merged.
**Fix:** fall back `directPhone` → `mobilePhone` → `phone` → `Business` (the `ZOOMINFO_TO_VANILLASOFT` priority order).

### N-05 · Staged-export reload silently attributes a manual operator's batch to whatever operator is in session state
`db/_staged.py:12-27` · `pages/4_CSV_Export.py:172-187` · **CONFIRMED**
Manually-entered operators have no DB id → staged rows persist `operator_id = NULL` → "Load Most Recent" restores `geo_operator` only when `operator_id` is truthy, leaving any *leftover* session operator attached. Export/push then tags Jane's territory leads with Bob's name/business/team — the same wrong-operator incident class Mike reported in production (session 46), one page over.
**Fix:** when `operator_id` is absent, explicitly set `geo_operator = None` (or persist the manual-operator dict in `staged_exports`).

### N-06 · `enrich_companies()` fails silent where `enrich_contacts()` fails loud
`zoominfo_client.py:1352-1400` vs `:1288-1306` · **CONFIRMED**
No count-mismatch warning (contacts version logs "N/M had no match"), no fallback parse for flat response shapes. A partially/totally failed Company Enrich returns quietly and SIC/industry/employeeCount — 60% of the geography composite's company inputs — stay blank with zero signal. This is the company-side sibling of the blank-enrichment incident (HADES-mcx/1d3); the contact side is guarded, this side is not.
**Fix:** port the count warning + flat-shape fallback from `enrich_contacts`.

### N-07 · Three new fail-loud blocks call `complete_pipeline_run` unguarded inside exception handlers
`pages/1_Intent_Workflow.py:1322` and `:1642-1656` · `pages/2_Geography_Workflow.py:1926-1930` · **CONFIRMED** (CodeRabbit + manual)
The sibling block (`pages/1:521-527`) wraps the same call in try/except because closing the run is best-effort. In these three (all added in the HADES-mq5/mcx hardening), a DB failure while *handling* a pipeline error propagates out of the except handler — the graceful `st.error`/banner is replaced by a crash and the run stays "running", the exact state the blocks exist to prevent.
**Fix:** wrap all three in try/except + `logger.warning`, matching `:521-527`.

### N-08 · Budget-skip runs are still invisible in two places
`scripts/run_intent_pipeline.py:220-239` · `pages/10_Automation.py:436-450` · **CONFIRMED** (CodeRabbit + manual)
(a) The headless budget-skip wraps `send_alert()` in try/except but discards its boolean — SMTP down means no email, `success: True`, exit 0 (the pattern HADES-2oe fixed for the health check, missed here). (b) The Automation Run-Now result branch never checks `result["error"]`/`budget_exceeded`, rendering budget skips as "Pipeline complete — 0 leads exported".
**Fix:** check the `send_alert` return (fail or at least red-flag the run); surface `result["error"]` in the Run-Now outcome message.

---

## P2 — verified robustness/consistency defects

| ID | Finding | Where | Notes |
|----|---------|-------|-------|
| N-09 | `_loaded_staged_batch_id` set by "Load Most Recent", never cleared — every later export in the session excludes batch X from dedup, letting its companies slip back into new pushes | `pages/4_CSV_Export.py:181,353` (no `pop` anywhere) | Clear it in the workflow reset fns, or scope to the loaded batch's render |
| N-10 | `execute_many` commits unconditionally, ignoring `_in_transaction` — bulk insert inside `with db.transaction():` would silently early-commit | `db/_core.py:160,197` | No current caller does this; API landmine. Thread the flag through or assert |
| N-11 | `ZoomInfoAPIError(status_code=0)` (connection errors, retry exhaustion) marked `recoverable=False`; sibling `ZohoAPIError` treats 0 as recoverable — Pipeline Health shows red/critical for transient blips | `errors.py:66-72` vs `:106-115`; `pages/11:357` | One-line fix + test for status 0 |
| N-12 | Health check: an undeliverable **warning**-severity alert still exits 0 — SMTP outage at 80-94% usage = green runs until 95% | `scripts/check_zoominfo_health.py:61-83` | Apply the critical-path rule to warnings |
| N-13 | UI intent resolution credit logging counts successful resolutions, not enrich responses — under-counts spend vs the HADES-n7u billing rule the headless path implements | `pages/1_Intent_Workflow.py:1174-1215` vs `scripts/run_intent_pipeline.py:343-372` | Mirror the script's `len(enriched)` accounting |
| N-14 | No retention purge for `credit_usage`, `query_history`, `company_id_mapping` (one row per API call, unbounded) — the 7qi purge pattern covers only cache/staged/error_log | `db/_schema.py:230-239` | Extend startup purge (~1yr caps; TTL for the mapping cache) |
| N-15 | Automation page hardcodes dedup fallback `365`, duplicating `get_dedup_days_back()` (this literal already drifted 180→365 once on this branch) | `pages/10_Automation.py:619` | Source from the shared function |

## P3 — minor

- `scripts/backfill_exports.py` never exits non-zero (manual-only today; wire an exit code before it's ever scheduled).
- `zoho_sync.sync_outcomes` stage classification is a substring match — "Not Delivered"/"Undelivered" would record as `delivery`, open deals as `no_delivery`. Dormant (zero callers) and the module is already in the KNOWN tail; new detail worth capturing in that bead.

## KNOWN tail items independently re-confirmed (tracked in HADES-7qi — no new count)

- Headless pipeline neither uses nor trains title preferences (`run_intent_pipeline.py:433-440` vs UI auto-select) — the dominant-volume path is outside the learning loop.
- GitHub cron is UTC-fixed: fires 8 AM ET during DST while the Automation page's DST-aware display promises 7 AM ET (~8 months/yr of hour drift).

## Verified sound (independently re-checked this pass — do not re-litigate)

`require_auth` on all 11 pages · `html.escape` at every `unsafe_allow_html` interpolation of API data · file-uploader `seek(0)`/rerun guards (incl. today's VS import) · geo operator-change reset + background `SearchJob` thread discipline (no `st.*` in worker; RLock honored) · credential handling and workflow-YAML secret wiring (no leakage into logs) · `states_conflict` veto on all fuzzy branches (0r7) · `EMPLOYEE_UNKNOWN_SCORE` bucket non-collision (tow) · hashed/numeric ID bridging scope (oq9/hec) · `normalize_zip` consistency across `utils`/`vs_leads`.

## Coverage statement

- CodeRabbit pass on the full branch diff: 22 findings (10 major / 12 minor); the 5 majors shown above were manually verified; full listing appended below when the capture re-run completes. Overlap with agent findings was high (the `complete_pipeline_run` and budget-skip items were found by both).
- No live API or production-DB verification (per policy). `ZoomInfoAPIError` status-0 frequency, mixed int/str ID frequency, and VS switchboard-phone prevalence are code-verified, not wire-measured.
- Dashboards/dev pages (5-9) were swept for the cross-cutting patterns only, as in the prior review.
- Test suite after review + same-day fixes: **956 passed**.

## Recommended fix order

1. **N-07 + N-08** — one theme (the hardening campaign's own error paths), small diffs, protects the fail-loud guarantees just shipped.
2. **N-02 + N-05 + N-09** — export/dedup state integrity on the CSV Export page (timestamp convention, operator attribution, batch-exclusion leak).
3. **N-04 + N-03** — dedup key hygiene (phone fallback chain + str coercion); both are duplicate-lead/credit-spend leaks.
4. **N-06** — company-enrich fail-loud parity (blank-SIC incident class).
5. **N-01 + N-10** — `execute_many` rollback + transaction contract.
6. P2 tail (N-11..N-15), then P3.

*Raw agent findings: session scratchpad `review/` directory. CodeRabbit full output: appended below / `review/coderabbit-full.txt`.*
