# HADES Hardening Ledger

Durable state for the silent-failure hardening campaign (epic **HADES-zz6**,
driver `docs/HARDENING_PROTOCOL.md`). One row per audited surface. Each pass
updates this file so recursion never redoes settled work.

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

---

## Surface audit log

| # | Surface | Status | Modes found / fixed / ruled-out | Beads |
|---|---------|--------|----------------------------------|-------|
| 1 | ZoomInfo Contact Enrich | ✅ done | Fieldless-match → blank leads + uniform 64 score, backfill lost. Fixed: pid stamp (C2) + `contact_has_core_data` filter + fail-loud banner (C1/C3). Force-fail tests added. | HADES-mcx |
| 2 | ZoomInfo Contact/Company Search | ⬜ | | |
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

## Newly discovered surfaces (append as found)

_(none yet)_

---

## Escalated to humans (operational / account — not code)

- **ZoomInfo enrichment credit / entitlement** — root *trigger* of the 2026-06-15
  incident. Code now degrades gracefully + fails loud, but full data requires the
  account to be confirmed/topped up. Owner: Andre. (See HADES-mcx notes.)

---

## Campaign summary (filled on stop)

_(pending first autonomous sweep)_
