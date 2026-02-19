# Score Transparency Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface component score breakdowns and actionable priority phrases so users understand *why* leads scored the way they did and which to call first.

**Architecture:** Component scores already exist on lead dicts (`_proximity_score`, `_onsite_score`, etc.) — no new scoring logic. Add a `score_breakdown()` HTML renderer in `ui_components.py`, a `generate_score_summary()` sentence builder in `scoring.py`, and wire both into the three workflow pages below each results table.

**Tech Stack:** Python, Streamlit HTML components (`st.markdown` with `unsafe_allow_html=True`), existing scoring engine.

---

### Task 1: Actionable Priority Phrases

Add `get_priority_action()` alongside existing `get_priority_label()`.

**Files:**
- Modify: `scoring.py:433-442` (after `get_priority_label`)
- Test: `tests/test_scoring.py`

**Step 1: Write failing test**

```python
# In tests/test_scoring.py — add to existing file

class TestPriorityAction:
    def test_high_score_action(self):
        from scoring import get_priority_action
        assert get_priority_action(85) == "Call first — strong match"

    def test_medium_score_action(self):
        from scoring import get_priority_action
        assert get_priority_action(70) == "Good prospect — review details"

    def test_low_score_action(self):
        from scoring import get_priority_action
        assert get_priority_action(45) == "Lower fit — call if capacity allows"

    def test_very_low_score_action(self):
        from scoring import get_priority_action
        assert get_priority_action(30) == "Lower fit — call if capacity allows"

    def test_boundary_80(self):
        from scoring import get_priority_action
        assert get_priority_action(80) == "Call first — strong match"

    def test_boundary_60(self):
        from scoring import get_priority_action
        assert get_priority_action(60) == "Good prospect — review details"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scoring.py::TestPriorityAction -v`
Expected: FAIL — `ImportError: cannot import name 'get_priority_action'`

**Step 3: Write minimal implementation**

```python
# In scoring.py, after get_priority_label (line 442)

def get_priority_action(score: int) -> str:
    """Get actionable call-to-action phrase based on score."""
    if score >= 80:
        return "Call first — strong match"
    elif score >= 60:
        return "Good prospect — review details"
    else:
        return "Lower fit — call if capacity allows"
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scoring.py::TestPriorityAction -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add scoring.py tests/test_scoring.py
git commit -m "feat: add get_priority_action() for actionable priority phrases"
```

---

### Task 2: Score Summary Sentence Generator

Build `generate_score_summary()` that produces a plain-English sentence from component scores. Two variants: geography and intent.

**Files:**
- Modify: `scoring.py` (add after `get_priority_action`)
- Test: `tests/test_scoring.py`

**Step 1: Write failing tests**

```python
# In tests/test_scoring.py

class TestScoreSummary:
    def test_geography_strong_proximity(self):
        from scoring import generate_score_summary
        lead = {
            "_proximity_score": 90, "_onsite_score": 80,
            "_authority_score": 70, "_employee_score": 60,
            "_distance_miles": 3.2, "sicCode": "7011",
            "managementLevel": "Director", "employees": 250,
        }
        result = generate_score_summary(lead, "geography")
        assert "nearby" in result.lower() or "close" in result.lower()

    def test_geography_weak_industry(self):
        from scoring import generate_score_summary
        lead = {
            "_proximity_score": 85, "_onsite_score": 30,
            "_authority_score": 75, "_employee_score": 60,
            "_distance_miles": 5.0, "sicCode": "9999",
            "managementLevel": "Manager", "employees": 200,
        }
        result = generate_score_summary(lead, "geography")
        assert "industry" in result.lower() or "fit" in result.lower()

    def test_intent_strong_signal(self):
        from scoring import generate_score_summary
        lead = {
            "_company_intent_score": 90, "_authority_score": 75,
            "_accuracy_score": 100, "_phone_score": 100,
            "managementLevel": "Manager",
        }
        result = generate_score_summary(lead, "intent")
        assert "strong" in result.lower() or "signal" in result.lower()

    def test_intent_weak_authority(self):
        from scoring import generate_score_summary
        lead = {
            "_company_intent_score": 85, "_authority_score": 30,
            "_accuracy_score": 70, "_phone_score": 100,
            "managementLevel": "Non-Manager",
        }
        result = generate_score_summary(lead, "intent")
        assert isinstance(result, str) and len(result) > 10

    def test_missing_fields_no_crash(self):
        from scoring import generate_score_summary
        result = generate_score_summary({}, "geography")
        assert isinstance(result, str)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scoring.py::TestScoreSummary -v`
Expected: FAIL — `ImportError: cannot import name 'generate_score_summary'`

**Step 3: Write minimal implementation**

```python
# In scoring.py, after get_priority_action

def _tier(score: int) -> str:
    """Classify a score into strength tier."""
    if score >= 70:
        return "strong"
    elif score >= 40:
        return "moderate"
    return "weak"


def generate_score_summary(lead: dict, workflow_type: str) -> str:
    """Generate a plain-English summary sentence from component scores."""
    from utils import SIC_CODE_DESCRIPTIONS

    if workflow_type == "geography":
        prox = lead.get("_proximity_score", 0)
        onsite = lead.get("_onsite_score", 0)
        auth = lead.get("_authority_score", 0)
        emp = lead.get("_employee_score", 0)

        # Proximity phrase
        dist = lead.get("_distance_miles")
        if prox >= 70:
            prox_phrase = f"Nearby ({dist:.0f} mi)" if dist else "Nearby"
        elif prox >= 40:
            prox_phrase = f"Moderate distance ({dist:.0f} mi)" if dist else "Moderate distance"
        else:
            prox_phrase = f"Far ({dist:.0f} mi)" if dist else "Far from target"

        # Authority phrase
        mgmt = lead.get("managementLevel", "")
        if isinstance(mgmt, list):
            mgmt = mgmt[0] if mgmt else ""
        auth_phrase = mgmt.lower() if mgmt else "contact"

        # Industry phrase
        sic = lead.get("sicCode", "")
        sic_name = SIC_CODE_DESCRIPTIONS.get(sic, "")
        if onsite >= 70:
            ind_phrase = f"strong industry fit ({sic_name})" if sic_name else "strong industry fit"
        elif onsite >= 40:
            ind_phrase = f"moderate industry fit ({sic_name})" if sic_name else "moderate industry fit"
        else:
            ind_phrase = f"low industry fit ({sic_name})" if sic_name else "low industry fit"

        # Company size phrase
        emps = lead.get("employees") or lead.get("employeeCount") or 0
        if isinstance(emps, str):
            emps = int(emps) if emps.isdigit() else 0
        if emps:
            size_phrase = f"{emps:,} employees"
        else:
            size_phrase = ""

        parts = [prox_phrase, auth_phrase, size_phrase, ind_phrase]
        return " · ".join(p for p in parts if p)

    elif workflow_type == "intent":
        intent = lead.get("_company_intent_score", 0)
        auth = lead.get("_authority_score", 0)

        # Signal phrase
        if intent >= 70:
            sig_phrase = "Strong intent signal"
        elif intent >= 40:
            sig_phrase = "Moderate intent signal"
        else:
            sig_phrase = "Weak intent signal"

        # Authority
        mgmt = lead.get("managementLevel", "")
        if isinstance(mgmt, list):
            mgmt = mgmt[0] if mgmt else ""
        auth_phrase = mgmt.lower() if mgmt else "contact"

        parts = [sig_phrase, auth_phrase]
        return " · ".join(p for p in parts if p)

    return ""
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scoring.py::TestScoreSummary -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add scoring.py tests/test_scoring.py
git commit -m "feat: add generate_score_summary() for plain-English score explanations"
```

---

### Task 3: Score Breakdown HTML Component

Build `score_breakdown()` in `ui_components.py` — renders horizontal bars with labels for each scoring factor.

**Files:**
- Modify: `ui_components.py` (add new function)
- Test: `tests/test_ui_components.py`

**Step 1: Write failing tests**

```python
# In tests/test_ui_components.py

class TestScoreBreakdown:
    def test_geography_renders_all_bars(self):
        from ui_components import score_breakdown
        lead = {
            "_score": 78, "_proximity_score": 85, "_onsite_score": 40,
            "_authority_score": 75, "_employee_score": 60,
            "_distance_miles": 3.2, "sicCode": "7011",
            "managementLevel": "Director", "employees": 250,
        }
        html = score_breakdown(lead, "geography")
        assert "Proximity" in html
        assert "Industry" in html
        assert "Authority" in html
        assert "Company Size" in html

    def test_intent_renders_all_bars(self):
        from ui_components import score_breakdown
        lead = {
            "_score": 72, "_company_intent_score": 85,
            "_authority_score": 60, "_accuracy_score": 100,
            "_phone_score": 70, "managementLevel": "Manager",
        }
        html = score_breakdown(lead, "intent")
        assert "Intent Signal" in html
        assert "Authority" in html
        assert "Accuracy" in html
        assert "Phone" in html

    def test_bar_color_green_for_high_score(self):
        from ui_components import score_breakdown
        lead = {
            "_score": 90, "_proximity_score": 95, "_onsite_score": 80,
            "_authority_score": 85, "_employee_score": 75,
        }
        html = score_breakdown(lead, "geography")
        # Green color should appear for high scores
        assert "#22c55e" in html or "success" in html.lower()

    def test_bar_color_yellow_for_moderate_score(self):
        from ui_components import score_breakdown
        lead = {
            "_score": 55, "_proximity_score": 50, "_onsite_score": 45,
            "_authority_score": 40, "_employee_score": 55,
        }
        html = score_breakdown(lead, "geography")
        assert "#eab308" in html

    def test_summary_line_included(self):
        from ui_components import score_breakdown
        lead = {
            "_score": 78, "_proximity_score": 85, "_onsite_score": 40,
            "_authority_score": 75, "_employee_score": 60,
            "_distance_miles": 3.2, "sicCode": "7011",
            "managementLevel": "Director", "employees": 250,
        }
        html = score_breakdown(lead, "geography")
        # Should contain the summary sentence
        assert "·" in html  # summary uses · separator

    def test_empty_lead_no_crash(self):
        from ui_components import score_breakdown
        html = score_breakdown({}, "geography")
        assert isinstance(html, str)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ui_components.py::TestScoreBreakdown -v`
Expected: FAIL — `ImportError: cannot import name 'score_breakdown'`

**Step 3: Write minimal implementation**

```python
# In ui_components.py — add after the existing component functions

def score_breakdown(lead: dict, workflow_type: str) -> str:
    """Render score breakdown as HTML with horizontal bars per component.

    Args:
        lead: Lead dict with _score and component score fields
        workflow_type: "geography" or "intent"

    Returns:
        HTML string for rendering with st.markdown(unsafe_allow_html=True)
    """
    from scoring import generate_score_summary, get_priority_action

    score = lead.get("_score", 0)
    action = get_priority_action(score)
    summary = generate_score_summary(lead, workflow_type)

    if workflow_type == "geography":
        components = [
            ("Proximity", lead.get("_proximity_score", 0)),
            ("Industry", lead.get("_onsite_score", 0)),
            ("Authority", lead.get("_authority_score", 0)),
            ("Company Size", lead.get("_employee_score", 0)),
        ]
    elif workflow_type == "intent":
        components = [
            ("Intent Signal", lead.get("_company_intent_score", 0)),
            ("Authority", lead.get("_authority_score", 0)),
            ("Accuracy", lead.get("_accuracy_score", 0)),
            ("Phone", lead.get("_phone_score", 0)),
        ]
    else:
        components = []

    def _bar_color(val: int) -> str:
        if val >= 70:
            return "#22c55e"
        elif val >= 40:
            return "#eab308"
        return COLORS.get("text_secondary", "#64748b")

    bars_html = ""
    for label, val in components:
        color = _bar_color(val)
        width = max(2, val)  # min 2% width so bar is visible
        bars_html += f'''<div style="display: flex; align-items: center; gap: 8px; margin: 4px 0;">
<span style="width: 100px; font-size: 0.8rem; color: {COLORS.get('text_secondary', '#94a3b8')};">{label}</span>
<div style="flex: 1; height: 8px; background: {COLORS.get('bg_primary', '#0d1117')}; border-radius: 4px; overflow: hidden;">
<div style="width: {width}%; height: 100%; background: {color}; border-radius: 4px;"></div>
</div>
<span style="width: 30px; font-size: 0.8rem; font-family: 'IBM Plex Mono', monospace; color: {COLORS.get('text_primary', '#e2e8f0')}; text-align: right;">{val}</span>
</div>'''

    return f'''<div style="padding: 8px 0;">
<div style="font-size: 0.85rem; color: {COLORS.get('text_secondary', '#94a3b8')}; margin-bottom: 8px;">{summary}</div>
{bars_html}
<div style="font-size: 0.8rem; color: {COLORS.get('text_secondary', '#94a3b8')}; margin-top: 6px; font-style: italic;">{action}</div>
</div>'''
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ui_components.py::TestScoreBreakdown -v`
Expected: PASS (6 tests)

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass (no regressions)

**Step 6: Commit**

```bash
git add ui_components.py tests/test_ui_components.py
git commit -m "feat: add score_breakdown() HTML component with color-coded bars"
```

---

### Task 4: Wire into Geography Workflow

Add score breakdown expanders below the results table in the Geography Workflow page.

**Files:**
- Modify: `pages/2_Geography_Workflow.py` (~lines 1645-1700, results display section)

**Step 1: Find the results table code**

The results table is built at lines ~1645-1700 and rendered with `st.dataframe()` at line 1698. After the dataframe, add expanders per lead.

**Step 2: Add expanders after the results table**

After the `st.dataframe(...)` call (line ~1700), add:

```python
# Score breakdown expanders
from ui_components import score_breakdown

with st.expander("Score details", expanded=False):
    for lead in final_leads:
        name = f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip()
        company = lead.get("companyName", "Unknown")
        score = lead.get("_score", 0)
        st.markdown(
            f"**{name}** · {company} · {score}%",
        )
        st.markdown(score_breakdown(lead, "geography"), unsafe_allow_html=True)
        st.markdown("---")
```

Note: `score_breakdown` is already imported at the top via `from ui_components import ...`. Add it to the existing import list.

**Step 3: Update the Priority column in the results table**

Find where `_priority` is set (around line 1600) and add the action phrase:

```python
from scoring import get_priority_action
lead["_priority"] = get_priority_label(lead.get("_score", 0))
lead["_priority_action"] = get_priority_action(lead.get("_score", 0))
```

In the results table dict (around line 1659), change `"Priority": lead.get("_priority", "")` to include the action:

```python
"Priority": lead.get("_priority_action", lead.get("_priority", "")),
```

**Step 4: Test manually**

Run: `streamlit run app.py` and navigate to Geography Workflow.
Verify: Score details expander appears below results with colored bars.

**Step 5: Commit**

```bash
git add pages/2_Geography_Workflow.py
git commit -m "feat: add score breakdown expander to Geography Workflow results"
```

---

### Task 5: Wire into Intent Workflow

Same pattern as Task 4, adapted for intent scoring components.

**Files:**
- Modify: `pages/1_Intent_Workflow.py` (~lines 1280-1320, results display section)

**Step 1: Find the results table code**

The results table is rendered with `st.dataframe()` at line ~1317. After the dataframe, add the same expander pattern.

**Step 2: Add expanders after the results table**

After the `st.dataframe(...)` call, add:

```python
from ui_components import score_breakdown

with st.expander("Score details", expanded=False):
    for lead in scored_leads:
        name = f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip()
        company = lead.get("companyName", "Unknown")
        score = lead.get("_score", 0)
        st.markdown(
            f"**{name}** · {company} · {score}%",
        )
        st.markdown(score_breakdown(lead, "intent"), unsafe_allow_html=True)
        st.markdown("---")
```

Add `score_breakdown` to the existing `from ui_components import ...` at the top.

**Step 3: Update the Priority column**

Find where `_priority` is assigned and add `_priority_action` using `get_priority_action()`. Update the results table to show the action phrase.

**Step 4: Test manually**

Run: `streamlit run app.py` and navigate to Intent Workflow.
Verify: Score details expander appears below results with intent-specific bars.

**Step 5: Commit**

```bash
git add pages/1_Intent_Workflow.py
git commit -m "feat: add score breakdown expander to Intent Workflow results"
```

---

### Task 6: Wire into CSV Export Review

Add score breakdown to the CSV Export page so users can review score details before exporting.

**Files:**
- Modify: `pages/4_CSV_Export.py` (~lines 234-260, summary section)

**Step 1: Add expander after the summary metrics**

After the validation section and before the operator selection, add a "Lead Details" expander:

```python
from ui_components import score_breakdown

with st.expander(f"Lead score details ({len(leads_to_export)} leads)", expanded=False):
    for lead in leads_to_export:
        name = f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip()
        company = lead.get("companyName", "Unknown")
        score = lead.get("_score", 0)
        st.markdown(f"**{name}** · {company} · {score}%")
        st.markdown(
            score_breakdown(lead, workflow_type),
            unsafe_allow_html=True,
        )
        st.markdown("---")
```

Add `score_breakdown` to the existing `from ui_components import ...` at the top.

**Step 2: Test manually**

Run: `streamlit run app.py`, run a workflow, go to Export page.
Verify: "Lead score details" expander shows breakdown for each lead.

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass

**Step 4: Commit**

```bash
git add pages/4_CSV_Export.py
git commit -m "feat: add score breakdown expander to CSV Export review"
```

---

### Task 7: Final Integration Test + Cleanup

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All tests pass (560 + ~17 new = ~577)

**Step 2: Update CLAUDE.md test count**

Update the test count in `CLAUDE.md` to reflect new total.

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update test count after score transparency feature"
```
