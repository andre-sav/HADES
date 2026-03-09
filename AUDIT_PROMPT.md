# HADES Silent-Failure Audit Prompt

Paste this prompt into a new Claude Code session to run the audit.

---

## Context

You are auditing a Streamlit multi-page app (HADES) for **silent failures** — bugs where code fails but the user sees no error, just missing/wrong data. A production bug was just found where a ZoomInfo Company Enrich API call silently failed on every single export because:

1. A variable (`client`) was assigned inside an `if` block that only runs on one Streamlit rerun cycle
2. A later `if` block (different rerun cycle) referenced that variable
3. The resulting `NameError` was caught by a broad `except Exception` and logged as a non-fatal warning
4. The user saw empty CSV columns with no indication anything went wrong

This class of bug — **Streamlit rerun scoping + broad exception swallowing** — may exist elsewhere. Your job is to find every instance.

## Audit Checklist

### 1. Streamlit Rerun Variable Scoping

Streamlit re-executes page scripts top-to-bottom on every interaction. Variables assigned inside conditional blocks (`if button_clicked:`, `if not st.session_state.X:`) do NOT persist to other blocks on subsequent reruns.

**For each page file in `pages/`:**

- [ ] List every variable assigned inside a conditional block (especially `client`, `db`, API responses, computed data)
- [ ] Check if that variable is referenced OUTSIDE its defining block
- [ ] Check if the defining block and the consuming block can run on DIFFERENT reruns
- [ ] Flag any case where a variable could be undefined when consumed

### 2. Broad Exception Handlers

Find every `except Exception` that could mask real errors:

```
grep -n "except Exception" pages/*.py scripts/*.py *.py
```

**For each one:**

- [ ] What errors could this catch that aren't the intended failure?
- [ ] Would a `NameError`, `TypeError`, `KeyError`, or `AttributeError` here indicate a bug rather than an expected API failure?
- [ ] Is the error surfaced to the user, or only logged?
- [ ] Should this be narrowed to specific exception types (e.g., `except (requests.RequestException, PipelineError)`)?

### 3. Silent Data Loss

Find every place where data flows through a transform that could silently drop fields:

- [ ] `merge_contact()` — does it ever drop fields from search that enrichment doesn't have?
- [ ] `merge_company_data()` — what happens when company_ids don't match? (silent skip)
- [ ] `build_vanillasoft_row()` — what happens when a field key doesn't match `ZOOMINFO_TO_VANILLASOFT`? (silent empty)
- [ ] JSON serialization/deserialization (`save_staged_export` / `get_staged_export`) — do all field types survive roundtrip? (especially nested objects, None vs empty string)
- [ ] DataFrame construction — are any fields silently coerced or dropped?

### 4. Session State Race Conditions

Streamlit fragments (`@st.fragment`) and callbacks can create subtle ordering issues:

- [ ] Check every `@st.fragment` — does it read session state that could be stale?
- [ ] Check every `st.rerun()` — is there session state that should be set but isn't before the rerun?
- [ ] Check every `on_change` callback — does it assume state from a specific execution order?

### 5. API Response Handling

For each ZoomInfo API call:

- [ ] What happens when the response is empty but not an error? (`{"data": [], "success": true}`)
- [ ] What happens when a field is present but null vs. missing entirely?
- [ ] What happens when the API returns a 200 with a partial failure?
- [ ] Are response fields being accessed with `.get()` or with direct indexing? (KeyError risk)

### 6. Test Mode vs Production Divergence

Test mode uses mock data. Check if test mode and production mode follow the same code path:

- [ ] Does test mode skip any steps that production executes?
- [ ] Does test mode execute any steps that production skips?
- [ ] Could test mode mask a bug that only manifests in production?

### 7. Enrichment Output Field Verification

- [ ] What fields does Contact Enrich actually return? Cross-reference against `DEFAULT_ENRICH_OUTPUT_FIELDS`
- [ ] What fields does Company Enrich actually return? Cross-reference against `DEFAULT_COMPANY_ENRICH_OUTPUT_FIELDS`
- [ ] Are there any field name mismatches between API response and what `merge_contact` / `merge_company_data` expect?
- [ ] Does the Enrich API nest fields (e.g., `company.name`) that the code expects flat (e.g., `companyName`)?

### 8. Export Pipeline End-to-End

Trace one lead from search to CSV column, verifying each field:

**Number of Employees:**
- Contact Search → `employeeCount` on contact? or `company.employeeCount`?
- Contact Enrich → field name in response?
- Company Enrich → `employeeCount` in response → `merge_company_data` → lead dict
- `build_vanillasoft_row` → `ZOOMINFO_TO_VANILLASOFT["employeeCount"]` → "Number of Employees"

**Primary SIC:**
- Same trace for `sicCode` / `sicCodes`

**Primary Line of Business:**
- Same trace for `industry` / `primaryIndustry`

**Do this for EVERY VanillaSoft column that has been reported empty.**

## Output Format

For each finding, report:

```
## Finding: [Short title]
- **Severity**: P0 (data loss) / P1 (silent failure) / P2 (cosmetic) / P3 (code smell)
- **File**: path:line
- **Bug class**: [rerun scoping / broad except / data loss / race condition / ...]
- **What happens**: [User-visible symptom]
- **Root cause**: [Technical explanation]
- **Fix**: [Specific code change needed]
```

## What to Run

```bash
# Start with these searches, then read the surrounding code
grep -n "except Exception" pages/*.py scripts/*.py
grep -n "client\s*=" pages/*.py
grep -n "\.get(" pages/*.py | grep -v "session_state\|st\." # Field access patterns
grep -n "st\.rerun()" pages/*.py # Rerun points
grep -n "@st.fragment" pages/*.py # Fragment boundaries
```

Read each page file fully. Don't sample — read every line. The bug we just fixed was 4 lines in a 1900-line file.
