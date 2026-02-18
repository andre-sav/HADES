# VanillaSoft Direct Push — Design

**Date:** 2026-02-17
**Status:** Approved

## Summary

Push leads directly to VanillaSoft from the CSV Export page via their Incoming Web Leads endpoint, eliminating the manual CSV download → upload step. CSV download remains as a secondary fallback.

## Architecture

```
build_vanillasoft_row() → dict → vanillasoft_client.push_lead() → XML POST → VanillaSoft
                           ↓
                    (same dict as CSV export — single source of truth)
```

## VanillaSoft API

- **Endpoint:** `POST https://new.vanillasoft.net/post.aspx?id={WebLeadID}&typ=XML`
- **Auth:** WebLeadID embedded in URL (generated in VanillaSoft Admin)
- **Payload:** XML, one lead per request
- **Response:** `<ReturnValue>Success</ReturnValue>` or `<ReturnValue>FAILURE</ReturnValue><ReturnReason>...</ReturnReason>`
- **No batch endpoint** — loop and POST each lead individually
- **No documented rate limits** — use 200ms delay between POSTs as conservative default

## Components

### 1. VanillaSoft Client (`vanillasoft_client.py`)

**`PushResult` dataclass:**
- `success: bool`
- `lead_name: str`
- `company: str`
- `error: str | None`

**`PushSummary` dataclass:**
- `succeeded: list[PushResult]`
- `failed: list[PushResult]`
- `total: int`

**`push_lead(row: dict) -> PushResult`:**
- Takes VanillaSoft row dict (output of `build_vanillasoft_row()`)
- Serializes to XML via `VANILLASOFT_XML_FIELDS` mapping
- POSTs to `post.aspx?id={WebLeadID}&typ=XML`
- Parses XML response for Success/FAILURE
- 10s timeout per request

**`push_leads(rows: list[dict], progress_callback) -> PushSummary`:**
- Loops through rows, calls `push_lead()` each
- Calls `progress_callback(i, total, result)` after each lead
- 200ms delay between POSTs
- Continues on failure (skip and collect)

### 2. XML Field Mapping (`VANILLASOFT_XML_FIELDS`)

Maps VanillaSoft column names → XML tag names (PascalCase):

| VanillaSoft Column | XML Tag |
|---|---|
| List Source | `ListSource` |
| Last Name | `LastName` |
| First Name | `FirstName` |
| Title | `Title` |
| Home | `Home` |
| Email | `Email` |
| Mobile | `Mobile` |
| Company | `Company` |
| Web site | `WebSite` |
| Business | `Business` |
| Number of Employees | `Employees` |
| Primary SIC | `PrimarySIC` |
| Primary Line of Business | `LineOfBusiness` |
| Address | `Address` |
| City | `City` |
| State | `State` |
| ZIP code | `ZIPCode` |
| Contact Owner | `ContactOwner` |
| Lead Source | `LeadSource` |
| Vending Business Name | `VendingBusinessName` |
| Operator Name | `OperatorName` |
| Operator Phone # | `OperatorPhone` |
| Operator Email Address | `OperatorEmail` |
| Operator Zip Code | `OperatorZip` |
| Operator Website Address | `OperatorWebsite` |
| Team | `Team` |
| Call Priority | `CallPriority` |
| Import Notes | `ImportNotes` |

Skipped (always empty): Square Footage, Best Appts Time, Unavailable for appointments.

### 3. Export Page Changes (`pages/4_CSV_Export.py`)

**Button layout:**
```
[📤 Push to VanillaSoft]  [💾 Download CSV]
```

**Push flow:**
1. Click "Push to VanillaSoft" → build rows via `build_vanillasoft_row()` (same path as CSV)
2. Generate batch ID via `generate_batch_id()`
3. Progress bar: `██████████░░░░░░  12/30`
4. Live log: `✔ Name — Company` or `✖ Name — Company (reason)`
5. Completion banner: "25/30 pushed successfully"
6. If failures: failed leads table + [Retry Failed] + [Download Failed as CSV]
7. Auto-records lead outcomes for successful leads (same logic as current "Mark as Exported")

**"Mark as Exported" removed** — pushing is the export action. CSV download is a secondary option that doesn't trigger outcome tracking.

**Push button disabled** when `VANILLASOFT_WEB_LEAD_ID` not configured, with tooltip explanation.

### 4. DB Schema Changes (`staged_exports` table)

New columns:
- `push_status TEXT` — NULL (not pushed), "partial" (some failed), "complete" (all succeeded)
- `pushed_at TEXT` — timestamp of push
- `push_results_json TEXT` — full PushSummary as JSON (for retry/audit)

On retry, only re-push leads from the `failed` list in `push_results_json`.

### 5. Secrets

New secret in `.streamlit/secrets.toml`:
```toml
VANILLASOFT_WEB_LEAD_ID = "..."
```

### 6. Error Handling

| Error | Behavior |
|---|---|
| Network timeout (10s) | Mark failed, continue to next lead |
| HTTP non-200 | Mark failed with status code, continue |
| XML parse error | Mark failed with raw response body, continue |
| VanillaSoft FAILURE | Extract `<ReturnReason>`, attach to PushResult, continue |
| Missing secret | Disable push button, show tooltip |

No automatic retries. User clicks "Retry Failed" to re-push failed leads only.

### 7. Testing

- **Unit tests (`test_vanillasoft_client.py`):** XML serialization, success response parsing, failure response parsing, timeout handling, progress callback
- **All tests mock `requests.post`** — no live VanillaSoft calls
- **Integration coverage:** Push flow on Export page with mocked client, verify progress callback sequence, verify DB column updates

## VanillaSoft Admin Setup

Steps for creating the Incoming Web Lead Profile:

1. VanillaSoft Admin > Integration > Incoming Web Leads > Add
2. Name: "HADES Pipeline"
3. For each XML tag in the mapping table above, create a field mapping to the corresponding VanillaSoft project field
4. Copy the generated WebLeadID
5. Add to `.streamlit/secrets.toml` as `VANILLASOFT_WEB_LEAD_ID`

## What This Does NOT Include

- No Zapier dependency
- No changes to workflow pages (Intent/Geography) — push is Export page only
- No automatic scheduling — push is manual, user-initiated
- No VanillaSoft read/query capability (API doesn't support it)
- No changes to the existing `build_vanillasoft_row()` logic — XML serialization wraps the same dict
