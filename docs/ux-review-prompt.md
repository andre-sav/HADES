# Comprehensive UX Review — HADES Lead Pipeline

You are reviewing a Streamlit application used daily by a vending services sales team.
Your job is NOT cosmetic polish. Your job is to find structural problems, redundancy,
missing functionality, and friction in the actual experience of using this tool.

## Before You Start

1. Read CLAUDE.md and docs/SESSION_HANDOFF.md for full context
2. Launch the app (`streamlit run app.py`) and open it in the browser
3. Read the user stories in docs/stories/ to understand intended behavior

## Phase 1: User Journey Walkthroughs (use the live app)

Walk through each journey end-to-end in the browser. For each, document:
- Every click, wait, and decision point
- Where you hesitate or feel confused
- What information you need that isn't visible
- What's shown that you don't need

**Journey A — Intent Pipeline (new user, first time):**
Home → Intent Workflow → Search → Review companies → Select → Find contacts →
Select contacts → Enrich → Review results → Export to VanillaSoft

**Journey B — Geography Pipeline (daily use, returning user):**
Home → Geography Workflow → Pick operator → Configure search → Run →
Review contacts → Select → Enrich → Score review → Export → Push to VanillaSoft

**Journey C — Morning check-in (power user, 30 seconds):**
Home → Check what ran overnight → See if anything needs attention →
Decide: run new search or export existing leads?

**Journey D — Export & deliver (completing work):**
CSV Export → Load staged leads → Review scores → Check validation →
Push to VanillaSoft → Verify success → Move to next batch

## Phase 2: Structural Analysis (per page)

For EVERY page, answer these questions:

### Necessity
- What user goal does each element serve?
- Is any element redundant with another element on this page?
- Is any element redundant with the sidebar navigation?
- Could two elements be merged into one without losing information?
- Is anything shown that the user never acts on?

### Missing Affordances
- Are there static displays that should be interactive (clickable, expandable, filterable)?
- Are there status indicators without explanation (what does this mean? what do I do?)?
- Are there actions without confirmation or feedback?
- Are there error states that are never shown or tested?
- Are there empty states that are confusing or unhelpful?

### Information Hierarchy
- Is the most important information the most visually prominent?
- Is anything buried that should be surface-level?
- Is anything surface-level that should be in an expander or secondary view?
- Are metrics meaningful without context (compared to what? since when?)?

### Consistency
- Do parallel workflows (Intent vs Geography) show the same information
  the same way? Document every difference.
- Are the same field names used consistently across pages?
- Do similar actions use the same button style/placement/wording?
- Are status indicators (colors, badges, pills) used consistently?

## Phase 3: Cross-Cutting Concerns

### Data Completeness
- Open each page and check: are there fields showing "Unknown", "N/A",
  empty strings, or missing data? Trace each to its source.
- Are tooltips/help text present on every non-obvious element?
- Do all tables have sort/filter capabilities where useful?

### Workflow Continuity
- After completing each pipeline step, is it clear what to do next?
- Can the user easily go back to a previous step without losing work?
- If the user refreshes the browser mid-workflow, what survives?

### Redundancy Audit
- List every way to navigate to each page (sidebar, buttons, links, cards).
  Flag anything with 3+ navigation paths.
- List every place the same data is displayed. Flag duplicates.
- List every status indicator and what it means. Flag inconsistencies.

## Phase 4: Optimization Proposals

For each finding, propose a specific fix with:
- **What:** The exact change
- **Why:** What user problem it solves
- **Impact:** High (daily friction) / Medium (occasional confusion) / Low (polish)
- **Effort:** Lines of code estimate

Group proposals into:
1. **Quick wins** — High impact, low effort (do first)
2. **Structural changes** — High impact, higher effort (plan carefully)
3. **Polish** — Low impact (do last or skip)

## Output Format

Produce a single markdown document with:
1. Journey walkthrough notes (what you observed, not what you'd change)
2. Per-page findings table (element | issue | severity | fix)
3. Cross-cutting findings
4. Prioritized fix list with effort estimates

Do NOT propose cosmetic changes (font sizes, spacing, colors) unless they
cause actual usability problems. Focus on structure, flow, and information.
