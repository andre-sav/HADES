# HADES Code Review — 2026-05-18

## Summary

- **9 findings**: P0=0, P1=2, P2=5, P3=2
- **Test baseline**: 775 / 775 passing
- **Scope reviewed**: dimensions 1, 2, 3, 4, 5, 6, 9 from `CODE_REVIEW_PROMPT.md`. Dimensions 7 (test coverage), 8 (dead code), and 10 (UX) deferred — partial findings on a hard dimension are less useful than complete findings on the dimensions that landed here.
- **Overall posture**: solid. The codebase shows clear evidence of prior security/correctness audits (PII canary tests, hmac-safe password compare, parameterized queries, exception-handling work from sessions 48-49). Remaining issues are tactical, not structural.

### Top 3 risks

1. **`zoho_sync.sync_outcomes` interpolates `batch_id` into a COQL query without validation** (P1 — injection vector if batch_id is ever attacker-controllable).
2. **`@lru_cache` on `get_zips_in_radius` retains stale radius results across in-process file updates** (P1 — second-order effect of the centroid replacement landing without pod recycle).
3. **`zoho-operator-sync.yml` lacks a `concurrency:` group** (P2 — daily sync overlapping with an in-flight prior run is possible; harmless today, painful when the sync grows).

---

## Findings

### [P1] COQL injection vector in `sync_outcomes` via unvalidated `batch_id` — `zoho_sync.py:373-378`

**What:** `sync_outcomes()` builds a COQL query by f-string interpolating `batch_id` directly into a `WHERE HADES_Batch_ID = '{batch_id}'` clause. Unlike the incremental-sync timestamp interpolation in the same file (line 117-124, which validates via `datetime.fromisoformat`), this path has no validation or escaping.

**Why it matters:** `batch_id` today is generated internally and is well-formed UUID-like text, so today this is theoretical. But the field is a `TEXT` column in `lead_outcomes`, populated from values that flow through external systems (VanillaSoft response, future Zoho-originating data). If any of those become attacker-influenced — directly or via a future feature that allows operator-entered batch labels — the query becomes injectable. The sibling code path *already validates* its interpolated value; this one should too, by the same rule of consistency.

**Evidence:**
```python
# zoho_sync.py:117-125 — DOES validate:
ts = modified_since.replace("Z", "+00:00")
parsed = dt.fromisoformat(ts)
zoho_timestamp = parsed.isoformat(timespec="seconds")
query = f"select {fields_str} from Accounts where Modified_Time > '{zoho_timestamp}'"

# zoho_sync.py:373-378 — DOES NOT validate:
query = (
    f"select Deal_Name, Stage, Closing_Date, HADES_Batch_ID "
    f"from Deals "
    f"where HADES_Batch_ID = '{batch_id}'"
)
```

**Suggested fix:** Reject any `batch_id` that doesn't match the expected pattern (`^[A-Za-z0-9_-]{1,64}$` or similar) before interpolation. Or, if COQL supports it, switch to a parameterized form. Belt-and-suspenders: log + skip + alert on validation failure.

**Related:** Session 49 silent-failure audit hardened other paths in this file; this one was missed.

---

### [P1] `get_zips_in_radius` `lru_cache` retains stale results across file replacement — `geo.py:61`

**What:** `get_zips_in_radius` is decorated `@lru_cache(maxsize=64)`. Combined with the same decorator on `load_zip_centroids`, this means that once a `(center_zip, radius)` pair has been computed in a Python process, the result is frozen for the lifetime of that process — even if `data/zip_centroids.csv` is replaced on disk.

**Why it matters:** Last week's centroid fix (commit `32bf351`) shipped a replacement CSV. Streamlit Cloud's standard deploy-on-push restarts the pod, so production should be fine, but two scenarios silently keep stale data:
1. A pod that fails to recycle on the centroid commit but does pick up later code-only deploys would keep the old broken cache forever.
2. Anyone running the app locally and editing `zip_centroids.csv` (e.g., to test a custom dataset) will keep seeing old results until they kill the process.

It's also a sharper version of the deployment caveat already documented in `CLAUDE.md`'s new Deployment section — the lru_cache caveat applies to the *radius-result* cache, not just the centroid-load cache.

**Evidence:**
```python
# geo.py:11-12
@lru_cache(maxsize=1)
def load_zip_centroids() -> dict[...]: ...

# geo.py:61-62
@lru_cache(maxsize=64)
def get_zips_in_radius(center_zip: str, radius_miles: float) -> tuple[dict, ...]:
    centroids = load_zip_centroids()   # this call hits the cached centroid dict
    ...
```

**Suggested fix:** Add a sentinel that ties the cache key to the CSV's mtime, OR expose `.cache_clear()` calls on both functions and call them in `load_zip_centroids` when the file mtime changes, OR drop the lru_cache on `get_zips_in_radius` and rely on `load_zip_centroids` caching alone (the haversine math is fast). The third option is cleanest — `get_zips_in_radius` runtime is ~ms even with no cache because the centroid dict is already cached. Update the Deployment section in CLAUDE.md to reflect whichever path is taken.

**Related:** session 51 (centroid replacement), the existing CLAUDE.md Deployment note.

---

### [P2] Scheduled Zoho operator sync workflow has no `concurrency:` group — `.github/workflows/zoho-operator-sync.yml`

**What:** The new daily sync workflow lacks a `concurrency:` block. GitHub Actions does *not* serialize same-name workflow runs by default; if a daily run overruns past 24 hours (full resync of a large Zoho tenant, or a transient API hang), the next day's run starts in parallel against the same Turso DB.

**Why it matters:** Two concurrent `sync_operators` runs can step on each other — both reading "existing operators" simultaneously, then both trying to insert the same new records. The `zoho_id UNIQUE` constraint will catch the duplicate inserts, but failed transactions on busy paths can leave the DB in an awkward state and the workflow logs in `failed` state, which masks the real first-run success.

**Evidence:** No `concurrency:` key anywhere in the workflow YAML. Same omission in `intent-poll.yml` — but that one has only 15 min timeout vs. 10 min here, and the operator sync is more I/O bound.

**Suggested fix:** Add to the workflow YAML:
```yaml
concurrency:
  group: zoho-operator-sync
  cancel-in-progress: false
```
`cancel-in-progress: false` because mid-sync cancellation could leave the DB partially updated; better to queue.

**Related:** commit 3a8802b (today's sync workflow).

---

### [P2] No retry / circuit-breaker on Zoho refresh-token failure in the scheduled job — `scripts/run_zoho_operator_sync.py:64`

**What:** The headless sync script catches `Exception` broadly and exits 1. If the Zoho refresh token expires (Zoho rotates them every ~6 months unless the integration is "live") or if Zoho's auth endpoint is briefly down, every daily run starts failing silently and there's no notification path. GitHub Actions will email the workflow owner on workflow failure, but only after the workflow has already failed — not on the first warning.

**Why it matters:** The same class of bug as "manual sync feels stale" that drove this whole investigation. A scheduled sync that has been silently failing for two weeks is functionally identical to "sync was never wired" from an operator's POV.

**Evidence:**
```python
# scripts/run_zoho_operator_sync.py:62-65
try:
    result = run_sync(db, auth, force_full=force_full)
except Exception:
    logger.exception("Zoho operator sync failed")
    return 1
```

**Suggested fix:** Two complementary moves:
1. Add a Slack/email/Sentry hook in the workflow `on: failure:` block (`intent-poll.yml` already has SMTP secrets wired — reuse the pattern).
2. Differentiate auth errors from other errors and exit 3 specifically for auth (`ZohoAuthError`) so a future alerting layer can route differently.

**Related:** the broader observation in dimension 2 — silent failures in scheduled jobs are uniquely costly because nobody reads the logs proactively.

---

### [P2] `export_dedup.get_previously_exported` silently drops competing normalized-name matches — `export_dedup.py:32`

**What:** When two different company records share the same normalized name (e.g., "ACME Corp" and "ACME, Inc." both normalize to "ACME"), only the first one encountered by the loop ends up in `by_name`. Since the SQL query orders rows by `exported_at DESC`, the "winner" is the most recent — usually correct, but the loop comment says "first match wins" rather than naming the recency property explicitly.

**Why it matters:** The fallback path (name match when `company_id` is missing on the incoming contact) can match against an operator-irrelevant historical export, suppressing a lead that should have been pushed. Low frequency but real for common-name companies.

**Evidence:**
```python
# export_dedup.py:28-33
for cid, meta in exported.items():
    name = meta.get("company_name", "")
    if name:
        normalized = normalize_company_name(name)
        if normalized and normalized not in by_name:
            by_name[normalized] = meta
```

**Suggested fix:** Either (a) keep all collisions in a list and have `filter_previously_exported` decide which to match against, or (b) add a comment that calls out the recency-wins property explicitly and adds a debug log when a duplicate-normalized-name collision is dropped. (b) is the cheap step; (a) is the right step if the data shows real lead suppression.

---

### [P2] Geography Workflow exempts itself from `check_budget` — `pages/2_Geography_Workflow.py:1826`

**What:** Geography Workflow only calls `cost_tracker.log_usage(...)` after the fact; it never calls `cost_tracker.check_budget("geography", ...)` before spending credits. Today this is by design (`config/icp.yaml` documents the geography budget as unlimited), but the asymmetry with the Intent workflow (which both checks AND logs) creates a footgun.

**Why it matters:** If the geography budget ever becomes finite — even temporarily, to throttle a runaway operator — the change requires not just config flip but also a code change to wire `check_budget` in. The current code has no place where that wiring would live.

**Evidence:** Compare `pages/1_Intent_Workflow.py:461` (`budget_status = cost_tracker.check_budget("intent", 100)`) with the absence of any `check_budget` call in `pages/2_Geography_Workflow.py`.

**Suggested fix:** Wire `check_budget("geography", expected_credit_estimate)` immediately before the enrich call (the only credit-spending step in Geography). When budget is unlimited, `CostTracker.check_budget` should return an "OK, no limit" status that the page renders as `0 credits` like today; when a limit is set, it gates. Make the gate behavior live in cost_tracker, not in the page.

---

### [P2] `staged_exports.operator_id` has no index — `db/_schema.py:157`

**What:** `db.get_recent_operator_ids` reads `SELECT DISTINCT operator_id FROM staged_exports WHERE operator_id IS NOT NULL ORDER BY created_at DESC LIMIT 5`. With only an `idx_staged_created` on `created_at`, the query scans rows but doesn't have a covering index for the `operator_id IS NOT NULL` filter. At today's scale (90-day retention, small operator count) the scan is fast; once retention grows or staged_exports grows it'll regress.

**Why it matters:** Runs on every render of the Geography Workflow "Existing Operator" picker. Latency creep here shows up as a slower page load for the operator dropdown.

**Suggested fix:** Add `CREATE INDEX IF NOT EXISTS idx_staged_operator_created ON staged_exports(operator_id, created_at DESC) WHERE operator_id IS NOT NULL` (partial index, supported by SQLite/libsql).

---

### [P3] Auth rate limit is per-session, not per-IP — `utils.py:39-62`

**What:** `require_auth()` tracks `_auth_failed` and `_auth_locked_until` in `st.session_state`. An attacker opening a new browser tab gets a fresh counter and bypasses the lockout. Hmm, `compare_digest` is still timing-safe so this is purely about brute-force speed, not credential leak.

**Why it matters:** Behind Streamlit Cloud's TLS + the password gate's complexity (presumably high-entropy), the practical exploit window is small. The external code review in session 47 already flagged this and intentionally deferred — captured here for completeness.

**Suggested fix:** Track failed attempts by IP via a small `auth_failures` table keyed on `(ip, hour_bucket)`. ~30 lines. Defer until either threat model shifts or login-bot activity is observed in Streamlit Cloud logs.

**Related:** session 47 external review.

---

### [P3] `_bmad/` is vendored under the project tree, slowing greps and scans — `_bmad/`

**What:** The vendored BMad framework lives at `_bmad/` under the project root. Every `grep -rn ... --include="*.py"` and every IDE indexer scans it. The leading underscore stops most pattern matches but not all (e.g., `find . -name '*.py'` picks it up).

**Why it matters:** Pure papercut. Slows whole-repo searches and makes "is this file part of HADES?" ambiguous for new readers.

**Suggested fix:** Move `_bmad/` outside the project tree (it appears to be tooling, not runtime), or add it to `.gitignore` if it's reproducible, or document its purpose in CLAUDE.md so its presence isn't confusing. Don't act on this until the deferred BMad workflow direction is decided.

---

## What I did NOT find (and looked for)

- **No `st.write(st.secrets)` / `st.json(st.secrets)` leaks** in any page or script.
- **No bare `pass` in `except` clauses** outside intentional cleanup paths.
- **No raw f-string user input in DB queries** — DB layer uses parameterized queries throughout.
- **No mixed-ID-type bugs**: every `companyId`/`personId` comparison in the codebase coerces to `str()` first.
- **No missing `try/except` around credit-spending paths.**
- **No orphan-`run_id` exits**: every place that sets `st.session_state.geo_run_id` / `intent_run_id` has a matching `None` reset on close, and session 51's commit `b2eb562` already added exception-path closure.
- **No hardcoded ZIP-count or specific ZIPs** in production code that would break under the new Census centroid data (the assertion test fixed in session 51 was the only such reference).
- **No exposure of dev pages in production**: `pages/8_Pipeline_Test.py` and `pages/9_API_Discovery.py` are both gated by `DEV_MODE` secret + `require_auth()`.
- **PII sanitization is well-tested**: `tests/test_pii_canary.py` covers every `PipelineError` subclass.
- **Auth uses `hmac.compare_digest`**: timing-safe.

## Bead candidates (to file once beads DB state is resolved)

| Title | Priority |
|---|---|
| `sync_outcomes` COQL injection vector — validate `batch_id` before interpolation | P1 |
| `lru_cache` on `get_zips_in_radius` retains stale radius results — drop or wire mtime invalidation | P1 |
| Add `concurrency:` group to `zoho-operator-sync.yml` | P2 |
| Wire `on: failure:` alerting to scheduled workflows (intent-poll + zoho-operator-sync) | P2 |
| Surface name-normalization collisions in `export_dedup.get_previously_exported` (debug log or list-of-matches) | P2 |
| Wire `check_budget` into Geography Workflow with no-op "unlimited" status | P2 |
| Add partial index on `staged_exports(operator_id, created_at)` | P2 |
| IP-based rate limit on auth gate (deferred per session 47) | P3 |
| Decide on `_bmad/` location (vendor / .gitignore / document) | P3 |

## Methodology notes

- 4 priority dimensions completed (1, 2, 3, 9), 3 sampled (4, 5, 6), 3 deferred (7, 8, 10).
- Read-only; no code edits in this session.
- Test suite verified passing both at start and as the implicit invariant throughout — every claim above is consistent with the green test state.
- No `gh` calls, no network probes, no parallel subagents — single reviewer voice per the prompt's constraints.
- Recent-change focus (dimension 9) covered RunLogger lifecycle, export_dedup edges, phone-mapping integration through `build_vanillasoft_row` in both Streamlit pages AND `scripts/run_intent_pipeline.py`, and Zoho operator sync.
