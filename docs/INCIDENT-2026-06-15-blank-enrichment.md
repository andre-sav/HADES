# Incident Analysis — "Hades data coming back blank" (2026-06-15)

**Reporter:** Mike Bigouette (HLM Inside Info — primary Hades operator)
**Surface:** `hades-hlm.streamlit.app/Geography_Workflow`, Step 3: Results
**Symptom:** Results table renders ~28 rows where **every text column is blank**
(Name, Title, Company, City, State, Loc Type) while the **Score column shows an
identical 64%** on every row. Metrics read `CONTACTS ENRICHED 28`,
`PREVIEW FOUND 61`, `COMPANIES 28`.

---

## 1. Root cause (confirmed)

The enriched contact objects reaching the scoring/display stage are **empty
dicts** (no `firstName`, `lastName`, `jobTitle`, `companyName`, `id`, etc.).

### Evidence chain

1. **Uniform 64% is the empty-lead fingerprint.** `calculate_geography_score({})`
   returns exactly `score=64` (proximity 70 ×0.40 + onsite 40 ×0.25 +
   authority 40 ×0.15 + employee 100 ×0.20). A real lead set produces *varied*
   scores (the known-good Feb-26 exports show 76, etc.). Every row at 64 means
   every lead scored is field-less. **This is not a display bug — the data is
   empty at scoring time.**

2. **Direct reproduction.** Feeding empty enrichment objects (`[{}, {}, {}]`)
   through the real `merge_contact()` + `score_geography_leads()` path produces
   exactly the screenshot: every row blank, every score 64.

3. **Search worked, enrichment did not.** `PREVIEW FOUND 61` + the Step-2 review
   table both show that Contact **Search** returned populated records. Only the
   Contact **Enrich** output (`/enrich/contact`) is empty. Search and enrich are
   separate ZoomInfo entitlements/endpoints.

4. **No code regression.** Last commit `82a8cf1` (2026-06-01); the operator was
   using the tool successfully after that. The break is a runtime/data event,
   not a deploy.

### Why even the search-phase names disappeared (the silent-failure defect)

`pages/2_Geography_Workflow.py` is *designed* to backfill search-phase fields
onto enriched contacts via `merge_contact(search_data, enriched)`. That backfill
**fails silently** here:

```python
# pages/2_Geography_Workflow.py ~L1762
pid = str(contact.get("id") or contact.get("personId") or "")  # "" for empty dict
search_data = search_by_pid.get(pid, {})                       # MISS -> {}
enriched_contacts[i] = merge_contact(search_data, contact)     # {} merged with {} -> {}
```

The pairing key is read from the **enriched object that came back**. When that
object is empty it has no id, so the lookup into `search_by_pid` misses, the
good search data is never merged in, and the row is fully blank. The pipeline
then:

- counts the 28 empty objects as `CONTACTS ENRICHED: 28`
  (`zoominfo_client.enrich_contacts` appends `item["data"][0]` whenever the
  `data` list is non-empty — even if `data[0]` is `{}`),
- logs `credits_used = 28` (`cost_tracker.log_usage`, page L1826-1830),
- scores them all 64 and renders a full, authoritative-looking table of blanks.

**The parser already receives the information needed to recover, and discards
it.** ZoomInfo returns each enrich result as `{input, data, matchStatus}`
(noted in code comments at `zoominfo_client.py` L1153, L1181). The code extracts
only `data[0]` and ignores `input` (which carries the **requested personId**)
and `matchStatus`. If `input.personId` were retained, search backfill would
always succeed and the operator would at minimum see search-quality
Name/Title/Company/City/State even when enrichment yields nothing.

---

## 2. Most likely trigger (external)

Search succeeds while enrichment returns matched-but-fieldless records — the
classic signature of a **ZoomInfo enrichment credit / entitlement problem**:

- enrichment credit pool exhausted, or
- the enrich add-on / subscription tier lapsed or changed at renewal.

When this happens, `/enrich/contact` commonly returns HTTP 200 with `result`
items whose `data` payloads are empty, while `/search/contact` keeps returning
basic fields. This matches the observed split exactly.

**This is a hypothesis about the external API.** Confirm with §3 before assuming.

---

## 3. Confirm before acting (operator + logs)

1. **Check ZoomInfo credit balance / enrichment entitlement** in the ZoomInfo
   admin console. HADES also exposes `ZoomInfoClient.get_usage()`
   (`GET /lookup/usage`) — surfaced on the Usage Dashboard page.
2. **Pull Streamlit Community Cloud logs** for the failing run. The client logs:
   - `Enrich raw response keys: [...]`
   - `Enrich response data type: ...` / `Enrich response: result contains N`
   - `Contact Enrich complete: N contacts extracted, M no match`
   and captures the full request/response in `client.last_exchange`. The enrich
   response body will show whether `data` arrays are empty and what
   `matchStatus` / error each result carries (e.g. credit/entitlement message).

---

## 4. Proposed fixes (defense-in-depth — fail loud, degrade gracefully)

Ordered by value. None should ship without first confirming §3 (don't fix the
symptom if the trigger is "buy more credits"); but the silent-failure defects
are worth fixing regardless because they turned a billing event into corrupt,
deliverable-looking output.

**P0 — Stop presenting empty enrichment as valid results.**
Detect when extracted contacts lack core identity fields. If a material
fraction come back empty, surface a blocking banner on the Results step:
*"Enrichment returned no contact data for N/28 records — likely a ZoomInfo
credit/entitlement issue. Check the Usage Dashboard."* Do not render the
blank table as if it were a finished lead list.

**P1 — Preserve search backfill even when enrichment is empty.**
In `enrich_contacts`, carry `item["input"]["personId"]`
onto each extracted contact. (As built: personId only — `matchStatus` has no
downstream consumer, so it was not carried.) In the geo page, key the `search_by_pid` backfill
on that **requested** personId rather than the id returned in the (possibly
empty) payload. Result: operator always sees search-quality
Name/Title/Company/City/State; only the enrich-only fields (verified
email/mobile) are missing when enrichment fails.

**P2 — Honest counts.**
`CONTACTS ENRICHED` and `credits_used` should count only records that came back
with real field data, not empty match objects. Track empties separately
(`N enriched, M returned empty`).

**P3 — Score guard.**
Treat a result set where every lead collapses to the identical baseline score
as a likely upstream-data failure and warn, rather than sorting/displaying it.

---

## 5. Status

- Root cause: **confirmed** (empty enrichment objects → blank rows + uniform 64).
- Trigger: **strongly suspected** ZoomInfo enrich credit/entitlement; pending
  §3 confirmation (operator action).
- Fixes:
  - **P0 + P1 IMPLEMENTED** (TDD, full suite 813 pass) — tracked as `HADES-mcx`.
    - P1: `zoominfo_client._stamp_requested_pid()` carries the requested
      `input.personId` onto fieldless enrich payloads so the geo-page
      search-backfill restores the lead (operator sees search-quality
      Name/Title/Company/City/State even when enrichment returns nothing).
    - P0: `export.contact_has_core_data()` detects fieldless records; the geo
      page filters them out of the deliverable set, shows a blocking
      `st.error` + `st.stop()` when **all** records are empty, and an
      `st.warning` on a partial failure. "Contacts Enriched" metric now counts
      only records with real field data.
  - **P2/P3 still open** (separate, lower priority): honest
    `cost_tracker.credits_used` count excluding empties; score guard for
    all-identical-baseline result sets.
- **Operator action still required:** confirm ZoomInfo enrich credit balance /
  entitlement (§3) — that is the actual trigger; the code fixes make a future
  lapse degrade gracefully instead of shipping blank "leads".
