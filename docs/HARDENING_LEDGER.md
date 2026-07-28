# HADES Hardening Ledger

Durable state for the silent-failure hardening campaign (epic **HADES-zz6**,
driver `docs/HARDENING_PROTOCOL.md`). One row per audited surface. Each pass
updates this file so recursion never redoes settled work.

> **▶ CAMPAIGN CLOSED 2026-07-27.** All 14 surfaces audited — see the summary at
> the foot of this file. The stale resume pointer that used to sit here (bead
> HADES-6ic, branch `fix/hades-silent-failure-hardening`, "837 tests, not yet
> pushed") was three merges out of date: that branch landed in `main` at
> `23c9e07` and HADES-6ic is closed.
>
> The campaign did **not** finish by running its own loop. Surfaces #3–#14 were
> swept by the two whole-project review cycles (2026-07-11 and 2026-07-26) under
> different bead names, and nobody updated this file — so the epic read as an
> untouched P1 with 12 open surfaces while the work was in fact done. The
> reconciliation below records the evidence. **Operating rules for any instance:
> `docs/WORKING-MODEL.md`.**

Status key: ⬜ not started · 🔶 in progress · ✅ done · 🚫 n/a

---

## Conventions established (prevent the class — grep these everywhere)

- **C1 — Validate content, not just the container.** A 200 response / non-empty
  list is not proof of usable data. Check that load-bearing fields are present
  before counting, scoring, displaying, exporting, or pushing.
  *(from HADES-mcx: `export.contact_has_core_data`)*
- **C2 — Preserve provenance for backfill.** When an external call can return
  fieldless matches, carry the requested key through so search-phase data can
  restore the record instead of rendering blank.
  *(from HADES-mcx: `zoominfo_client._stamp_requested_pid`)*
- **C3 — Fail loud, degrade graceful.** On degraded input: surface an actionable
  operator message; prefer real-but-lower-confidence fallback over blanks; never
  ship empty/degenerate output downstream.
- **C4 — Force-fail tests only.** A test proving "doesn't crash on good input"
  does not count. Feed the bad case; assert it is caught/surfaced.
- **C5 — No unsynchronized shared mutable state on the cached client.** The
  ZoomInfo client is an `@st.cache_resource` singleton shared across sessions and
  background threads. Per-request/per-sweep signals must be thread-local (or
  lock-guarded), never plain instance attributes.
- **C6 — A guard that halts (`st.stop()`/early return) must close out side state
  first.** Before stopping, complete any open pipeline run and clear run-logger
  state, or the run is orphaned in a non-terminal status and re-fires on rerun.
- **C7 — A detector needs an INDEPENDENT oracle *and* a low base rate.** The
  oracle must not be the computation it audits — re-running haversine over the
  centroid table that produced the rows is self-referential, so a collapsed
  centroid reports 0.0 miles and passes. Independence makes a check *meaningful*;
  a low false-positive rate on real data makes it *usable*, and you only learn
  that by measuring. Both are required. A check firing on 15% of rows trains
  operators to ignore it, which is indistinguishable from having no check.
  *(from HADES-av6: independent + 0/60 real searches → shipped. HADES-0n4:
  independent but 15% of rows → closed as not viable.)*
- **C8 — A bead proposing a detector must name the incident record and state how
  the detector fires on it.** Four of four insurance/hardening beads audited on
  2026-07-27 specified a check that could not detect the incident that motivated
  it, because each was written from the *symptom* just after the event rather
  than the *mechanism*. One line at filing time catches this for free.
  *(HADES-0h1, av6, 704, 0n4 — see docs/SESSION_HANDOFF.md 2026-07-27.)*
- **C9 — Verify the monitor can fail before trusting it.** Curl a hostname with
  no app behind it; inject a break and confirm the test goes red. Streamlit
  Cloud's `/healthz` returns 200 `{"status":"ok"}` for apps that do not exist, so
  a check built on it would have been permanently green. A check that cannot fail
  converts "unmonitored" into "confirmed healthy", which is worse than nothing.
  *(from HADES-704.)*

---

## Surface audit log

| # | Surface | Status | Modes found / fixed / ruled-out | Beads |
|---|---------|--------|----------------------------------|-------|
| 1 | ZoomInfo Contact Enrich | ✅ done | Fieldless-match → blank leads + uniform 64 score, backfill lost. Fixed: pid stamp (C2) + `contact_has_core_data` filter + fail-loud banner (C1/C3). Force-fail tests added. | HADES-mcx |
| 2 | ZoomInfo Contact/Company Search | ✅ done | FOUND+FIXED: silent page-cap truncation (`max_pages` stops the sweep before the real last page with no signal → operator trusts a partial "N found" as complete). Now: `_search_was_truncated` + `client.last_search_truncated` (loud warn) → `expand_search` result['truncated'] → geo-page `st.warning`. RULED OUT: 200-but-empty (shows "0 found" — visible); `_request` raises on non-200 so errors aren't swallowed as data. SIBLING TO SWEEP: schema-rename → blank preview fields (same class as enrich; lower risk, operator sees blanks pre-selection). | HADES-4u2 |
| 3 | ZoomInfo Company Enrich | ✅ done | Confirmed silent: `enrich_companies()` had none of `enrich_contacts`' fail-loud protections. Ported. | HADES-7r2 |
| 4 | ZoomInfo Intent pipeline (headless) | ✅ done | Multiple modes found: headless pipeline **reported success on failures** and recorded outcomes before delivery (R-13); blank-enrichment guard existed only on Geography, so intent UI + cron shipped fieldless leads and the monitor was **dead code** (R-06); unguarded `complete_pipeline_run` in 3 error paths + invisible budget-skips (N-07/08, exit 2 on undelivered alert); silent truncation end-to-end (R-25); cache key omitted `sic_codes`/`employee_min` → stale wrongly-filtered results (R-18). | HADES-guz, wr2, tfp, mms, h83 |
| 5 | ZoomInfo auth/token + usage | ✅ done | **Alerting layer was a no-op with SMTP unconfigured — critical health verdicts exited green** (R-11); credit accounting wrong in both directions with no budget gate at the actual spend point (R-21). Daily `check_zoominfo_health.py` covers entitlement. Operational residue (the entitlement itself) is HADES-m29, escalated to human below. | HADES-2oe, n7u |
| 6 | VanillaSoft push | ✅ ruled out | Audited 2026-07-27: already fail-loud by construction. `push_lead` returns a per-lead `PushResult(success, error)`; XML response parsed for per-lead feedback; non-200, timeout, connection error and unparseable XML all map to `success=False`; `push_leads` returns a `PushSummary` carrying the `failed` list. A partial push cannot report success. 27 tests. No fix needed. | — |
| 7 | Zoho client / sync / auth | ✅ ruled out | Audited 2026-07-27: fail-loud path intact — missing env vars logged as error, exceptions via `logger.exception`, non-zero exit propagated by `sys.exit(main())`, and the workflow's `if: failure()` fires `notify_failure.py`. 39 tests. **HADES-jdi is live proof it works**: the sync has been alerting red daily on missing `ZOHO_*` secrets rather than failing silently. Separately, N2-01/02/07 fixed soft-delete leaking into `zoho_sync.py:197`, where the nightly cron kept rewriting soft-deleted operators. | HADES-jdi (operational), gcc |
| 8 | DB layer (Turso/libsql) | ✅ done | `execute_many` swallowed non-stale failures without rollback and ignored `transaction()` (N-01/10); shared-connection thread-unsafety + partial-transaction commit on stale-stream reconnect (R-19); **cache expiry format mismatch served expired entries as fresh for up to ~24h** — exactly the "stale cache served as fresh" mode predicted in this row (R-17); lock/purge-orphaning/`zoho_id`-recovery/audit-before-state (N2-08/09/10/12). | HADES-znl, 638, 8s5, gcc |
| 9 | Scoring (degenerate inputs) | ✅ done | Uniform-score guard `scores_all_identical` (the original smell); **missing/messy employee count silently scored BEST (100)** (R-07); **raw ZoomInfo ZIP skipped haversine so proximity — 40% of the geo score — was fabricated as a flat 15mi** (R-04). | HADES-mcx, tow, 1hw |
| 10 | Export / CSV | ✅ done | CSV downloads were recorded nowhere, invisible to dedup and history (R-12); export-page state integrity — timestamps, operator attribution, batch-exclusion leak (N-02/05/09); dedup name-fallback dropped same-name franchises (R-03); fuzzy threshold 85 false-matched across workflows (R-16). Export operator freshness via `resolve_export_operator` (HADES-fpd). | HADES-rkr, 96q, u1x, 0r7, fpd |
| 11 | Cost tracker / usage logging | ✅ done | The predicted mode confirmed and fixed: counts were wrong in **both** directions and there was no budget gate at the actual spend point (R-21). `credits_used` (what ZoomInfo charged) split from `leads_returned` (deliverables). | HADES-n7u, obn |
| 12 | Streamlit rerun state loss | ✅ done | Richest surface. Failed enrichment **auto-refired on any rerun → uncontrolled repeated credit spend** (R-10); a new search did not invalidate downstream state, so stale leads exported under new labels (R-09); background search failure flashed then wiped (R-23); company-table filter change silently dropped hidden selections (R-24); operator change did not reset results. Convention recorded in CLAUDE.md (session-state rerun guard). | HADES-2xo, aoe, 709, c44, v0r |
| 13 | Dedup / merge | ✅ done | Dedup-key hygiene: phone fallback chain + `str()` ID coercion at 4 sites (N-03/04); franchise over-merge (R-03); fuzzy false-match drop (R-16). VS lead-history dedup added phone-or-name+ZIP with switchboard ZIP corroboration for franchise safety. | HADES-c6q, u1x, 0r7, dio |
| 14 | Calibration | ✅ done | The predicted mode was real but with a different mechanism than guessed: **Apply never took effect** (`lru_cache`) **and vanished on redeploy** (R-08) — calibration was not training on degenerate data, it was silently not training at all. | HADES-zw1 |

---

## Monitoring / alerting (HADES-1d3 — the #1 blind spot, now addressed)

- `monitoring.py` — pure evaluators: `evaluate_usage()` (credit/entitlement
  thresholds; an unreadable signal is "unknown", never "ok") and
  `evaluate_enrichment_batch()` (fieldless-record fraction). Tested, 11 cases.
- `notify_failure.send_alert(subject, body)` extracted as a reusable alert
  channel (CLI `main()` now uses it too).
- `scripts/check_zoominfo_health.py` + `.github/workflows/zoominfo-health-check.yml`
  (daily 12:00 UTC) — the SYSTEM now alerts on credit/entitlement exhaustion
  before the operator sees blanks. Follow-up: wire `evaluate_enrichment_batch`
  into headless `run_intent_pipeline`.

## Newly discovered surfaces (append as found)

- **Adversarial code review of the hardening branch** (bmad-code-review, 3 layers)
  hardened the fixes themselves — patched in-branch:
  - `contact_has_core_data` now counts **phone** (not just name/company/email) —
    a phone-dialing tool must not drop phone-only leads or raise a false
    credit-exhaustion P0 for them. *(reinforces C1: "usable" is workflow-specific.)*
  - `last_search_truncated` made **thread-local** — the client is an
    `@st.cache_resource` singleton shared across sessions/threads; a plain
    attribute raced. *(new C5 below.)*
  - All-empty `st.stop()` now **completes the pipeline run** first (was orphaning
    it in a non-terminal state). *(new C6 below.)*
  - Usage logging split: `credits_used` = full batch (what ZoomInfo charged),
    `leads_returned` = deliverables (post-filter) — kept consistent with the UI.
  - `expand_search` error-return path now carries `truncated`; added propagation
    tests (4 return sites were untested).
  - Deferred: content-side early-stop truncation + multi-sweep number accuracy →
    **HADES-w2t** (needs ZoomInfo empty-page behavior evidence first).

---

## Second-opinion review (Gemini, 2026-06-15)

Independent model review of the incident response. Endorsed the root-cause
diagnosis, the P0/P1 fixes (incl. "backfill+warn is correct, not dangerous —
the failure is in enrichment, not the search data"), thread-local, and
`contact_has_core_data`. Two course-corrections, both now logged as P1:
- **HADES-1d3** — proactive monitoring + alerting is the #1 blind spot (operator
  was the detector). Wire credit-check + degraded-response detection into
  `notify_failure.py`.
- **HADES-fxr** — highest-leverage hardening = recorded-response integration
  tests for P0 boundaries, NOT an open-ended LLM sweep.
- **Sweep guidance:** if continued, narrow to **Auth/Usage (#5)** and **Intent
  pipeline (#4)** next (Search #2 already done); cut the per-iteration
  5-Whys/convention ceremony — consolidate conventions after patterns emerge.

## Escalated to humans (operational / account — not code)

- **ZoomInfo enrichment credit / entitlement** — root *trigger* of the 2026-06-15
  incident. Code now degrades gracefully + fails loud, but full data requires the
  account to be confirmed/topped up. Owner: Andre. (See HADES-mcx notes.)

---

## Campaign summary (closed 2026-07-27)

**All 14 surfaces audited: 12 found and fixed, 2 audited and ruled out clean
(#6 VanillaSoft push, #7 Zoho sync).** Epic HADES-zz6 closed.

**The campaign's stop condition was met, but not by its own loop.** The design
said "loop until 2 consecutive surfaces yield nothing new." What actually
happened is that two whole-project review cycles (2026-07-11, 2026-07-26) swept
surfaces #3–#14 far more thoroughly than the per-surface recursion would have,
filing ~50 beads under their own names. This file was never updated to match, so
for six weeks the epic read as an untouched P1 with 12 open surfaces while the
work was done. **The ledger, not the code, was the stale artifact.**

Worth keeping from that: a durable ledger only works if updating it is part of
closing the work it tracks. A "resume here" pointer that survives three merges
is worse than no pointer — it sends the next instance to a branch that no longer
exists.

### What the sweep actually found

The predicted modes were mostly real, but several had a *different mechanism*
than the row predicted — which is the argument for auditing surfaces rather than
hunting for the guessed bug:

- **#14 Calibration** was predicted to "train on degenerate data silently." It
  was in fact not training at all — Apply never took effect (`lru_cache`) and
  vanished on redeploy.
- **#9 Scoring** was predicted as a "uniform baseline score smell." The worst
  finding was proximity — 40% of the geography score — being *fabricated* as a
  flat 15mi whenever a raw ZoomInfo ZIP skipped haversine.
- **#5 Auth/usage** turned up the highest-severity item of the campaign: the
  alerting layer was a **no-op** with SMTP unconfigured, so critical health
  verdicts exited green. The monitoring built to end the campaign could not
  itself report.

### Residue (tracked elsewhere, not reopening the epic)

- **HADES-m29** (P1) — ZoomInfo entitlement. Operational, escalated to human; the
  root *trigger* of the 2026-06-15 incident. Code degrades gracefully and fails
  loud; the account does not.
- **HADES-jdi** (P1) — `ZOHO_*` GitHub secrets. Operational. Its daily red run is
  the fail-loud path working as designed.
- **HADES-w2t** (P3) — content-side early-stop truncation + multi-sweep number
  accuracy. Deferred pending evidence of ZoomInfo's empty-page behaviour.
- **HADES-7qi** (P3) — ~25 confirmed lower-severity findings from the 07-11
  review.
