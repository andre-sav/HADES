# Expansion Timeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a per-step expansion timeline component to the Geography Workflow showing what changed, old → new values, and contacts found at each step.

**Architecture:** `expand_search()` records structured step data alongside the existing `expansion_log`. A new `expansion_timeline()` component in `ui_components.py` renders this data as styled HTML rows inside a Streamlit expander. The Geography page wires them together.

**Tech Stack:** Streamlit, Python, HTML/CSS (inline styles using existing COLORS/FONTS/SPACING dicts from `ui_components.py`)

---

### Task 1: Add structured `expansion_steps` data to `expand_search()`

**Files:**
- Modify: `expand_search.py:222,443-463,541-552`
- Test: `tests/test_expand_search.py`

**Step 1: Write the failing test**

Add to `tests/test_expand_search.py` at the end:

```python
class TestExpansionSteps:
    """Test structured expansion_steps data in result dict."""

    def test_expansion_steps_present_in_result(self):
        """Result dict must contain expansion_steps list."""
        # Simulate a result dict as returned by expand_search
        result = {
            "target": 25,
            "found": 30,
            "target_met": True,
            "steps_applied": 2,
            "expansion_steps": [
                {
                    "param": "management_levels",
                    "old_value": "Manager/Director/VP Level Exec",
                    "new_value": "Manager/Director/VP Level Exec/C Level Exec",
                    "contacts_found": 14,
                    "new_companies": 5,
                    "cumulative_companies": 18,
                },
                {
                    "param": "employee_max",
                    "old_value": "50-5,000",
                    "new_value": "50+ (no cap)",
                    "contacts_found": 20,
                    "new_companies": 12,
                    "cumulative_companies": 30,
                },
            ],
        }
        assert "expansion_steps" in result
        assert len(result["expansion_steps"]) == 2
        assert result["expansion_steps"][0]["param"] == "management_levels"
        assert result["expansion_steps"][0]["old_value"] == "Manager/Director/VP Level Exec"
        assert result["expansion_steps"][1]["new_companies"] == 12

    def test_expansion_steps_empty_when_no_expansion(self):
        """When target met on first search, expansion_steps should be empty."""
        result = {
            "target": 10,
            "found": 15,
            "target_met": True,
            "steps_applied": 0,
            "expansion_steps": [],
        }
        assert result["expansion_steps"] == []

    def test_expansion_step_param_names(self):
        """Each step param should be one of the known expansion types."""
        valid_params = {"management_levels", "employee_max", "accuracy_min", "radius"}
        steps = [
            {"param": "management_levels", "old_value": "a", "new_value": "b",
             "contacts_found": 10, "new_companies": 5, "cumulative_companies": 15},
            {"param": "radius", "old_value": "10mi", "new_value": "15mi",
             "contacts_found": 8, "new_companies": 3, "cumulative_companies": 18},
        ]
        for step in steps:
            assert step["param"] in valid_params
```

**Step 2: Run tests to verify they pass (these are structural tests)**

Run: `python -m pytest tests/test_expand_search.py::TestExpansionSteps -v`
Expected: PASS (these test data structure contracts, not function calls)

**Step 3: Add `expansion_steps` recording to `expand_search()`**

In `expand_search.py`, make these changes:

a) After line 222 (`expansion_log = []`), add:

```python
    expansion_steps = []  # Structured per-step data for timeline UI
```

b) Inside the expansion loop, after line 463 (`log_progress(f"**Expansion {steps_applied}...`), before the rate limit delay, add code to record the step. The recording needs to happen AFTER the search (lines 472-484) so we know contacts_found and new_companies. So place this block after line 484 (`log_progress(f"Found {len(contacts)}..."`):

```python
            # Record structured step data for timeline
            expansion_steps.append({
                "param": list(step.keys())[0],  # Primary param changed
                "old_value": old_value_desc,
                "new_value": ", ".join(expansion_desc),
                "contacts_found": len(contacts),
                "new_companies": new_companies,
                "cumulative_companies": len(unique_companies),
            })
```

c) To capture `old_value_desc`, add this BEFORE the "Describe and apply expansion" block (before line 443). Insert right after `continue` on line 441:

```python
        # Capture old values BEFORE applying the step
        old_parts = []
        if "radius" in step:
            old_parts.append(f"{current_params['radius']}mi")
        if "accuracy_min" in step:
            old_parts.append(f"accuracy {current_params['accuracy_min']}")
        if "management_levels" in step:
            old_parts.append("/".join(current_params["management_levels"]))
        if "employee_max" in step:
            curr = current_params["employee_max"]
            old_parts.append("50+ (no cap)" if curr == 0 else f"50-{curr:,}")
        old_value_desc = ", ".join(old_parts)
```

d) Add `expansion_steps` to ALL return dicts in the function. There are 5 return statements. Add `"expansion_steps": expansion_steps,` to each one. They are at approximately:
- Line ~345 (cancelled early return)
- Line ~374-385 (error return)
- Line ~391-403 (target met first search, stop_early)
- Line ~541-552 (final normal return)

Search for every `"expansion_log": expansion_log` and add `"expansion_steps": expansion_steps,` on the next line.

**Step 4: Run all expand_search tests**

Run: `python -m pytest tests/test_expand_search.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass (524+)

**Step 6: Commit**

```bash
git add expand_search.py tests/test_expand_search.py
git commit -m "feat: add structured expansion_steps to expand_search result

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Build `expansion_timeline()` UI component

**Files:**
- Modify: `ui_components.py` (append after `narrative_metric()`, around line 1810)
- Test: `tests/test_ui_components.py`

**Step 1: Write the failing tests**

Add to `tests/test_ui_components.py`. First update the import on line 16:

```python
from ui_components import workflow_run_state, export_validation_checklist, narrative_metric, company_card_header, score_breakdown, expansion_timeline
```

Then add at the end of the file:

```python
class TestExpansionTimeline:
    """Tests for expansion_timeline component."""

    def test_renders_steps(self):
        """expansion_timeline renders HTML for each step."""
        mock_st.reset_mock()
        steps = [
            {"param": "management_levels", "old_value": "Manager/Director/VP Level Exec",
             "new_value": "management → Manager/Director/VP Level Exec/C Level Exec",
             "contacts_found": 14, "new_companies": 5, "cumulative_companies": 18},
            {"param": "employee_max", "old_value": "50-5,000",
             "new_value": "employees → 50+ (no cap)",
             "contacts_found": 20, "new_companies": 12, "cumulative_companies": 30},
        ]
        html = expansion_timeline(steps, target=25, target_met=True)
        assert "Step 1" in html
        assert "Step 2" in html
        assert "+5" in html
        assert "+12" in html
        assert "18" in html  # cumulative
        assert "30" in html  # cumulative

    def test_renders_target_met_footer(self):
        """Shows target met message when target_met=True."""
        mock_st.reset_mock()
        steps = [
            {"param": "accuracy_min", "old_value": "accuracy 95",
             "new_value": "accuracy → 85",
             "contacts_found": 10, "new_companies": 5, "cumulative_companies": 25},
        ]
        html = expansion_timeline(steps, target=25, target_met=True, steps_skipped=5)
        assert "Target met" in html
        assert "5" in html  # steps skipped

    def test_renders_target_not_met_footer(self):
        """Shows shortfall message when target_met=False."""
        mock_st.reset_mock()
        steps = [
            {"param": "radius", "old_value": "10mi",
             "new_value": "radius → 20mi",
             "contacts_found": 5, "new_companies": 2, "cumulative_companies": 12},
        ]
        html = expansion_timeline(steps, target=25, target_met=False)
        assert "12" in html
        assert "25" in html

    def test_empty_steps_returns_no_expansion(self):
        """Empty steps list returns a 'no expansion' message."""
        mock_st.reset_mock()
        html = expansion_timeline([], target=25, target_met=True)
        assert "No expansion" in html

    def test_old_value_shown(self):
        """Old value is displayed in each step."""
        mock_st.reset_mock()
        steps = [
            {"param": "radius", "old_value": "10mi",
             "new_value": "radius → 15mi",
             "contacts_found": 8, "new_companies": 3, "cumulative_companies": 18},
        ]
        html = expansion_timeline(steps, target=25, target_met=False)
        assert "10mi" in html
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui_components.py::TestExpansionTimeline -v`
Expected: FAIL with `ImportError: cannot import name 'expansion_timeline'`

**Step 3: Implement `expansion_timeline()`**

Add to `ui_components.py` after `narrative_metric()` (after line ~1810):

```python
def expansion_timeline(
    steps: list[dict],
    target: int,
    target_met: bool,
    steps_skipped: int = 0,
) -> str:
    """
    Render expansion step timeline as styled HTML.

    Args:
        steps: List of step dicts with param, old_value, new_value,
               contacts_found, new_companies, cumulative_companies
        target: Target company count
        target_met: Whether target was met
        steps_skipped: Number of steps skipped after target met

    Returns:
        HTML string (also rendered via st.markdown)
    """
    if not steps:
        html = (
            f'<div style="color:{COLORS["text_secondary"]};font-size:0.9rem;'
            f'padding:{SPACING["sm"]} 0;">No expansion needed</div>'
        )
        st.markdown(html, unsafe_allow_html=True)
        return html

    rows = []
    for i, step in enumerate(steps, 1):
        param_label = {
            "management_levels": "Management",
            "employee_max": "Employees",
            "accuracy_min": "Accuracy",
            "radius": "Radius",
        }.get(step["param"], step["param"])

        new_companies = step.get("new_companies", 0)
        cumulative = step.get("cumulative_companies", 0)

        row = (
            f'<div style="display:flex;align-items:baseline;gap:{SPACING["sm"]};'
            f'padding:{SPACING["xs"]} 0;border-bottom:1px solid {COLORS["border"]}22;">'
            f'<span style="color:{COLORS["text_muted"]};font-size:0.8rem;min-width:3rem;">Step {i}</span>'
            f'<span style="color:{COLORS["primary_light"]};font-weight:600;min-width:6.5rem;'
            f'font-size:0.9rem;">{html_mod.escape(param_label)}</span>'
            f'<span style="color:{COLORS["text_secondary"]};font-family:{FONTS["mono"]};font-size:0.85rem;">'
            f'{html_mod.escape(step.get("old_value", ""))}</span>'
            f'<span style="color:{COLORS["text_muted"]};font-size:0.8rem;">→</span>'
            f'<span style="color:{COLORS["text_primary"]};font-family:{FONTS["mono"]};font-size:0.85rem;">'
            f'{html_mod.escape(step.get("new_value", ""))}</span>'
            f'<span style="margin-left:auto;color:{COLORS["success"]};font-family:{FONTS["mono"]};'
            f'font-size:0.85rem;white-space:nowrap;">+{new_companies} companies ({cumulative} total)</span>'
            f'</div>'
        )
        rows.append(row)

    # Footer
    if target_met:
        footer_color = COLORS["success"]
        footer_text = f"Target met — {steps[-1].get('cumulative_companies', '?')} companies found"
        if steps_skipped > 0:
            footer_text += f". {steps_skipped} expansion step{'s' if steps_skipped != 1 else ''} skipped."
    else:
        footer_color = COLORS["warning"]
        cumulative = steps[-1].get("cumulative_companies", 0) if steps else 0
        footer_text = f"{cumulative} of {target} target companies found after all expansions"

    footer = (
        f'<div style="padding:{SPACING["sm"]} 0;color:{footer_color};font-size:0.9rem;font-weight:500;">'
        f'{footer_text}</div>'
    )

    html = (
        f'<div style="background:{COLORS["bg_secondary"]};border:1px solid {COLORS["border"]};'
        f'border-left:3px solid {COLORS["primary"]};border-radius:{SPACING["xs"]};'
        f'padding:{SPACING["md"]} {SPACING["lg"]};margin-bottom:{SPACING["sm"]};">'
        f'{"".join(rows)}{footer}</div>'
    )

    st.markdown(html, unsafe_allow_html=True)
    return html
```

Also add `import html as html_mod` near the top of `ui_components.py` if not already present (check first — the file already uses `html.escape()` elsewhere, so it may already be imported).

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui_components.py::TestExpansionTimeline -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass

**Step 6: Commit**

```bash
git add ui_components.py tests/test_ui_components.py
git commit -m "feat: add expansion_timeline() UI component

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Wire timeline into Geography Workflow page

**Files:**
- Modify: `pages/2_Geography_Workflow.py:1139-1171`

**Step 1: Read the current expansion summary code**

The current code at lines 1139-1171 of `pages/2_Geography_Workflow.py`:
```python
    exp_result = st.session_state.geo_expansion_result
    if exp_result:
        # ... summary badge ...
        if exp_result["steps_applied"] > 0:
            final = exp_result["final_params"]
            expansions = []
            # ... builds one-line summary ...
            if expansions:
                st.caption(f"Expansions applied: {', '.join(expansions)}")
            st.caption(f"Searches performed: {exp_result['searches_performed']}")
        else:
            st.caption("No expansions needed")
```

**Step 2: Add import**

Add `expansion_timeline` to the existing import from `ui_components` at the top of the file. Find the line that imports from `ui_components` and add `expansion_timeline` to it.

**Step 3: Replace the expansion details block**

Replace the block from `# Show expansion details` (line ~1152) through `st.caption("No expansions needed")` (line ~1171) with:

```python
        # Show expansion timeline
        expansion_steps = exp_result.get("expansion_steps", [])
        total_possible = len(EXPANSION_STEPS)
        steps_skipped = max(0, total_possible - exp_result["steps_applied"] - (total_possible - exp_result["steps_applied"]))

        if expansion_steps or exp_result["steps_applied"] > 0:
            with st.expander(f"Expansion details ({exp_result['steps_applied']} steps, {exp_result['searches_performed']} searches)", expanded=True):
                expansion_timeline(
                    expansion_steps,
                    target=exp_result["target"],
                    target_met=exp_result["target_met"],
                    steps_skipped=total_possible - exp_result["steps_applied"] if exp_result["target_met"] else 0,
                )
        else:
            st.caption("No expansions needed")
```

Also add `EXPANSION_STEPS` to the import from `expand_search` at the top of the file if not already imported.

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass (no test changes in this task — UI wiring only)

**Step 5: Commit**

```bash
git add pages/2_Geography_Workflow.py
git commit -m "feat: wire expansion_timeline into Geography Workflow

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Final verification + commit docs

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -x -q --tb=short`
Expected: All pass (524 + ~8 new = ~532)

**Step 2: Commit design doc + plan**

```bash
git add docs/plans/2026-02-17-expansion-timeline-design.md docs/plans/2026-02-17-expansion-timeline-plan.md
git commit -m "docs: expansion timeline design and implementation plan

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
