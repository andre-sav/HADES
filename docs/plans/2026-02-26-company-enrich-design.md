# Company Enrich Integration

**Date:** 2026-02-26
**Status:** Approved

## Problem

Contact Enrich (`/enrich/contact`) cannot return company-level fields: `sicCode`, `industry`, `employeeCount`. These fields are only available through Company Enrich (`/enrich/company`). Without Company Enrich, the VanillaSoft export has three blank columns: Primary SIC, Primary Line of Business, Number of Employees.

## Discovery

The legacy API has a Company Enrich endpoint at `POST /enrich/company`. Field names differ from Contact Enrich:

| Field Name | Returns | Maps To |
|---|---|---|
| `sicCodes` | `[{"id": "8051", "name": "Skilled Nursing Care Facilities"}]` | Primary SIC (4-digit code from most specific entry) |
| `primaryIndustry` | `["Hospitals & Physicians Clinics"]` | Primary Line of Business |
| `employeeCount` | `144` | Number of Employees |

Note: `sicCode` (singular) and `industry` are disallowed for our account. `sicCodes` (plural) and `primaryIndustry` work.

## Credit Cost

Confirmed via live test: Company Enrich costs **zero additional credits** when the contact at that company was already enriched (company is "under management"). Total cost remains 1 credit per lead, same as the ZoomInfo web portal.

## Design

### New API Method

Add to `zoominfo_client.py`:

- `CompanyEnrichParams` dataclass — `company_ids: list[str]`, `output_fields: list[str]`
- `DEFAULT_COMPANY_ENRICH_OUTPUT_FIELDS` — `["id", "name", "employeeCount", "sicCodes", "primaryIndustry"]`
- `enrich_companies(params)` — single call to `POST /enrich/company`, up to 25 companies
- `enrich_companies_batch(company_ids, batch_size=25)` — batched wrapper

### Field Mapping

After Company Enrich returns data, extract fields and merge onto leads:

- `sicCodes[-1]["id"]` → `lead["sicCode"]` (most specific 4-digit SIC code)
- `primaryIndustry[0]` → `lead["industry"]`
- `employeeCount` → `lead["employeeCount"]`

### Pipeline Integration

Add Company Enrich step to all 3 enrichment paths, after Contact Enrich + merge:

1. **`pages/1_Intent_Workflow.py`** — after Contact Enrich merge, before staging
2. **`pages/2_Geography_Workflow.py`** — same position
3. **`scripts/run_intent_pipeline.py`** — same position

Flow: `Contact Search → Contact Enrich → merge_contact → Company Enrich → merge company fields → Score → Export`

### Backfill Script

Update `scripts/backfill_exports.py` to add Company Enrich step after Contact Enrich.

### Tests

- Unit test for `enrich_companies()` response parsing
- Unit test for SIC code extraction (most specific entry)
- Unit test for Company Enrich batch splitting
- Integration test verifying company fields appear in final merged lead
