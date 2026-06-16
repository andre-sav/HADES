# HADES Hardening Ledger

Durable state for the silent-failure hardening campaign (epic **HADES-zz6**,
driver `docs/HARDENING_PROTOCOL.md`). One row per audited surface. Each pass
updates this file so recursion never redoes settled work.

> **▶ RESUME HERE:** bead **HADES-6ic** is the handoff anchor — branch
> `fix/hades-silent-failure-hardening` (7 commits, 837 tests pass, not yet
> pushed). HADES-fxr ✅ done (focused enrich+search integration tests). Next:
> supervised sweep of Auth/Usage (#5) + Intent (#4). A fresh work instance
> starts there. **Operating rules for any instance: `docs/WORKING-MODEL.md`.**

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

---

## Surface audit log

| # | Surface | Status | Modes found / fixed / ruled-out | Beads |
|---|---------|--------|----------------------------------|-------|
| 1 | ZoomInfo Contact Enrich | ✅ done | Fieldless-match → blank leads + uniform 64 score, backfill lost. Fixed: pid stamp (C2) + `contact_has_core_data` filter + fail-loud banner (C1/C3). Force-fail tests added. | HADES-mcx |
| 2 | ZoomInfo Contact/Company Search | ✅ done | FOUND+FIXED: silent page-cap truncation (`max_pages` stops the sweep before the real last page with no signal → operator trusts a partial "N found" as complete). Now: `_search_was_truncated` + `client.last_search_truncated` (loud warn) → `expand_search` result['truncated'] → geo-page `st.warning`. RULED OUT: 200-but-empty (shows "0 found" — visible); `_request` raises on non-200 so errors aren't swallowed as data. SIBLING TO SWEEP: schema-rename → blank preview fields (same class as enrich; lower risk, operator sees blanks pre-selection). | HADES-4u2 |
| 3 | ZoomInfo Company Enrich | ⬜ | merge_company_data fills gaps silently; check empty/partial company responses → silent SIC/industry blanks | |
| 4 | ZoomInfo Intent pipeline (headless) | ⬜ | scheduled; confirm failures alert (notify_failure) vs vanish | |
| 5 | ZoomInfo auth/token + usage | ⬜ | partial-entitlement degradation (root trigger of the incident); usage endpoint accuracy | |
| 6 | VanillaSoft push | ⬜ | does a partial/failed push report success? | |
| 7 | Zoho client / sync / auth | ⬜ | | |
| 8 | DB layer (Turso/libsql) | ⬜ | empty-read vs error-read indistinguishable; stale cache served as fresh | |
| 9 | Scoring (degenerate inputs) | ⬜ | "uniform baseline score" smell beyond geography (intent, contact) | |
| 10 | Export / CSV | ⬜ | silent column drops, encoding, truncation | |
| 11 | Cost tracker / usage logging | ⬜ | counts containers not validated leads (credits_used counted empties — P2 of HADES-mcx) | |
| 12 | Streamlit rerun state loss | ⬜ | known recurring class (recent Master-upload + Company-Enrich rerun fixes) | |
| 13 | Dedup / merge | ⬜ | over-merge / silent drop | |
| 14 | Calibration | ⬜ | trains on degenerate data silently | |

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

## Campaign summary (filled on stop)

_(pending first autonomous sweep)_
