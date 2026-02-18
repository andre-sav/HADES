# Why HADES Takes Time to Build Right

**For:** Damione
**Date:** February 18, 2026

---

## The Short Version

HADES looks like "a search tool with some buttons" from the outside. Under the hood, it's a full-stack application that integrates with **7 external systems**, manages **messy real-world data**, enforces **budget controls**, and runs **automated pipelines** on a schedule. Each of those things individually is straightforward. Combining them all into a reliable, production-grade tool is where the time goes.

---

## By the Numbers

| Metric | Count |
|--------|-------|
| Lines of application code | 17,000 |
| Lines of test code | 7,500 |
| Total Python files | 54 |
| UI pages | 11 |
| Core backend modules | 22 |
| Automated tests | 551 |
| External API integrations | 7 |
| Git commits in 15 days | 67 |
| Session state variables managed | 70 |
| Error-handling blocks | 78 |
| Design/planning documents | 33 |
| UI component library | 2,452 lines (custom-built) |

This is not a weekend project. It's a production application with the scope of something a small team would build over months.

---

## Where the Time Actually Goes

### 1. Seven External Systems That Don't Play Nice

HADES doesn't just query one API. It talks to:

1. **ZoomInfo Contact Search** - Find people at companies by location, industry, job title
2. **ZoomInfo Intent Search** - Find companies showing buying signals
3. **ZoomInfo Contact Enrich** - Fill in missing details (phone, email) for found contacts
4. **VanillaSoft Web Leads API** - Push leads directly into the call center dialer
5. **Zoho CRM** - Sync operator database (3,041 records)
6. **Turso (cloud database)** - Store everything persistently
7. **GitHub Actions** - Run the intent pipeline automatically every weekday morning

Each integration requires:
- Authentication (OAuth tokens, API keys, JWT)
- Rate limiting and retry logic (ZoomInfo throttles at ~5 req/sec)
- Error handling for when the service is down or returns garbage
- Data format translation (JSON, XML, CSV - each system speaks a different language)
- Testing with mocks (you can't run 551 tests against live APIs)

**Real example:** VanillaSoft's API accepts XML, not JSON. Every lead has to be translated from ZoomInfo's JSON format into 31 specific XML fields with exact naming conventions. If one field is wrong, the whole push silently fails. Building and testing that integration alone was a multi-day effort.

### 2. Real-World Data Is Messy

ZoomInfo's data looks clean in their documentation. In reality:

- **ZIP codes** come back as `"75201"`, `"75201-1234"`, `"752011234"`, or just `"7520"` (truncated). Every format has to be handled.
- **IDs** switch between integers and strings across different API responses. The same company might be `12345` in one call and `"12345"` in the next.
- **Scores** arrive as `"95%"` (string with percent sign) instead of the number `95`.
- **Phone numbers** come in every format imaginable: `(512) 431-7769`, `5124317769`, `+15124317769`, or sometimes just `431-7769`.
- **Names** contain HTML entities: `&amp;` instead of `&`, `&#39;` instead of apostrophes.
- **Fields that should always exist** are sometimes `null`, sometimes missing entirely, sometimes an empty string.

Every one of these has caused a bug at some point. Every one required writing defensive code and tests. This is not hypothetical - these are real issues we've hit and fixed.

### 3. Complex Business Logic, Not Just CRUD

This isn't a simple "fetch data and display it" app. The business logic includes:

- **Lead scoring engine** - Weighted scoring based on signal strength (50%), on-site likelihood (25%), and data freshness (25%). Each dimension has its own calculation rules, and the weights are configurable.

- **Auto-expansion algorithm** - When a Geography search doesn't hit the target contact count, the system automatically expands in a specific priority order: management levels first, then employee range, then accuracy threshold, then radius. Each expansion runs a new API search and deduplicates against previous results.

- **ZIP radius calculation** - Pure Python haversine math against 42,000 US ZIP codes to find all ZIPs within a radius. Handles cross-state borders (e.g., Texarkana TX includes Arkansas ZIPs).

- **Budget controls** - Weekly credit caps with alerts at 50%, 80%, and 95%. The system has to track credits across both workflows, prevent overspending, and still allow Geography searches (which are unlimited).

- **Deduplication** - One contact per company across multiple search expansions, matching by personId, companyId, and name. Has to handle the messy ID types mentioned above.

### 4. Two Workflow Modes, Each with Sub-Modes

The app isn't one workflow - it's effectively four:

| Workflow | Mode | Steps | Complexity |
|----------|------|-------|------------|
| Intent | Autopilot | Search → Auto-select → Find contacts → Export | Fully automated decision-making |
| Intent | Manual Review | Search → Review companies → Select → Find contacts → Export | User reviews each company |
| Geography | Autopilot | Select operator → Configure → Search → Enrich → Export | Auto-expansion, auto-dedup |
| Geography | Manual Review | Select operator → Configure → Search → Review per company → Confirm → Enrich → Export | User picks contacts per company |

Each mode has its own step indicator, state management, UI flow, and edge cases. The step indicator alone manages 70 session state variables to track where the user is and what data has been loaded.

### 5. The UI Is Custom-Built

Streamlit provides basic widgets (buttons, tables, dropdowns). Everything that makes HADES look professional is custom:

- **2,452 lines of CSS** injected as a design system (colors, spacing, shadows, animations)
- **Custom components**: metric cards, status badges, health indicators, progress bars, step indicators, styled tables with pill badges, labeled section dividers, action bars
- **Responsive layout** handling for tables with varying column counts
- **Dark mode design** with consistent color tokens across 11 pages

Off-the-shelf Streamlit apps look like gray boxes with default fonts. Making it look and feel like a real product takes significant design and implementation work.

### 6. Testing Everything

551 tests exist because every integration, every data format edge case, and every business rule needs verification. The test suite covers:

- API response parsing (happy path + every messy data variant)
- Scoring calculations across all weight combinations
- ZIP radius calculations with known distances
- Export format validation (all 31 VanillaSoft fields)
- Budget cap enforcement
- Deduplication logic
- Error handling when APIs return unexpected responses

Every code change runs against all 551 tests. This prevents regressions but means even small changes require ensuring nothing else breaks.

### 7. Automation and DevOps

The intent pipeline runs unattended every weekday at 7 AM. Making that reliable requires:

- GitHub Actions workflow with cron scheduling
- Credential management across environments (local dev vs. cloud)
- Error reporting and run history logging
- Handling partial failures (API down mid-search)
- Making the pipeline idempotent (safe to re-run without duplicates)

---

## What "Quick Changes" Actually Cost

Changes that sound small often aren't:

| Request | Sounds Like | Actually Involves |
|---------|-------------|-------------------|
| "Add a new field to the export" | 5 minutes | Update CSV mapping, VanillaSoft XML template, export validation, UI column, tests |
| "Change the scoring weights" | 1 minute | Update config, verify calibration page still works, regression test all scoring tests, validate downstream sort order |
| "Add a new filter option" | 10 minutes | UI widget, API parameter mapping, session state management, default handling, expansion logic interaction, tests |
| "Push leads to a new system" | An afternoon | New API client, auth, retry logic, data mapping, error handling, UI progress/status, tests, credential management |

---

## The Iceberg Analogy

What Damione sees:
- A dark-themed web app with nice cards and buttons
- "Search" button that finds leads
- "Export" button that sends them to VanillaSoft

What's underneath:
- 17,000 lines of application code
- 7 API integrations with auth, retry, and error handling
- Scoring engine with configurable weights
- Auto-expansion algorithm with 4 fallback tiers
- ZIP radius math against 42,000 centroids
- Budget tracking with weekly caps and alerts
- Deduplication across search expansions
- 551 automated tests
- Automated daily pipeline with monitoring
- Custom design system (2,452 lines of CSS)
- State management across 70 session variables
- Data cleaning for every messy format ZoomInfo throws at us

---

## Bottom Line

HADES replaces what would be hours of manual work per day: logging into ZoomInfo, searching, filtering, copying data into spreadsheets, formatting for VanillaSoft, and uploading. Automating that reliably - with budget controls, quality scoring, deduplication, and error handling - is a serious engineering effort. The time investment is building a tool that runs itself and doesn't break when real-world data gets weird.
