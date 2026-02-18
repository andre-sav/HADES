# HADES - ZoomInfo Lead Pipeline

Streamlit multi-page app for querying ZoomInfo API, scoring leads against ICP criteria, and exporting to VanillaSoft CSV format. Built for a vending services sales team.

## Architecture

```
Streamlit UI → ZoomInfo API → Scoring Engine → Turso DB → VanillaSoft Push / CSV Export
```

**Key Components:**
- **Turso (libsql)** - Cloud SQLite for persistence (operators, cache, usage tracking, staged exports)
- **ZoomInfo API** - OAuth client with retry logic, rate limiting, Contact Search, Intent Search (v2 JSON:API)
- **Scoring Engine** - Weighted scoring based on signal strength, proximity, on-site likelihood
- **Cost Tracker** - Budget controls with weekly caps and alerts

## Session Workflow

**Session Start:**
1. Run `bd ready` to see available work
2. Run `bd list --status=in_progress` to check for incomplete work
3. Read `docs/SESSION_HANDOFF.md` for context from last session

**During Work:**
- `bd update <id> --status=in_progress` before starting a task
- `bd close <id>` when done
- `bd create --type=bug --title="..."` for bugs discovered during work

**Session End:**
1. Update `docs/SESSION_HANDOFF.md` with: what was done, uncommitted changes, next steps
2. `bd sync` to commit beads state

## File Structure

```
HADES/
├── app.py                 # Main Streamlit entry point
├── turso_db.py           # Database connection and CRUD
├── zoominfo_client.py    # ZoomInfo OAuth + API client (Contact Search)
├── scoring.py            # Lead scoring engine
├── dedup.py              # Deduplication logic
├── cost_tracker.py       # Budget controls
├── errors.py             # PipelineError base class and exception hierarchy
├── export.py             # VanillaSoft CSV generation
├── vanillasoft_client.py # VanillaSoft Incoming Web Leads push client
├── utils.py              # Config loading, phone formatting, ZIP-to-state mapping
├── geo.py                # ZIP radius calculations, haversine distance
├── config/
│   └── icp.yaml          # ICP filters, scoring weights, SIC codes
├── data/
│   └── zip_centroids.csv # US ZIP codes with lat/lng/state (~42k rows)
├── pages/
│   ├── 1_Intent_Workflow.py      # Intent signal queries
│   ├── 2_Geography_Workflow.py   # Contact search with manual/autopilot modes
│   ├── 3_Operators.py            # Operator CRUD
│   ├── 4_CSV_Export.py           # Export with operator metadata
│   ├── 5_Usage_Dashboard.py      # Credit usage monitoring
│   ├── 6_Executive_Summary.py    # MTD metrics and trends
│   ├── 9_Automation.py           # Automation dashboard + Run Now
│   └── 10_Pipeline_Health.py    # System health indicators + diagnostics
├── scripts/
│   ├── run_intent_pipeline.py    # Headless intent pipeline (cron/manual)
│   └── _credentials.py           # Credential loader (env → toml → st.secrets)
├── .github/workflows/
│   └── intent-poll.yml           # Daily intent poll (Mon-Fri 7AM ET)
├── tests/                # 492 tests (pytest)
└── docs/
    └── stories/          # User stories with acceptance criteria
```

## Key Configuration

**config/icp.yaml:**
- 25 SIC codes (22 from ZoomInfo account filter + 3 from HLM delivery data)
- Employee range: 50 - 5,000 (starting; expansion may remove upper limit)
- Intent budget: 500 credits/week with alerts at 50%/80%/95%
- Geography budget: unlimited
- Scoring weights: signal_strength 50%, onsite 25%, freshness 25%

**Secrets required (.streamlit/secrets.toml):**
```toml
TURSO_DATABASE_URL = "libsql://..."
TURSO_AUTH_TOKEN = "..."
ZOOMINFO_CLIENT_ID = "..."
ZOOMINFO_CLIENT_SECRET = "..."
VANILLASOFT_WEB_LEAD_ID = "..."  # VanillaSoft Incoming Web Leads profile ID
APP_PASSWORD = "..."              # Password gate for Streamlit Community Cloud (optional for local dev)
```

## Testing

Always run `python -m pytest tests/ -x -q --tb=short` after Python changes before committing. Run the full test suite, not just new tests. The pre-commit hook enforces this automatically.

## Commands

```bash
# Run app
streamlit run app.py

# Run tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_scoring.py -v
```

## ZoomInfo Contact Search API

**Implemented in `zoominfo_client.py`:**

- `ContactQueryParams` dataclass - all search parameters
- `search_contacts()` - Contact Search endpoint
- `search_contacts_all_pages()` - Pagination helper
- `search_contacts_one_per_company()` - Deduplicates to 1 contact per company (highest accuracy score)

**Required Parameters:**
- `zip_codes`: List of ZIP codes to search
- `radius_miles`: Search radius (use 1 for manual ZIP mode)
- `states`: List of state codes - **REQUIRED** (e.g., `["TX", "CA"]`)

**Key Parameters:**
- `locationSearchType`: `PersonAndHQ` (default) - Contact's office AND company HQ must match
  - Toggle: "Include Person-only results" runs both PersonAndHQ + Person searches for maximum coverage
- `sortBy`: `contactAccuracyScore` (default)
- `sortOrder`: `desc` (default)

**Quality Filters (defaults):**
- `companyPastOrPresent`: `"present"` - Only current employees
- `excludePartialProfiles`: `True` - Better data quality
- `required_fields`: `["mobilePhone", "directPhone", "phone"]` - Contact must have at least one phone type
- `required_fields_operator`: `"or"` - OR = any field, AND = all fields
- `contactAccuracyScoreMin`: `95` - High quality threshold
- `companyEmployeeCount`: `{"min": 50, "max": 5000}` - Employee range
- `management_levels`: `["Manager"]` - Target decision-makers (facility managers, operations managers)
- `exclude_org_exported`: `True` - Skip contacts already exported by your org

**Usage Example:**
```python
from zoominfo_client import ContactQueryParams, get_zoominfo_client

client = get_zoominfo_client()
params = ContactQueryParams(
    zip_codes=["75201"],
    radius_miles=25,
    states=["TX"],  # REQUIRED
)
contacts = client.search_contacts_one_per_company(params)
```

## Geography Workflow Features

**Dual Workflow Modes:**
- **Autopilot**: Search → Auto-select best contact per company → Results
- **Manual Review**: Search → Review all contacts → Select per company → Confirm

**Dual Location Search Modes:**
- **Radius (default)**: Enter center ZIP + radius → calculates all ZIPs in radius locally
- **Manual ZIP list**: Paste ZIP codes from freemaptools.com

**ZIP Radius Calculation (geo.py):**
- Calculates all ZIP codes within radius using haversine distance
- Automatically detects state borders (e.g., Texarkana TX → includes AR ZIPs)
- States auto-derived from ZIP list (no manual entry needed)
- Radius options: 10mi, 12.5mi, 15mi (recommended), or custom (1-50mi)
- Expansion may use additional radii: 17.5mi, 20mi (max)
- Sends explicit ZIP list to ZoomInfo API (radius=0) for deterministic results

**Target Contacts with Auto-Expansion:**
- User sets target contact count (default: 25, range: 5-100)
- "Stop early" option: stop expanding once target reached (default: ON for Autopilot, OFF for Manual)
- If target not met, system automatically expands search parameters in this order:
  1. Management levels → +Director → +VP/C-Level (stay in territory)
  2. Employee range → remove 5,000 cap (larger companies)
  3. Accuracy → 85 → 75 (more contacts)
  4. Radius → 12.5mi → 15mi → 17.5mi → 20mi (last resort)
- Results show expansion summary: target met status, expansions applied, searches performed
- Contacts deduplicated by personId across expansion searches

**UI Features:**
- Shows ZIP count and state breakdown before searching
- Visible/editable API parameters
- API request preview with formatted JSON
- Results grouped by company with contact selection
- Quality filters (accuracy, location type, required fields)
- Industry filters (25 SIC codes, full names displayed)
- Target contacts input with expansion summary

## SIC Codes (25 target industries)

```
3531 - Construction Machinery
3599 - Industrial Machinery NEC
3999 - Manufacturing Industries NEC
4213 - Trucking, Except Local               (NEW - 19.0% delivery rate)
4225 - General Warehousing and Storage
4231 - Terminal and Joint Terminal Maintenance
4581 - Services to Air Transportation       (NEW - 27.3% delivery rate)
4731 - Freight Transportation Arrangement   (NEW - 20.0% delivery rate)
5511 - Motor Vehicle Dealers (New and Used)
7011 - Hotels and Motels
7021 - Rooming and Boarding Houses
7033 - Recreational Vehicle Parks
7359 - Equipment Rental and Leasing NEC
7991 - Physical Fitness Facilities
8051 - Skilled Nursing Care Facilities
8059 - Nursing and Personal Care NEC
8062 - General Medical and Surgical Hospitals
8211 - Elementary and Secondary Schools
8221 - Colleges and Universities
8322 - Individual and Family Social Services
8331 - Job Training and Vocational Rehab
8361 - Residential Care
9223 - Correctional Institutions
9229 - Public Order and Safety NEC
9711 - National Security
```

## Geo Module (geo.py)

**ZIP Radius Calculation:**
```python
from geo import get_zips_in_radius, get_states_from_zips

# Get all ZIPs within 15 miles of Dallas
zips = get_zips_in_radius("75201", 15.0)
# Returns: [{"zip": "75201", "state": "TX", "lat": 32.78, "lng": -96.79, "distance_miles": 0.0}, ...]

# Extract unique states ordered by frequency
states = get_states_from_zips(zips)
# Returns: ["TX"]

# Border example: Texarkana TX near AR border
zips = get_zips_in_radius("75501", 15.0)
states = get_states_from_zips(zips)
# Returns: ["TX", "AR"] - automatically includes neighboring state
```

**Data Source:**
- `data/zip_centroids.csv` - ~42k US ZIP codes with lat/lng/state
- Source: GitHub US ZIP codes dataset (MIT license)
- Pure Python implementation using haversine formula (no geo dependencies)

## Patterns & Conventions

- `@st.cache_resource` for database/client singletons
- **Schema is self-creating** — `init_schema()` runs `CREATE TABLE IF NOT EXISTS` on every app start. New tables need no manual SQL or migration scripts.
- **Streamlit rerun guard** — When persisting data in page scripts, use a session state flag (e.g., `intent_leads_staged`) to prevent duplicate DB inserts on Streamlit reruns.
- Session state keys prefixed by workflow: `intent_results`, `geo_results`
- Lead dicts use `_` prefix for computed fields: `_score`, `_priority`, `_lead_source`
- VanillaSoft export has 31 columns (30 standard + Import Notes)

## Related Projects

- **ZVDP** (`/Users/boss/Projects/ZVDP`) - Reference data: field mapping JSON
- **VSDP** (`/Users/boss/Projects/VSDP`) - Functional app with phone cleaning, Zoho CRM integration

## Status

- **551 tests passing** (all tests green)
- ✅ **Contact Search API WORKING** - Verified 2026-02-02
- ✅ **Intent Search API** - Legacy `/search/intent` endpoint (JWT-compatible). v2 `/gtm/data/v1/intent/search` requires OAuth2 PKCE (no DevPortal access).
- ✅ **Target Contacts Expansion** - Implemented 2026-02-03
- ✅ **Shadcn UI Adopted** - `streamlit-shadcn-ui` across all pages
- 🔧 **Contact Enrich** - API returns data, response parsing fixed (needs production test)
- See `docs/SESSION_HANDOFF.md` for detailed debugging context

## API Format Notes (CRITICAL)

All search params must be **comma-separated strings**, not arrays:
- `"state": "TX,CA"` not `["TX", "CA"]`
- `"employeeRangeMin": "50"` not `50`

## External APIs

### Zoho

When working with Zoho APIs: the CRM module name is "Deals" (not "Potentials"), COQL has rate limits — add delays between queries, and always test API calls with proper auth headers before giving POST/GET commands to the user.

### ZoomInfo

All search params must be comma-separated strings, not arrays. Assume data is messy — handle truncated ZIPs (4-digit and 9-digit), missing fields, HTML entities in text, and null values with defensive parsing. Known messy patterns:
- **Mixed ID types** — `companyId`/`personId` may be int or string across responses. Always coerce to `str()` before using as dict keys.
- **Numeric fields as strings** — `contactAccuracyScore` can be `"95%"`, `distance` can be `"5.0 miles"`. Always wrap `float()`/`int()` in try/except with regex fallback.
- **ZIP+4 variants** — `"75201-1234"`, `"75201 1234"`, `"752011234"` all appear. Split/truncate to 5 digits before lookup.

## Next Steps

1. **Live test Intent pipeline** - Search → Select → Find Contacts → Enrich → Export (blocked by 429)
2. **Live test enrichment** - Verify enrich API works with real data
3. **Live test Geography pipeline** - Full end-to-end with real API
4. **Production test UX** - Verify shadcn components, action bar, export validation with real data

---
*Last updated: 2026-02-16*
