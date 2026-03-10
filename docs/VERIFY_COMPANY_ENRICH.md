# Verify Company Enrich Fix — Live Smoke Test

## Context

Session 49 fixed a silent-failure bug where Company Enrich retried on every Streamlit rerun due to the done-flag never being set on exception. The fix (across `export.py`, `zoominfo_client.py`, and both workflow pages) ensures:

1. Done-flag is always set after try/except (no retry loop)
2. `enrich_companies` parser handles both list and dict response formats
3. Full tracebacks are logged on failure

**What remains unverified:** Whether the real ZoomInfo Company Enrich API response is parsed correctly by the updated code. Unit tests pass but use mocked responses.

## Task

Run a live Company Enrich call against the real ZoomInfo API and verify end-to-end data flow.

### Step 1: Probe the raw API response shape

Write and run a minimal script (`scripts/verify_enrich.py`) that:

1. Loads credentials via `scripts/_credentials.py`
2. Instantiates `ZoomInfoClient` directly (not via Streamlit cache)
3. Calls `enrich_companies` with 2-3 known company IDs (pick from a recent `lead_outcomes` row or use a well-known company like ZoomInfo's own ID)
4. Prints the **raw** `response` dict from `_request()` — specifically `type(response["data"])` and the first element's structure
5. Prints the **parsed** `companies` list returned by `enrich_companies`

The goal is to see the actual response shape and confirm the parser extracts `id`, `sicCodes`, `primaryIndustry`, `employeeCount`.

### Step 2: Verify merge_company_data

With the parsed company dicts from Step 1, manually call `merge_company_data()` on a small list of mock leads that have matching `companyId` values. Confirm:

- `lead["sicCode"]` is populated (string, not a dict)
- `lead["industry"]` is a string (not a dict — the type-check fix in `export.py`)
- `lead["employeeCount"]` is populated

### Step 3: End-to-end smoke test via Streamlit

Run the Geography Workflow in **test mode** through to results, then:

1. Disable test mode
2. With real enriched contacts, check the logs for:
   - `Company Enrich: merged N companies onto M contacts` → **success**
   - `Company Enrich failed (non-fatal):` with traceback → **diagnose and fix**
3. If successful, check the CSV export preview — SIC Code, Industry, Employee Count columns should be populated

### Step 4: Evaluate and fix

**If the parser works:** Done. Tell the user it's verified.

**If the parser fails:** The traceback will show exactly what `response["data"]` looks like. Update the `enrich_companies` method in `zoominfo_client.py` (lines 1276-1295) to handle the actual shape. Re-run the script from Step 1 to confirm.

**If the API itself returns errors (401/429/etc):** That's an auth or rate limit issue, not a parser issue. The fix is still correct — it just means the API isn't available right now. Retry later.

### Step 5: Clean up

- Delete `scripts/verify_enrich.py` (one-time diagnostic script)
- Run `python -m pytest tests/ -x -q --tb=short` to confirm nothing regressed
- Report results

## Success Criteria

- [ ] Raw API response shape documented
- [ ] `enrich_companies` parser returns non-empty list
- [ ] `merge_company_data` populates sicCode, industry, employeeCount as strings/ints (not dicts)
- [ ] 761 tests still passing
- [ ] Colleague can be told "go ahead" with confidence

## Files Changed in Session 49 (for reference)

- `export.py` — flatten guard, industry type check, logger
- `zoominfo_client.py` — list-format parser, no-match warning, DB init warning
- `expand_search.py` — SearchJob.search_params, traceback logging
- `pages/1_Intent_Workflow.py` — Company Enrich done-flag fix, test mode skip
- `pages/2_Geography_Workflow.py` — Company Enrich done-flag fix, test mode skip
- `db/_schema.py` — re-raise migration failure
- `scripts/_credentials.py` — narrowed exception, logger
- `pages/10_Automation.py` — exc_info=True
- `pages/11_Pipeline_Health.py` — logger.exception
