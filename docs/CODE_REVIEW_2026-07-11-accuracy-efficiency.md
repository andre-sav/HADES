# HADES Whole-Project Code Review — Accuracy & Efficiency

**Date:** 2026-07-11
**Method:** 9 parallel deep-read agents (one per subsystem + cross-cutting sweeps), each attempting refutation before reporting, followed by an independent adversarial verification pass on every P0/P1 and key P2 claims. Baseline: 840 tests green before and after (review is read-only).
**Driver:** `docs/CODE_REVIEW_PROMPT_ACCURACY_EFFICIENCY.md` · Tracking: HADES-3dd

---

## Executive summary

- **2 confirmed P0s.** (1) Any non-Latin-1 character (en-dash, smart quote) in any lead field **crashes a VanillaSoft push mid-batch**, and the already-pushed leads are recorded nowhere — guaranteed future CRM duplicates. (2) Intent contact scoring looks up company intent scores by **hashed** intent ID while contacts carry **numeric** IDs — the lookup misses for 100% of contacts, so the 60%-weighted intent component is a **constant 50 for every lead**. Intent ranking has never worked as designed.
- **11 confirmed P1s**, dominated by two themes: **silent lead loss in dedup/state handling** (franchise false-matches, stale cross-search session state, CSV exports invisible to dedup) and **the June blank-lead incident being fixed only on the Geography path** — the intent UI and the daily cron have no guard, and the purpose-built monitor (`evaluate_enrichment_batch`) is dead code.
- **The alerting layer is currently a no-op.** With SMTP unconfigured, the health check computes "critical" verdicts and exits 0 green. Budget-exceeded skips and resolution failures also report "success."
- **Credit spend is gated and counted in the wrong places**: unlogged resolution enrichments, container-counting, and no budget check at the point where credits are actually spent (`enforce_budget` is dead code).
- Efficiency findings are secondary but real: ~6 Turso round-trips + a 3K-row operators fetch per widget interaction on the hottest page; duplicate no-op expansion searches; ~38 schema round-trips every hour.
- Positives worth noting: the recent 365-day dedup centralization is genuinely correct; token refresh locking, retry/backoff, rerun push-guards, auth gating on all pages, and haversine math all survived scrutiny.

**Verdict labels:** CONFIRMED = mechanism verified by execution or full path trace during this review. PLAUSIBLE = strong code reading, unverified trigger frequency or live API semantics.

---

## P0 — wrong data / data loss reaching production invisibly

### R-01 · VanillaSoft push crashes mid-batch on non-Latin-1 text; partial push recorded nowhere → guaranteed CRM duplicates
**CONFIRMED (executed)** · accuracy · `vanillasoft_client.py:84,114-125` · `pages/4_CSV_Export.py:502-535`
Lead 41/80 contains "Manager – Facilities" (en-dash — routine in ZoomInfo titles). `_build_xml` produces a Python `str`; `requests` passes str bodies through unencoded (verified: `PreparedRequest.body` is `str`); `http.client` encodes as latin-1 and raises `UnicodeEncodeError` — which is a `ValueError`, not a `requests.exceptions.RequestException`, so none of `push_lead`'s three except clauses catch it. The exception escapes `push_leads`, the page script dies **before** the outcome-recording block: zero `lead_outcomes` rows, no `mark_staged_pushed`, no summary. The 40 already-POSTed leads exist in VanillaSoft; the next export re-pushes all 80 → 40 duplicate CRM records. Secondary: latin-1-encodable non-ASCII (é, ®) is silently sent as latin-1 bytes with no charset declaration → mojibake in the CRM.
**Fix direction:** encode the XML body as UTF-8 bytes with an XML declaration; catch `Exception` per-lead in `push_lead`; record outcomes for succeeded leads even when the batch aborts.

### R-02 · Intent contact scoring: company_scores keyed by hashed IDs, contacts carry numeric IDs — 60%-weighted component is a constant 50
**CONFIRMED (reproduced + independently re-verified)** · accuracy · `scoring.py:373-381` · `scripts/run_intent_pipeline.py:245-250` · `pages/1_Intent_Workflow.py:1612-1618`
Intent search returns hashed company IDs (the reason Step-3 hashed→numeric resolution exists). `company_scores` is built from pre-resolution intent leads (hashed keys); contact search then runs with resolved numeric IDs, so `company_scores.get(str(company_id))` misses for every contact. Consequences: `_company_intent_score` = default 50 for all (60% of composite), `_intent_topic` masked by fallback, `_intent_age_days` = 999, company-level SIC/employee backfill never fires. Ranking is silently driven only by authority/accuracy/phone. Both UI and headless paths affected. Existing tests exercise the exact miss path but never assert the component value. Mitigant: intent pipeline live-testing has been blocked by 429s, so this may predate any real-world use — which is exactly why it must be fixed before the live test.
**Fix direction:** re-key `company_scores` by numeric ID after resolution (the `numeric_map` already exists), or carry the hashed ID onto contacts.

---

## P1 — silent lead loss / wrong scores / dead alerting

### R-03 · Export dedup name-fallback fires even when the contact has a valid, DIFFERENT companyId — same-name franchises silently dropped
**CONFIRMED** · accuracy · `export_dedup.py:62-69`
Code is `if cid and cid in by_id: … elif company_name:` — the name fallback runs whenever the ID merely *doesn't match*, contradicting the module docstring ("when no company_id"). "Planet Fitness" Fort Worth (cid 222) is filtered because "Planet Fitness" Dallas (cid 111) was exported last quarter. The ICP is franchise-heavy (hotels, gyms, schools, senior living). A present-but-unknown companyId is *proof* the company was never exported — the name fallback should be `elif not cid`. An existing test (`test_export_dedup.py:83-98`) pins the buggy behavior with a name that contradicts its own comment.
**Fix direction:** `elif not cid and company_name:`; fix the mispinned test.

### R-04 · Raw ZoomInfo ZIP skips the haversine → proximity (40% of geography score) silently fabricated as 15 mi
**CONFIRMED** · accuracy · `pages/2_Geography_Workflow.py:1789-1796` · `scoring.py:165-178`
`contact_zip in centroids` is tested on the raw `zipCode` — ZIP+4 ("75201-1234"), int, and 4-digit forms (all documented messy patterns) miss the 5-char-string keys, `distance` is never set, and scoring assumes 15 mi for everyone, displaying `_distance_miles: 15.0` as if real. `utils.normalize_zip` exists and handles every variant — it just isn't called here. This block is the *sole* distance source (searches send explicit ZIP lists with radius=0, so the API returns no distance).
**Fix direction:** `normalize_zip()` both ZIPs before lookup; treat unresolvable ZIP as a visible data warning, not a silent default.

### R-05 · ZIP prefix 201 (Northern Virginia) mapped to "DC" — small-radius NoVA searches send state=DC and return zero results
**CONFIRMED (labels proven by execution; API AND-semantics assumed)** · accuracy · `utils.py:389` · `data/zip_centroids.csv` (45 rows)
`range(200, 206) → "DC"` is wrong: DC is 200xx/202-205xx; **201xx is exclusively Virginia**. Executed repro: `get_zips_in_radius("20147", 5.0)` (Ashburn VA) → states `['DC']` → API gets `state=DC` + VA ZIPs → zero results, territory looks empty. At larger radii VA sneaks in via 220xx but state counts/exports stay wrong. Also mislabeled: 06390 (Fishers Island NY → CT), 733xx (Austin TX → OK). Baked into the CSV by the rebuild script.
**Fix direction:** map 201 → VA (+ the two single-ZIP exceptions), rebuild `zip_centroids.csv`, add prefix tests for 200-205.

### R-06 · Blank-enrichment guard exists only on Geography — intent UI, daily cron, and export layer all ship fieldless leads; the purpose-built monitor is dead code
**CONFIRMED (triple-independently)** · accuracy · `scripts/run_intent_pipeline.py:355-446` · `pages/1_Intent_Workflow.py` (0 references) · `monitoring.py:96` (`evaluate_enrichment_batch`, 0 callers)
The 2026-06-15 incident class (matched-but-fieldless enrich records) replays untouched through the automation path: blank leads score at baseline, export to CSV, email as "25 leads", get staged, **and are recorded in `lead_outcomes` — burning those companies in the 365-day dedup window despite delivering blank rows**. `contact_has_core_data` is called only in `pages/2`. `evaluate_enrichment_batch` was built and unit-tested for exactly this signature (HADES-1d3) and is called by nothing.
**Fix direction:** apply the C1 filter in `run_intent_pipeline` and the intent UI; wire `evaluate_enrichment_batch` + `send_alert` into the headless path; add a last-line guard in `export_leads_to_csv`/push.

### R-07 · Missing or messy employee count silently gets the BEST employee score
**CONFIRMED (executed)** · accuracy · `scoring.py:185-190` · `config/icp.yaml:130-133`
`lead.get("employees") or lead.get("employeeCount") or 50` + `int()` fallback 50 — and post-calibration, the 50-100 bucket scores **100** (it scored 40 when the default was written). Missing → 100; `0` → 100; `"500+"`/`"1,200"` → 100 (a 1,200-employee company should score 20 — a 16-point composite swing). The intent path regex-strips digits; geography doesn't. Combined with R-06's company-enrich gap, a whole batch can have this component pinned at max.
**Fix direction:** share the intent path's defensive parse; make "unknown" score the mid/default tier, not the top bucket; regression-test the messy forms.

### R-08 · Score calibration "Apply" silently never takes effect, and is lost on redeploy
**CONFIRMED** · accuracy · `calibration.py:195-229` · `utils.py:74` (`@lru_cache`) · zero `cache_clear` calls in prod code
Applying calibration rewrites `icp.yaml` and reports success, but `load_config` is process-lifetime cached and nothing invalidates it — live scoring keeps the old weights until reboot, while page 7's "Current" column re-reads the file and displays the new ones (undetectable divergence). On Streamlit Cloud the write lands on the ephemeral container FS and vanishes on redeploy. `yaml.dump` also destroys every comment in the file (all calibration provenance). Invalidation must cascade: `dedup._get_fuzzy_threshold`, `dedup.get_dedup_days_back`, and `expand_search` module-level constants also capture cached config.
**Fix direction:** `load_config.cache_clear()` + cascade after apply, plus a loud "restart to fully apply / commit to git to persist" notice; use a comment-preserving writer (ruamel) or store calibration in the DB instead of the yaml.

### R-09 · New search does not invalidate downstream session state — users can export search A's leads believing they're search B's
**CONFIRMED (both workflows)** · accuracy · `pages/2_Geography_Workflow.py:1017-1237` (reset fn called only at :501 operator-change and :1009 Reset) · `pages/1_Intent_Workflow.py:479-726`
Geography: after a completed run, changing radius/filters and clicking Search sets new search-phase keys but never resets `geo_enrichment_done` / `geo_enriched_contacts` / `geo_leads_staged` / `geo_usage_logged` — enrichment is skipped and the Results section re-renders the OLD enriched contacts re-labeled with the NEW search's metadata and distances. Intent: re-running Search B leaves `intent_companies_confirmed`, A's selections and contacts live — Step 2/3 are skipped and A's contacts get enriched/exported under B's query params. Related: `*_leads_staged` is also not reset by "Back to Contact Selection", so re-enriched leads never re-stage and "Load Most Recent" recovery restores the stale first set.
**Fix direction:** call the existing reset functions (minus operator) on every Search click; reset staged flags on Back.

### R-10 · Failed enrichment auto-refires on any rerun — uncontrolled repeated credit spend
**CONFIRMED (flag lifecycle traced)** · accuracy+efficiency · `pages/1_Intent_Workflow.py:1454-1554` · `pages/2_Geography_Workflow.py:1655-1737`
The enrichment gate is `contacts && selected && not done && (autopilot || clicked)`. On `PipelineError`/`Exception` none of the trigger flags are reset, so the next rerun — any widget touch — silently re-executes `enrich_contacts_batch` on the full selection. A flaky API means repeated spend with no user action. Enrichment also runs inline (unlike the two-phase search), so a widget interaction during a long call can start a second concurrent enrich.
**Fix direction:** clear the trigger flags in every except path (mirror the search flow's `intent_search_pending` handling); consider the two-phase pattern for enrichment.

### R-11 · The alerting layer is a no-op while SMTP is unconfigured — critical health verdicts exit green
**CONFIRMED** · accuracy · `scripts/check_zoominfo_health.py:75` (`return 0` unconditional) · `scripts/notify_failure.py:45-47`
Credits at 96% → verdict "critical" → `send_alert` sees SMTP_USER unset, prints "skipping email" to stderr, returns False — ignored — script exits 0 → Actions run green. The system built specifically to warn before the next blank-lead incident (HADES-1d3) currently cannot produce any human-visible signal. SMTP secrets are known-unconfigured (it's in the project's own Next Steps).
**Fix direction:** exit non-zero on critical when the alert channel is unavailable (red run = GitHub's own notification fires); this is also the forcing function to configure SMTP.

### R-12 · CSV-download exports are invisible to dedup and history — recorded nowhere
**CONFIRMED (triple-independently)** · accuracy · `pages/4_CSV_Export.py:477-484`
The download button (the only option when `VANILLASOFT_WEB_LEAD_ID` is unset, and a peer button otherwise) records nothing: no `lead_outcomes`, no `mark_staged_exported`, no `update_query_exported`. Whole batches imported into VanillaSoft manually re-surface in every future search and re-contact inside the 1-year rule — the exact complaint in the rep's audit email. Inverse defect (R-13) on the automation side.
**Fix direction:** record outcomes on download (st.download_button on_click), or an explicit "mark batch exported" step.

### R-13 · Headless pipeline reports success and burns dedup on failures: resolution errors → "success" run; budget-exceeded → silent green skip; outcomes recorded before delivery
**CONFIRMED** · accuracy · `scripts/run_intent_pipeline.py:296-304, 182-189, 440-474`
(a) If company-ID resolution enrichment throws (429/auth/credit exhaustion — the incident shape), the exception is swallowed, and the run completes as **"success"** with 0 leads ("No new intent signals matched filters"). (b) Budget-exceeded runs return before the email block: green run, no email, reps silently get no leads for the rest of the week. (c) Every scored contact is written to `lead_outcomes` at CSV-generation time — before the email attempt; if SMTP fails (or is unconfigured), companies are dedup-blocked for 365 days without any rep ever seeing them, and the staged backup then self-blocks on the Export page ("All leads have been previously exported" + st.stop).
**Fix direction:** complete resolution-failure runs as "error"; send (or at minimum red-flag) budget-skip notifications; record outcomes only after confirmed delivery (email sent or staged-export pushed), or exempt the loaded batch from its own dedup.

---

## P2 — confirmed correctness defects

| ID | Finding | Verdict | Where |
|----|---------|---------|-------|
| R-14 | "Retry Failed" push button is structurally dead: it sits inside a `pop()`-gated block (the click is never observed) and `_vs_retry_rows` has zero readers; the failed-leads panel + CSV vanish on the click, replaced by the green success banner. For non-staged leads the identity of failed leads is unrecoverable. | CONFIRMED | `pages/4_CSV_Export.py:492,588-591` |
| R-15 | Intent cross-session dedup is structurally dead: `filter_previously_exported` runs on pre-resolution leads (hashed IDs) against numeric-ID history — the ID branch can never match; all intent dedup rides exact-name fallback (missing name variants, maximizing R-03 exposure). | CONFIRMED | `run_intent_pipeline.py:226` vs `:442`; same class UI |
| R-16 | Fuzzy threshold 85 produces realistic false matches that DROP leads: measured `north/south dallas fitness`=90.0, `atria/artis senior living`=89.5 (real distinct chains in-ICP). No geo component in the match; cross-workflow exclusion (default ON) drops the lower-scored lead with no operator-visible pairing. | CONFIRMED (measured) | `dedup.py:107`, `pages/4_CSV_Export.py:242-265` |
| R-17 | ZoomInfo cache: `expires_at` stored as local `'T'`-separator ISO, compared lexicographically against UTC space-separator `CURRENT_TIMESTAMP` — `'T' > ' '` means entries on their expiry date stay "fresh" up to ~24h extra (+ tz offset locally); purge under-deletes the same way. | CONFIRMED (executed) | `db/_cache.py:13-48` |
| R-18 | Intent cache key omits `sic_codes`/`employee_min` (which the actual API call sends from config): after an icp.yaml ICP change, week-old results filtered by the OLD criteria replay as fresh cache hits. A correct key builder (`get_query_hash`) exists, unused. | CONFIRMED | `pages/1_Intent_Workflow.py:156-162` vs `:585-591` |
| R-19 | Shared DB singleton across all sessions/threads with no lock; `_in_transaction` is instance-global (one user's transaction makes another user's writes skip commit / interleave); stale-stream reconnect inside `transaction()` replays only the current statement and then commits a **partial** transaction with zero error. | CONFIRMED mechanism / PLAUSIBLE frequency | `db/_core.py:17-89`, `db/__init__.py:48` |
| R-20 | Pipeline runs stuck "running" forever: contact-search and enrichment `PipelineError` handlers never complete the run (the search handler does); success-completion only fires when the results table renders ≥1 filtered row; new searches overwrite `run_id` without closing the old run. Dashboards show 🔄 Running indefinitely; no staleness sweeper. | CONFIRMED | `pages/1:1223,1522,1801-1828`, `pages/2:1063-1074` |
| R-21 | Credit accounting + budget enforcement: ID-resolution enriches (1/company, unbatched) never logged; `credits_used` counts response containers, not validated leads (geography splits correctly, intent doesn't); no budget check at the enrichment step where credits are actually spent; `enforce_budget`/`can_execute_query` are dead code; page-load budget snapshot goes stale over a session. | CONFIRMED | `pages/1:1103-1133,1454+`, `cost_tracker.py:133-173`, `run_intent_pipeline.py:181` |
| R-22 | Home-page freshness badge permanently "Unknown": naive `CURRENT_TIMESTAMP` rows minus `datetime.now(timezone.utc)` raises TypeError on every row, swallowed by `except (ValueError, TypeError)` — a stalled pipeline looks identical to a healthy one on the landing page. | CONFIRMED (executed) | `app.py:92-103,139-149` |
| R-23 | Failed background geography search shows no error: the monitor fragment renders `st.error` then calls `st.rerun()` in the same pass, wiping it; no session key persists the failure (Intent persists `_intent_api_error`; Geography doesn't). The search silently vanishes. | CONFIRMED | `pages/2:1255-1281` |
| R-24 | Step-2 company table: narrowing the Priority/Freshness filters silently drops selections on hidden rows (sync loop rebuilds only from displayed rows); positional `edited_rows` under a stable widget key risks remapping edits to different companies on filter change. | CONFIRMED (loss) / PLAUSIBLE (remap) | `pages/1:964-1014` |
| R-25 | Intent truncation is silent end-to-end: `search_intent_all_pages` has no truncation signal at all (the fixed contact-search bug's sibling); the contact-search flag that DOES exist is read by nobody on the intent path (UI or headless). Operators treat page-capped results as complete. | CONFIRMED | `zoominfo_client.py:716-761`, `pages/1:619,1162`, `run_intent_pipeline.py:318` |
| R-26 | Radius "expansion" is a no-op without a center ZIP (manual-ZIP/template modes): up to 4 byte-identical duplicate sweeps (~20 wasted API calls per search) while the expansion timeline tells the operator a 17.5/20-mile radius was searched. | CONFIRMED | `expand_search.py:80-83,279` |
| R-27 | Geography page fires ~6 sequential Turso round-trips + a full ~3K-row `get_operators()` fetch on **every widget interaction** (~0.5s+ latency each) on the hottest page; `@st.cache_data` unused app-wide; CSV-Export page similarly re-runs the 365-day dedup query per rerun. | CONFIRMED · efficiency | `pages/2:230-519`, `pages/4:279` |

## P3/P4 — confirmed, lower severity (condensed)

**Data quality / correctness:** HTML entities never decoded anywhere (breaks dedup matching at ratio 81.8 < 85 and double-escapes to `&amp;amp;` in the CRM — `dedup.py:55`, `export.py:178`); single-pass suffix stripping order-dependence ("Acme Corp, LLC" vs "Acme Corporation" = ratio 61.5 miss); CSV is UTF-8 without BOM (Excel mojibake; the project's own import side handles this, export doesn't); ASCII control chars serialize into invalid XML sent raw (per-lead VS rejection); push success/failure matched by (name, company) sets when personId missing (mis-recording risk); VS "duplicate" rejections never recorded → company re-attempted forever; round-robin Contact Owner restarts at agent[0] every batch (systematic front-of-list skew, no persisted cursor); `normalize_zip` corrupts 8-digit zero-dropped ZIP+4 into a different valid ZIP ("10011234"→"10011" Manhattan, not Agawam MA); manual-ZIP mode silently discards malformed tokens (no "N skipped" notice); template mode leaks state `"?"` into the API state param; SIC lookup is exact-string with no int/suffix normalization (silent default 40); string `signalScore` silently ignored (differentiation collapses to categorical); scoring weights never validated to sum 1.0 (`score_intent_contacts` also lacks the 100-clamp); calibration employee buckets have no min-sample filter and `calibrate_scoring.py` rescues SIC codes for delivered rows only (upward-biased rates behind the shipped icp.yaml scores); company-enrich done-flag set even in the except branch (transient 429 permanently forfeits SIC/employee for the session; 60% of geography composite pinned to constants while passing the core-data guard); token-persistence failures logged at DEBUG (invisible); Zoho outcome sync is dead code (outcomes never flow back; known-unwired pending CRM field, with latent bugs inside); cron mislabeled 7AM ET (it's 8AM during DST; dashboard countdown hardcodes 7); health-check cron fires at the same instant as the pipeline it's meant to precede; GitHub 60-day inactivity auto-disable would silently stop all scheduled runs (no run → no failure → no alert); `DISTINCT + ORDER BY` returns wrong recent-operators order (reproduced); re-export marks "newest staged row" instead of the row it created; NULL `person_id` rows escape the batch-idempotency index; `exported_at` written in two formats (boundary skew hours-scale); UI/headless drift cluster (max_pages 10 vs 5, no title-pref ranking headless, headless failures never reach the error_log the health page reads); intent UI enriches before cross-session dedup (credits spent on leads later discarded — headless orders it correctly); Ctrl+Enter listener leaks across pages clicking the first primary button (dialog-gated, bounded); intent cache Refresh while results showing wedges the page (no Search, no Reset visible); Run-Now outcome wiped by immediate rerun (invisible failures → re-click → duplicate spend); dead config (`cache.ttl_days`/`enabled` ignored by all callers); `zoho_id` UNIQUE migration is invalid SQLite (latent init crash on old-backup restore); `_execute_multi_row_insert` silently truncates SQL after VALUES (latent upsert-breaker).

**Efficiency:** `init_schema` ≈38 sequential round-trips re-run hourly (cache_resource ttl=3600; old connections never closed); `record_title_selections` 2 round-trips × 25-100 titles in the button path; cache + error-log purges have zero callers (unbounded growth; staged-exports purge IS wired); Automation page calls the GitHub API synchronously per rerun (10s timeout); no `requests.Session` for VS push (~40-60s blocked script for 80 leads; widens the R-01 crash window); count-then-delete purges; person-only sweep fires after target already met.

---

## Ruled out (verified sound — do not re-litigate)

Haversine math and bbox pre-filter (brute-force cross-checked); auth gate on all 11 pages + app.py (hmac + lockout); file-uploader seek fix; rerun double-push guard (`pop` single-fire) and double-staging/usage guards; token refresh locking; Fernet-key failure fallback; per-page 429/5xx retry with backoff + circuit breaker (no page re-fetch double-spend); negative caching (empty results never cached); `last_search_truncated` thread-locality (C5 fixed); 31-column CSV contract (char-for-char verified, test-pinned); Import-Notes injection; `_parse_response` fails safe on HTML; `exclude_org_exported` never sent (docs match code); 365-day dedup window genuinely centralized (this branch's fix verified); schema↔query drift (all 13 mixins audited clean); empty-vs-error DB reads (execute raises; dedup call sites unwrapped — an outage fails loud); Zoho incremental-sync overlap safety; `lru_cache` mutation (all cached returns traced to read-only callers — latent no-copy pattern noted); O(n²) fuzzy at DB scale (never happens; the only fuzzy loops are session-list-sized; `merge_lead_lists` is dead code); 175 `except` blocks enumerated — the remainder judged acceptable with reasons recorded in agent transcripts.

## Coverage statement (what this review did NOT do)

- **No live API/DB verification:** ZoomInfo wire formats (string `signalScore`, `"95%"` prevalence), the `sort_order`-not-sent finding (needs one live page-1 ordering check), VanillaSoft duplicate-rejection semantics, and ZoomInfo's state+zip AND semantics (R-05's zero-results mechanism) are code-verified but not wire-verified. No production Turso queries were run (per policy).
- **Skimmed, not deep-read:** pages 5-9 (dashboards/dev pages — swept for the four cross-cutting patterns only), `ui_components.py` beyond pattern hits (~2.6k display lines), `system-test/` and stray root CSVs (out of scope).
- **Untested claims:** libsql thread-safety internals (R-19's frequency), Streamlit `data_editor` version-specific remap (R-24b), concurrent-enrich interrupt timing (R-10b).
- Test suite re-run after review: **840 passed** — the working tree is unchanged by this review.

## Recommended fix order

1. **R-01 + R-14** (one surface: push robustness + partial-batch truth) — data loss with CRM-duplicate blast radius.
2. **R-02 + R-15** (one root cause: hashed/numeric ID spaces) — fix before the intent live test.
3. **R-06 + R-13 + R-11** (one theme: the automation path must fail loud) — prevents the next silent blank-lead week.
4. **R-03** (one-line dedup fallback fix + test correction) — stops silently discarding franchise leads.
5. **R-04, R-05, R-07** (scoring inputs: normalize ZIP, fix DC prefix, fix employee default).
6. **R-09/R-10** (session-state lifecycle), then R-08 (calibration), then the P2 tail.

*Report generated by the accuracy/efficiency review defined in `docs/CODE_REVIEW_PROMPT_ACCURACY_EFFICIENCY.md`. Raw agent findings (including full ruled-out rationale) are in the session scratchpad `review/` directory.*
