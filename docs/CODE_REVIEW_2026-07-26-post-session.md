# HADES Code Review — 2026-07-26 (post-session sweep)

**Scope:** everything added since the last review — `git diff 23c9e07..HEAD` = **66 files, 3,158 insertions**, spanning PRs #1–#12.
**Method:** 4 parallel domain agents (DB layer / monitoring+scripts / dedup+export / UI+test-quality) + CodeRabbit on the full diff. Every P0–P1 claim below was **manually verified against source by me** before acceptance; agent claims that didn't survive verification are listed under *Rejected*.
**Baseline:** 1100 tests green, CI green, `main` @ `95eaec5`.

---

## Executive summary

**24 verified findings. 15 of them are in code I shipped this session** — including three regressions introduced by fixes from the previous review. The pattern is consistent and worth naming: **every one of the new defects is a "the fix didn't reach all the way" failure**, not a design error. Soft-delete filtered the accessors but not three raw queries. The dedup key fix made phones more likely to populate but left the empty-phone hole open. Batching the ID resolution lost per-item error isolation. This is the same sibling-path gap class the last review flagged — now recurring in the fixes for it.

**Nothing here is currently corrupting data in production**, because ZoomInfo is entitlement-locked and the pipeline is idle. That is luck, not design: several of these fire on the first real run.

---

## P0 — must fix before the pipeline runs again

### N2-01 · Soft-delete leaks into three raw queries, one of which mutates deleted rows nightly
`pages/3_Operators.py:63`, `:83` · `zoho_sync.py:197` · **VERIFIED**
Soft-delete (PR #10) filtered the accessor methods in `db/_operators.py` but three raw `FROM operators` queries elsewhere were missed:
- `:63` header count and `:83` synced count include deleted operators — on the very page that owns delete/restore.
- **`zoho_sync.py:197` is the serious one.** Its unfiltered fetch feeds `existing_by_zoho_id` and `all_names`, so (a) the nightly cron's batch `UPDATE ... WHERE zoho_id = ?` **keeps rewriting soft-deleted operators**, breaking the "frozen and recoverable" guarantee while they're invisible in every UI; and (b) a live Zoho record whose name matches a soft-deleted operator is silently skipped as a duplicate **forever** — the headless path never reaches `find_deleted_operator_by_name`.
**Fix:** add `WHERE deleted_at IS NULL` to all three; for zoho_sync, branch soft-deleted matches into a restore/relink path.

### N2-02 · Empty-phone dedup key still bypasses the state veto (the hole c6q aimed at)
`dedup.py:130-146`, guard at `:209` · **VERIFIED**
`get_dedup_key` returns `"|companyname"` when no phone resolves. The guard is `if key == "|"` — it only catches leads with *neither* phone nor company. `"|planet fitness"` passes it and is treated as a **tier-1 exact match**, and `states_conflict()` is consulted only in the fuzzy branch (`:282`, `:405`).
**Two same-name franchise locations in different states, both phone-less, still silently merge** — precisely the HADES-u1x class. PR #3 reduced the frequency (more phones populate) without closing the hole.
**Fix:** guard on `key.startswith("|")`, or force the state veto for phone-less keys. Call sites: `:206`, `:250/257`, `:329/344`, `:382/392`.

### N2-03 · Sentry's PII scrubber is dead code, and the active path is unscrubbed
`observability.py:71-84, 110-121` · **VERIFIED — and this corrects a claim I made**
`scrub_event()` only redacts `event["extra"]`. **Grep finds zero `set_extra`/`set_context` call sites in the repo** — the scrubber can never fire. Meanwhile `sentry_sdk.init()` passes no `integrations=`, so the default `LoggingIntegration` is active: every `logger.error` becomes a Sentry event carrying the formatted message and exception `.value` verbatim, and `logger.info/warning` become breadcrumbs. None of that passes through `before_send`.
**Current exposure is nil** — I grepped every `logger.*` call and they all log counts (`len(leads)`, batch ids), never lead contents. What actually protects PII is `include_local_variables=False` + `send_default_pii=False`, both of which I did verify live. **But my PR #8 description and CLAUDE.md present the scrubber as a live protection, and it is not.** Any future `logger.error(f"...{lead}")` ships PII unredacted.
**Fix:** add a `before_breadcrumb` hook and scrub `logentry.message` + `exception.values[].value`, or disable the auto `LoggingIntegration`. Correct the docs either way.

---

## P1 — wrong behavior on first real run

| ID | Finding | Where | Verified |
|----|---------|-------|----------|
| N2-04 | **Export-volume check will false-alarm every morning from ~day 10.** The workflow runs 07:00 UTC (2–3 AM ET) and compares the *still-forming* UTC day against a 30-day mean of complete days. `today_count` is 0 on essentially every run → `critical` daily → operator learns to ignore the channel, masking a real collapse. My "first run is quiet" care missed that the current day is always incomplete. **Fix:** measure yesterday's completed volume, matching the "vs yesterday" framing the other two checks use. | `scripts/data_anomaly_check.py:97-111` | ✅ |
| N2-05 | **Loading an *intent* staged batch nulls the Geography page's operator.** My N-05 fix sets `geo_operator` unconditionally regardless of `workflow_type`; all three intent staging paths omit `operator_id`, so it always resolves to `None` — clobbering the Geography selection cross-page and firing `_reset_geo_search_state()`, discarding an in-progress search. Regression from PR #2. **Fix:** only write `geo_operator` when `workflow_type == "geography"`. | `pages/4_CSV_Export.py:188-191` | ✅ |
| N2-06 | **One malformed ID aborts the entire company-resolution batch.** My N-17 batching moved `int(numeric_id)` inside a single `try` wrapping the whole loop; the old per-company loop isolated failures. One bad value now leaves every remaining company unresolved. Regression from PR #7. **Fix:** per-contact try/except, continue on invalid. | `pages/1_Intent_Workflow.py:1212-1216` | ✅ |
| N2-07 | **`phone` is misclassified as person-level dedup proof.** `utils.py:653` documents `phone` as the *Business*-phone fallback, and `ZOOMINFO_TO_VANILLASOFT` maps `directPhone`→Business, `mobilePhone`→Mobile, `phone`→(fallback). Treating it as standalone proof is wrong by the same logic that made me require ZIP corroboration for `companyPhone`. Same on the VS side: `phone_business` is folded undifferentiated into `vs_by_phone`. **Fix:** person-level = `directPhone`/`mobilePhone` + VS `phone_mobile`/`phone_home`; company-level (needs ZIP) = `phone`/`companyPhone`/`companyHQPhone` + VS `phone_business`. | `export_dedup.py:19-25, 53-61, 80-84` | ✅ |
| N2-08 | **`claim_pipeline_run` commits outside the connection lock.** `self.execute()` acquires *and releases* the lock, then the `commit()` runs unlocked — violating the HADES-638 contract every other write path in `_core.py` follows on the shared singleton connection. `export.py:57-66` (`generate_batch_id`) has the same pre-existing pattern. **Fix:** wrap the body in `with self.lock:`, or add an `execute_write_returning()` helper. | `db/_pipeline.py:74-89` | ✅ |
| N2-09 | **The 90-day purge orphans the operator attribution soft-delete promised to preserve.** `delete_operator` deliberately keeps `staged_exports.operator_id` intact "so historical exports keep their operator attribution", but there is no FK and `purge_soft_deleted` hard-deletes the operator row — every staged export older than the window is left pointing at a nonexistent operator. **Fix:** denormalize the operator name onto `staged_exports`, or skip purging operators still referenced. | `db/_staged.py:151-173` | ✅ |
| N2-10 | **`zoho_id` UNIQUE has no soft-deleted recovery path.** I added `find_deleted_operator_by_name` for the name collision but `zoho_id` is *also* UNIQUE, and the Zoho upsert is keyed on it — a soft-deleted operator's `zoho_id` blocks re-creation with no way to recover. Compounds N2-01(b). **Fix:** add a `find_deleted_operator_by_zoho_id` companion, or clear/namespace `zoho_id` on soft delete and restore it. | `db/_operators.py:136-178` | ✅ |
| N2-11 | **The test suite opens real TCP connections to `smtp.gmail.com` on every run.** `_make_creds()` supplies real-shaped SMTP creds and three tests drive `run_pipeline()` to the success path unpatched (`test_happy_path`, `test_successful_run_logs_to_db`, `test_contact_scoring_uses_company_intent_score`). The broad `except Exception: email_failed=True` swallows the failure so tests pass, masking it. **Fix:** autouse `conftest.py` fixture patching `smtplib.SMTP`. | `tests/test_run_intent_pipeline.py:33-45` | ✅ |
| N2-12 | **`update_lead_outcome` audits with `before=None`,** so the log only repeats what was passed in — it cannot answer "what was it before", which is the log's entire purpose. The match is on `(batch_id, company_name)` and can touch multiple rows, so a pre-read is also the only way to know how many. **Fix:** pre-read the matching rows and log the real before-state. | `db/_outcomes.py:174-192` | ✅ |
| N2-13 | **`geo_run_id` is cleared even when `complete_pipeline_run` fails,** so my N-07 guard converts a crash into a permanently-`running` row with the reference dropped. **Fix:** retain the session reference on failure so a later attempt can close it. | `pages/2_Geography_Workflow.py:1285-1294` | ✅ |
| N2-14 | **Export-volume floor can go negative,** silently disabling detection: `floor = mean - 2·stdev` is guarded only for `stdev == 0`. A history with genuine zero-export days drives `stdev > mean/2`, so `floor < 0` and `today_count >= 0` always passes. **Fix:** clamp the floor at ≥ 0 (and see N2-04). | `monitoring.py:188-214` | ✅ |

---

## P2 / P3 — latent, robustness, hygiene

- **Blank `ContactID` collapses VS rows.** `contact_id` is `TEXT PRIMARY KEY` + `INSERT OR REPLACE`; `_parse_row` accepts blank IDs, so a future export with a renamed/blank ID column silently collapses thousands of dedup rows into one. The verified 294k file had unique IDs. *Fix: skip+count blank IDs; have the import script compare row growth against `len(parsed.rows)`.*
- **Unparseable `Added Date` drops rows from the dedup window forever.** `added_date=""` and the filter is `added_date >= datetime(...)`; `""` loses lexicographically, so those rows are invisible to dedup. Verified 0 bad dates today. *Fix: sentinel that sorts recent, or treat empty as in-window.*
- **Two `normalize_phone` implementations with different strictness.** `utils` (used by `dedup.py`) doesn't enforce 10 digits; `vs_leads` does. Same conceptual operation, different truth depending on the path. *Fix: consolidate.*
- **`purge_soft_deleted` writes no `mutation_log` entry** — the single most destructive, irreversible operation is the one write path the audit trail can't see.
- **`import_vs_leads.py` and `backfill_exports.py` never call `init_sentry`,** unlike every other headless script (CLAUDE.md convention). The VS import handles 294k rows of contact PII.
- **`backfill_exports.py --all` silently processes only the first 50** staged exports (`get_staged_exports(limit=50)`). Pre-existing.
- **Burst detector fed the newest 500 mutations of *any* op** before filtering deletes; intervening writes can push a real burst out of the window. *Fix: query `WHERE op='delete'`.*
- **Stale `running` pipeline rows are never reconciled** — `claim_pipeline_run`'s window gates new claims but never relabels the crashed row, so dashboards show 🔄 indefinitely.
- **~7 "wiring" tests assert on source-code strings** (`inspect.getsource(...)` / reading a page file and checking a substring). These cannot detect a call that's commented out, moved into dead code, or has its result discarded. **Several are mine from this session.** *Fix: mock the target and assert it's invoked.*
- **One tautological test:** `test_progressive_delay_formula` recomputes `min(2**(attempts-2), 30)` and compares it to itself, never calling `require_auth`.
- **`scores_all_identical` is wired into Geography only,** not Intent — coverage gap, flagged below the defect bar.

---

## Rejected / not accepted

- **CodeRabbit's `_in_transaction` concurrency finding** — cited from the stale `HADES_CODEBASE_FLAT.md` snapshot. `transaction()` holds `self.lock` for its entire body, so instance-level `_in_transaction` cannot interleave. This *was* the HADES-638 fix; already mitigated.
- **CodeRabbit's `str()` ID-coercion finding** — also cited from the flat file; fixed in PR #3.
- **PII in the Pipeline Health mutation panel** — investigated and dismissed. Lead PII is pruned (`leads_json`/`push_results_json`/`query_params`); operator phone/email is sales-team business contact info already visible on the Operators page under the same shared password gate.
- **The stale `HADES_CODEBASE_FLAT.md` polluted this review for the second consecutive time.** It should be deleted from the repo root along with `REVIEW_PROMPT.md`.

---

## Verified sound (do not re-litigate)

`execute_many` rollback ownership · `mutation_log.log_mutation`/`safe_snapshot` genuinely cannot raise · `db/_staged.py` + `db/_operators.py` own list/search/join queries filter correctly on both sides · `purge_soft_deleted` only touches non-NULL `deleted_at` · new timestamps consistently UTC and lexicographically comparable · `resolve_export_operator` implementation and behavioral tests · VS uploader single-read with `file_sig` rerun guard · batched resolution credit counting · background-thread cancellation · `evaluate_mutation_burst` sliding-window math · division-by-zero guards · `inputs.*` on schedule triggers.

---

## Recommended fix order

1. **N2-01, N2-02, N2-07** — data integrity: stop the nightly cron mutating deleted rows, close the franchise merge, fix the phone classification.
2. **N2-04, N2-14** — make the anomaly channel trustworthy before it cries wolf on day 10.
3. **N2-05, N2-06, N2-13** — the three regressions from the previous review's fixes.
4. **N2-03** — Sentry scrubber + correct the overstated docs.
5. **N2-08, N2-09, N2-10, N2-12** — DB layer integrity.
6. **N2-11** and the test-quality tail.
