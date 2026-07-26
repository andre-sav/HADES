# HADES-fpd — Caching & invalidation plan

**Date:** 2026-07-26 · **Status:** plan for review, no code written
**Bead:** HADES-fpd (R-27, deferred once on 2026-07-11 pending an invalidation story)

---

## The decision

**Framed:** add `st.cache_data` to the Geography page's Turso reads.
**Unstated:** whether per-rerun latency is the real problem, or whether the problem is
that the page fetches **3,041 operator rows to populate a dropdown**.
**Status quo option:** leave it. ~300 ms of DB reads per widget interaction.

**Door:** two-way in code (revert the PR), but the blast radius is **not local** —
operator metadata flows into VanillaSoft, an external CRM. Stale values there are
customer-visible, which is why this earns a real interrogation rather than a green light.

## Measured facts (verified 2026-07-26 against production, read-only)

| Fact | Value |
|---|---|
| `operators` rows | **3,041** (all 3,041 Zoho-linked) |
| Full `get_operators()` fetch | median **104 ms**, max 259 ms |
| Small query round-trip (network floor) | median **63 ms** |
| Reads per Geography rerun | 4 (`weekly_usage`, `last_query`, `operators`, `templates`) ≈ **300 ms** |
| Zoho sync writes operators | **raw SQL**, `zoho_sync.py:281/296/311` |
| Zoho sync process | **separate** (GitHub Actions), not the Streamlit process |
| Operator dict → export | snapshotted into `session_state` at pick time (`pages/2:439`), used directly for export metadata (`pages/4:462`) |

**Unverified (hoped):** that ~300 ms is the latency operators actually experience.
All timings above are from a developer laptop. **Streamlit Cloud → Turso latency is
unmeasured** and could be materially different in either direction.

## Lenses that bite

**Delete vs. solve — the big one.** The page fetches all 3,041 operators to fill a
picker. A 3,041-entry `selectbox` is poor UX *regardless of latency*, and
`search_operators(query, limit, offset)` already exists (added in HADES-03x, used by
the Operators page). Replacing the full fetch with the paginated search **removes**
the 104 ms read instead of caching it — and removes the invalidation problem entirely.

**Blast radius & coupling.** The Zoho sync is an out-of-process writer using raw SQL.
No in-process hook — not `st.cache_data.clear()`, not a mixin wrapper — can observe it.
Cache correctness would be bounded *only* by TTL. Any invalidation design that claims
otherwise is wrong.

**Single source of truth.** Operator state already lives in two places: the DB and the
`session_state` snapshot. A cache makes three. Each copy is future drift.

**Severity > probability.** Stale operator name/phone reaching a pushed lead is the
session-46 incident class (wrong operator attribution reached the CRM, reported by
the operator). Low probability, high credibility cost.

**Pre-mortem.** Six months out: *"why did Bob's leads go out with Jane's phone
number?"* Cause: cached list + session snapshot + a mid-session operator edit.
Painful to debug precisely because three copies disagree.

**Cost-of-wrong vs. cost-of-delay.** Delay costs ~300 ms/click (unverified in prod).
Wrong costs bad data in an external CRM plus a three-layer staleness debug. Asymmetric
against caching the operator list.

## The finding that reframes it

**The staleness this bead worries about already exists — without any cache.**

`pages/2:439` copies the whole operator dict into `session_state`; `pages/4:462` reads
export metadata straight off that snapshot. If anyone edits an operator (UI *or* the
nightly Zoho sync) after it was picked, the export already carries stale values. No
TTL, no bound — it persists for the life of the browser session.

So "don't cache, stay correct" is a false comfort. The correctness gap is live today.

## Recommended shape (for review — not yet built)

Ordered by value, and deliberately **not** "add caching":

1. **Re-read the operator by ID at export time** (`pages/4`), replacing the session
   snapshot for the fields that land in VanillaSoft. Pure correctness win, independent
   of any caching, and it closes a live gap. One uncached ~63 ms read at the one moment
   consequence attaches.
2. **Replace the 3,041-row picker fetch** with the existing paginated
   `search_operators()`. Deletes the 104 ms read *and* fixes a bad dropdown. No
   invalidation story needed because there is no cache.
3. **Only then**, if prod latency justifies it, cache the genuinely low-risk reads —
   `get_location_templates`, `get_title_preferences`, budget config — with a short TTL
   (60 s). Staleness there is cosmetic: a template missing from a list for a minute.
   **Do not cache `get_operators`.**

Invalidation contract if step 3 proceeds:
- `st.cache_data(ttl=60)` — TTL is the *only* mechanism that bounds out-of-process writes.
- Explicit `.clear()` on the in-process mutation paths (Operators page create/update/delete).
- Nothing whose staleness can reach VanillaSoft is eligible.

## Risk of this recommendation

I may be over-weighting correctness for a page the team uses daily and experiences as
sluggish. If real Streamlit Cloud latency is 300 ms+ per query, the page costs >1 s per
click and the UX complaint is legitimate — my "just fix the picker" answer would then be
necessary but not sufficient.

## The gating question

R-27 came from code reading, not from a user complaint. Before building anything:

> **Has anyone actually reported the Geography page as slow — or are we optimizing a
> number measured on a developer laptop?**

If no one has complained, step 1 (the correctness fix) is worth doing on its own merits
and the rest of this bead should be closed as speculative. If they have, the cheapest
next evidence is a one-line timing caption rendered on the page in production, which
settles the real latency in a single session.
