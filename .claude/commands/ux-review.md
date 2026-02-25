# UX Review

Autonomous visual and structural review of HADES Streamlit pages after UI changes. Catches layout misalignment, inconsistent state, wrong counts, missing spacing, and design system violations.

**Invoke after any page modification.** Run the full protocol — do not skip steps.

## Step 1: Identify Scope

Determine which pages were modified in this session:

```bash
git diff --name-only HEAD | grep "pages/"
```

If no page files changed but `ui_components.py` changed, review ALL pages.

## Step 2: Screenshot Each Page State

For each modified page, navigate via Playwright and screenshot every key state. Use `mcp__claude-in-chrome__tabs_context_mcp` first to get browser context, then navigate.

**Base URL:** `http://localhost:8501`

### Page State Matrix

Each page has states that must be visually verified. Screenshot each reachable state.

| Page | States to Check |
|------|----------------|
| **Home** (`/`) | Default dashboard load |
| **Intent Workflow** (`/Intent_Workflow`) | (1) Empty — no search run, (2) Search pending — cancel button visible, (3) Autopilot results showing, (4) Manual mode step 2 — company selection, (5) Manual mode step 4 — results with export buttons |
| **Geography Workflow** (`/Geography_Workflow`) | (1) Empty — no operator selected, (2) Operator selected — search form visible, (3) Results showing |
| **Operators** (`/Operators`) | (1) List view with pagination, (2) Add/edit form if reachable |
| **CSV Export** (`/CSV_Export`) | (1) Empty — no staged exports, (2) With staged exports |
| **Usage Dashboard** (`/Usage_Dashboard`) | (1) Weekly tab, (2) By Period tab, (3) Recent Queries tab |
| **Executive Summary** (`/Executive_Summary`) | (1) Overview tab, (2) Trends tab, (3) Budget tab |
| **Score Calibration** (`/Score_Calibration`) | (1) Weights tab, (2) Calibration tab, (3) Outcomes tab |
| **Pipeline Test** (`/Pipeline_Test`) | Default view |
| **API Discovery** (`/API_Discovery`) | Default view |
| **Automation** (`/Automation`) | (1) Default — run history, (2) After action if reachable |
| **Pipeline Health** (`/Pipeline_Health`) | Default — health cards + tables |

**Not all states are reachable without running the pipeline.** Screenshot what you can navigate to. For workflow pages that require API calls to reach later states, check the code structure instead (Step 3).

## Step 3: Visual Inspection Checklist

For each screenshot, check every item. Report violations with file:line references.

### Layout & Alignment

- [ ] **Buttons on the same logical row are in the same `st.columns()` call** — no buttons orphaned on separate rows
- [ ] **Column proportions make sense** — primary actions get equal or more space than secondary
- [ ] **No empty/dead space** from unused columns (e.g., `col1` in a `[2,1,1]` layout left empty)
- [ ] **Consistent spacing** — `st.markdown("")` or dividers between major sections, not jammed together

### Step Indicators & Progress

- [ ] **Completed state shows all steps green** — when pipeline is done, `current_step > total` so all steps render as completed (green checkmarks), not the last step as active (purple number)
- [ ] **Step count matches mode** — Autopilot has 3 steps, Manual has 4
- [ ] **Step labels match section headers** — "Step N" in headers matches the indicator

### Data Consistency

- [ ] **Summary strip counts match visible data** — CONTACTS in strip == rows in results table, COMPANIES in strip == actual count at current pipeline stage
- [ ] **Metric cards show current-stage data** — not stale values from earlier pipeline steps
- [ ] **Post-enrichment views use enriched data** — not pre-enrichment counts or fields

### Component Patterns

- [ ] **Dataframes have breathing room** — `st.markdown("")` after `st.dataframe()` before the next element
- [ ] **Expanders don't crowd adjacent elements** — spacing above and below
- [ ] **Status badges use correct semantic colors** — success=green, warning=amber, error=red, info=blue
- [ ] **Tables use mono font for data values** — scores, counts, IDs in IBM Plex Mono

### Interactive Elements

- [ ] **Disabled states are clear** — disabled buttons show why (tooltip or adjacent caption)
- [ ] **Destructive buttons use `destructive_button()` helper** — not plain `st.button` with red styling
- [ ] **Outline buttons use `outline_button()` helper** — secondary actions aren't competing with primary

### Design System (ref: `.interface-design/system.md`)

- [ ] **Colors from tokens only** — no hardcoded hex outside `COLORS` dict
- [ ] **Labels are uppercase** — 12px, 500wt, muted, 0.04em tracking
- [ ] **Data values in mono** — IBM Plex Mono for numbers, scores, IDs
- [ ] **Cards follow pattern** — bg_secondary, 1px border, 10px radius

## Step 4: Code Anti-Pattern Scan

Run these checks on modified files. Each catches a class of bugs found in production:

### Scope Escapes

Variables defined inside `if/else` blocks but referenced outside:

```bash
# Look for variables assigned only inside conditional blocks
# then used at module level — the _is_pending pattern
```

Check: any variable first assigned inside `if _results_showing:` / `else:` but used after the block ends. These cause NameError when the other branch executes.

### Stale Data References

When a pipeline has stages, later stages must use later-stage data:

- After enrichment: use `intent_results` or `intent_enriched_contacts`, NOT `intent_contacts_by_company`
- After scoring: use scored/deduped counts, NOT raw API response counts
- Summary strips and metric cards are the most common offenders

### Missing Spacing

```
st.dataframe(...) followed immediately by st.expander/st.button/st.columns
```

Should have `st.markdown("")` between them.

### Orphaned UI Elements

Buttons or controls rendered outside the column layout of their logical group. Pattern: one `st.columns()` call for the main row, then a separate block below for a related button.

### Fragment Boundary Issues

`@st.fragment` functions have their own rerun scope. Elements INSIDE a fragment and elements OUTSIDE should not share layout expectations (e.g., columns).

## Step 5: Report

Present findings as a table:

| # | Severity | Page | Issue | Fix |
|:-:|:--------:|------|-------|-----|
| 1 | High | Intent Workflow | ... | ... |

Severity levels:
- **High** — Layout broken, wrong data shown, NameError possible
- **Medium** — Spacing off, alignment inconsistent, design system violation
- **Low** — Minor polish, could-be-better

Then fix all High and Medium issues. Ask before fixing Low issues.

## When to Skip

- If only backend/API code changed (no UI impact), skip the review
- If only tests changed, skip
- If only `CLAUDE.md` or docs changed, skip
