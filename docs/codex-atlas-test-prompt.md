# HADES Dashboard — Atlas Browser Testing Prompt

> Paste this into Codex with Atlas (browser) enabled.
> Pre-requisite: `streamlit run app.py` must be running on the target machine.

---

## Role

You are a QA engineer and UX reviewer testing a Streamlit multi-page application called HADES — a ZoomInfo lead pipeline for a vending services sales team. Use Atlas to navigate every page of the live app at `http://localhost:8501`, exercise core workflows, and report actionable findings.

No authentication is required.

## App Context

HADES queries the ZoomInfo API to find B2B sales leads, scores them against an Ideal Customer Profile (ICP), and exports them to VanillaSoft (a CRM). The primary users are sales operations staff who run searches daily.

**Two core workflows:**
- **Intent Workflow** — Find companies showing buying intent signals, resolve their contacts, enrich, score, and export.
- **Geography Workflow** — Find contacts within an operator's service territory by ZIP code radius, enrich, score, and export.

**Key design decisions:**
- Dark theme with Indigo/Cyan accent gradient, Urbanist font family
- All numeric/data values use IBM Plex Mono (tabular nums)
- Status indicators use colored badge pills (not emoji)
- Spacing is on a 4px grid (0.25rem increments)
- Cards have subtle shadow with hover elevation change

## Pages to Test (sidebar order)

| # | Page | What it does |
|---|------|-------------|
| 0 | **app** (Home) | Quick-action cards, system status row, metrics, recent runs |
| 1 | **Intent Workflow** | Multi-step pipeline: search intent → select companies → find contacts → enrich → score → export |
| 2 | **Geography Workflow** | Operator selector → ZIP radius config → contact search with auto-expansion → review → export |
| 3 | **Operators** | CRUD list of 3,000+ operators with search, pagination, inline edit, Zoho CRM sync |
| 4 | **CSV Export** | Source selection, cross-workflow dedup, validation checklist, VanillaSoft push + CSV download |
| 5 | **Usage Dashboard** | ZoomInfo API usage meters, weekly/period/query-history tabs |
| 6 | **Executive Summary** | MTD KPIs with week-over-week deltas, narrative metrics, trend charts, budget status |
| 7 | **Score Calibration** | Current scoring weights, SIC industry scores, calibration from outcome data |
| 8 | **Pipeline Test** | Dev-only (requires DEV_MODE secret) — may show gating message, that's expected |
| 9 | **API Discovery** | Dev-only (requires DEV_MODE secret) — may show gating message, that's expected |
| 10 | **Automation** | Scheduled pipeline config, Run Now with dry-run preview, run history |
| 11 | **Pipeline Health** | Health indicator cards (DB, cache, API, last query), recent errors, query activity |

## Test Plan

### Pass 1 — Visual & Layout Audit (every page)

Navigate to each page in sidebar order. For each page, check:

1. **Page loads without errors** — no red error banners, no Python tracebacks, no blank content areas
2. **Header renders correctly** — title + caption + divider present, no double dividers
3. **Typography hierarchy** — headings use Urbanist, data values use monospace, labels are uppercase 12px
4. **Card and surface treatment** — metric cards have visible border + shadow, hover states respond
5. **Status badges** — colored pills (green/amber/red/blue/gray) instead of emoji for status indicators
6. **Spacing consistency** — no cramped sections, no excessive whitespace gaps between elements
7. **Empty states** — if data is missing, a helpful empty-state message appears (not a blank void)
8. **Responsive behavior** — resize the browser window narrower; columns should reflow, not overlap or truncate

### Pass 2 — Functional Walkthrough

**Home page:**
- Verify quick-action cards link to correct pages (Intent, Geography, Export)
- Status row shows database "Connected" badge
- Recent Runs expander opens and shows run history

**Operators page:**
- Type a search query → results filter in real time
- Click the "+" add button → form appears with correct fields
- Cancel the form → it collapses cleanly
- If operators exist, pagination controls work (Previous/Next)
- Click the ⋮ menu on an operator row → Edit/Delete actions appear

**Usage Dashboard:**
- Tabs switch between Weekly / By Period / Recent Queries
- Progress bars render with correct color thresholds (green < 70%, amber 70-90%, red > 90%)
- Period selector changes the displayed data

**Executive Summary:**
- KPI cards show numeric values with delta indicators (green up / red down arrows)
- Plotly charts render (not blank rectangles)
- Narrative metric sentences read coherently

**Score Calibration:**
- "Current Weights" tab shows SIC code table with filter input
- Employee Scale table renders
- Tab switching works cleanly

**Automation:**
- Next Run countdown displays a future date
- Run History section shows past runs with status badges
- "Dry Run" button is clickable (don't actually press "Run Now" — it uses real API credits)

**Pipeline Health:**
- Four health indicator cards render in a 2x2 grid
- Each card shows a colored dot (green/yellow/red), label, status text, and detail
- Recent Pipeline Runs table populates

### Pass 3 — Edge Cases & Error States

- **Export page with no staged leads** — should show empty state with helpful CTA, not crash
- **Operators page with empty search** — should show all operators, not "no results"
- **Automation page** — if no pipeline runs exist, empty state should render
- **Score Calibration → Calibration Report** — if no outcome data, should show empty state
- **Rapid tab switching** — on Usage Dashboard and Executive Summary, switch tabs quickly 5+ times; verify no stale content bleeds through

## Output Format

Organize your findings into three sections:

### 1. Blockers (things that prevent task completion)
For each: **Page** → **What happened** → **Expected behavior** → **Screenshot if possible**

### 2. UX Issues (things that work but feel wrong)
For each: **Page** → **What you observed** → **Why it matters** → **Suggested fix**

### 3. Polish (minor visual/consistency nits)
For each: **Page** → **Observation** → **Design system expectation**

At the end, provide a **Summary Score**:
- Functionality: X/10 (does everything work?)
- Visual Consistency: X/10 (does the design system hold?)
- Information Architecture: X/10 (can a user find what they need?)
- Error Handling: X/10 (do failures degrade gracefully?)

## Important Notes

- Pages 8 (Pipeline Test) and 9 (API Discovery) are dev-only. If they show an info message saying "only available in developer mode", that is **correct behavior** — not a bug.
- Do NOT click "Run Now" on the Automation page or "Push to VanillaSoft" on the Export page — these trigger real API calls that cost money.
- The Ctrl+Enter keyboard shortcut is only active on the Geography Workflow page.
- If the ZoomInfo API usage section on the Usage Dashboard shows a warning about credentials, that's expected for environments without API keys configured.
