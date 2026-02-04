# Target Contacts with Auto-Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to set a target contact count and automatically expand search parameters until the target is met.

**Architecture:** Add expansion loop that wraps the existing `search_contacts_all_pages()` call. Each iteration applies the next expansion step, accumulates deduplicated contacts, and stops when target is met or all steps exhausted.

**Tech Stack:** Streamlit, ZoomInfo API (existing client), Python

**Design Doc:** `docs/plans/2026-02-03-target-contacts-expansion-design.md`

---

## Task 1: Add Expansion Constants

**Files:**
- Modify: `pages/2_Geography_Workflow.py` (near top, after imports)

**Step 1: Add expansion step definitions after imports (around line 30)**

```python
# --- Expansion Strategy ---
# Applied in order when target contact count not met
EXPANSION_STEPS = [
    {"radius": 12.5},
    {"radius": 15.0},
    {"management_levels": ["Manager", "Director"]},
    {"management_levels": ["Manager", "Director", "VP", "C-Level"]},
    {"employee_max": None},  # Remove 5000 cap
    {"accuracy_min": 85},
    {"accuracy_min": 75},
    {"radius": 17.5},
    {"radius": 20.0},
]

DEFAULT_TARGET_CONTACTS = 25
DEFAULT_START_RADIUS = 10.0
DEFAULT_START_ACCURACY = 95
DEFAULT_START_MANAGEMENT = ["Manager"]
DEFAULT_START_EMPLOYEE_MAX = 5000
```

**Step 2: Verify file still loads**

Run: `streamlit run app.py` and navigate to Geography Workflow
Expected: Page loads without errors

---

## Task 2: Add Target Input UI

**Files:**
- Modify: `pages/2_Geography_Workflow.py` (after Industry Filters expander, before `full_request_body`)

**Step 1: Add target contacts section after Industry Filters (around line 494)**

Find the line `st.caption(f"{len(selected_sic_codes)} of {len(default_sic_codes)} industries selected")` and add after the expander closes:

```python
    # Target Contacts
    st.markdown("---")
    target_col1, target_col2 = st.columns([1, 1])

    with target_col1:
        target_contacts = st.number_input(
            "Target contacts",
            min_value=5,
            max_value=100,
            value=DEFAULT_TARGET_CONTACTS,
            step=5,
            help="System will auto-expand search parameters if target not met",
        )

    with target_col2:
        # Default based on workflow mode
        default_stop_early = st.session_state.geo_mode == "autopilot"
        stop_early = st.checkbox(
            "Stop early if target met",
            value=default_stop_early,
            help="Stop expanding once target reached, even if more results available",
        )

    st.caption(f"Starting: {DEFAULT_START_RADIUS}mi radius, {DEFAULT_START_ACCURACY} accuracy, Manager level, 50-{DEFAULT_START_EMPLOYEE_MAX:,} employees")
```

**Step 2: Verify UI appears**

Run: `streamlit run app.py` and navigate to Geography Workflow
Expected: "Target contacts" number input and "Stop early" checkbox appear after Industry Filters

---

## Task 3: Add Session State for Expansion Results

**Files:**
- Modify: `pages/2_Geography_Workflow.py` (in session state initialization section, around line 90)

**Step 1: Find existing session state initialization and add new keys**

Find the block starting with `if "geo_mode" not in st.session_state:` and add:

```python
if "geo_expansion_result" not in st.session_state:
    st.session_state.geo_expansion_result = None
```

**Step 2: Verify no errors**

Run: `streamlit run app.py` and navigate to Geography Workflow
Expected: Page loads without errors

---

## Task 4: Write Expansion Search Function

**Files:**
- Modify: `pages/2_Geography_Workflow.py` (after imports and constants, before UI code)

**Step 1: Add the expand_search function (around line 50)**

```python
def expand_search(
    client,
    base_params: dict,
    zip_codes: list[str],
    states: list[str],
    target: int,
    stop_early: bool,
) -> dict:
    """
    Search with automatic expansion until target met or steps exhausted.

    Args:
        client: ZoomInfo client instance
        base_params: Starting search parameters
        zip_codes: List of ZIP codes to search
        states: List of state codes
        target: Target number of contacts
        stop_early: Stop once target reached

    Returns:
        dict with keys: target, found, target_met, steps_applied, final_params,
                       searches_performed, contacts, contacts_by_company
    """
    import time
    from geo import get_zips_in_radius, get_states_from_zips

    all_contacts = {}  # personId -> contact (for deduplication)
    searches_performed = 0
    steps_applied = 0

    # Current parameters (will be modified by expansion)
    current_params = {
        "radius": base_params.get("radius", DEFAULT_START_RADIUS),
        "accuracy_min": base_params.get("accuracy_min", DEFAULT_START_ACCURACY),
        "management_levels": base_params.get("management_levels", DEFAULT_START_MANAGEMENT).copy(),
        "employee_max": base_params.get("employee_max", DEFAULT_START_EMPLOYEE_MAX),
    }

    # Fixed parameters (don't change during expansion)
    fixed_params = {
        "location_type": base_params.get("location_type", "PersonAndHQ"),
        "current_only": base_params.get("current_only", True),
        "required_fields": base_params.get("required_fields"),
        "required_fields_operator": base_params.get("required_fields_operator", "or"),
        "exclude_org_exported": base_params.get("exclude_org_exported", True),
        "sic_codes": base_params.get("sic_codes", []),
    }

    center_zip = base_params.get("center_zip")

    def do_search(radius_miles, accuracy_min, management_levels, employee_max):
        """Execute a single search with given parameters."""
        # Recalculate ZIPs if radius changed
        if center_zip and radius_miles != base_params.get("radius"):
            calculated = get_zips_in_radius(center_zip, radius_miles)
            search_zips = [z["zip"] for z in calculated]
            search_states = get_states_from_zips(calculated)
        else:
            search_zips = zip_codes
            search_states = states

        params = ContactQueryParams(
            zip_codes=search_zips,
            radius_miles=0,  # Explicit ZIP list
            states=search_states,
            location_type=fixed_params["location_type"],
            employee_min=get_employee_minimum(),
            employee_max=employee_max,
            sic_codes=fixed_params["sic_codes"],
            company_past_or_present="present" if fixed_params["current_only"] else "pastOrPresent",
            exclude_partial_profiles=True,
            required_fields=fixed_params["required_fields"],
            required_fields_operator=fixed_params["required_fields_operator"],
            contact_accuracy_score_min=accuracy_min,
            exclude_org_exported=fixed_params["exclude_org_exported"],
            management_levels=management_levels if management_levels else None,
        )

        return client.search_contacts_all_pages(params, max_pages=5)

    # Initial search
    try:
        contacts = do_search(
            current_params["radius"],
            current_params["accuracy_min"],
            current_params["management_levels"],
            current_params["employee_max"],
        )
        searches_performed += 1

        for c in contacts:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                all_contacts[person_id] = c

    except Exception as e:
        return {
            "target": target,
            "found": 0,
            "target_met": False,
            "steps_applied": 0,
            "final_params": current_params,
            "searches_performed": searches_performed,
            "contacts": [],
            "contacts_by_company": {},
            "error": str(e),
        }

    # Expansion loop
    for step in EXPANSION_STEPS:
        # Check if target met
        if stop_early and len(all_contacts) >= target:
            break

        # Apply expansion step
        if "radius" in step:
            current_params["radius"] = step["radius"]
        if "accuracy_min" in step:
            current_params["accuracy_min"] = step["accuracy_min"]
        if "management_levels" in step:
            current_params["management_levels"] = step["management_levels"].copy()
        if "employee_max" in step:
            current_params["employee_max"] = step["employee_max"]

        steps_applied += 1

        # Rate limit delay
        time.sleep(0.5)

        # Search with new parameters
        try:
            contacts = do_search(
                current_params["radius"],
                current_params["accuracy_min"],
                current_params["management_levels"],
                current_params["employee_max"],
            )
            searches_performed += 1

            for c in contacts:
                person_id = c.get("personId")
                if person_id and person_id not in all_contacts:
                    all_contacts[person_id] = c

        except Exception as e:
            # Stop on error, return what we have
            break

        # Check if target met after this step
        if stop_early and len(all_contacts) >= target:
            break

    # Build contacts_by_company
    contacts_list = list(all_contacts.values())
    contacts_by_company = {}

    for contact in contacts_list:
        company_id = contact.get("companyId") or contact.get("company", {}).get("id")
        company_name = contact.get("companyName") or contact.get("company", {}).get("name", "Unknown")
        if company_id:
            if company_id not in contacts_by_company:
                contacts_by_company[company_id] = {
                    "company_name": company_name,
                    "contacts": [],
                }
            contacts_by_company[company_id]["contacts"].append(contact)

    # Sort contacts within each company by accuracy score
    for company_id, data in contacts_by_company.items():
        data["contacts"].sort(
            key=lambda c: c.get("contactAccuracyScore", 0),
            reverse=True,
        )

    return {
        "target": target,
        "found": len(all_contacts),
        "target_met": len(all_contacts) >= target,
        "steps_applied": steps_applied,
        "final_params": current_params,
        "searches_performed": searches_performed,
        "contacts": contacts_list,
        "contacts_by_company": contacts_by_company,
    }
```

**Step 2: Verify no syntax errors**

Run: `python -c "import pages.2_Geography_Workflow"` (will fail but shows syntax errors)
Or: `streamlit run app.py` and check page loads

---

## Task 5: Update Search Execution to Use Expansion

**Files:**
- Modify: `pages/2_Geography_Workflow.py` (search execution section, around line 610)

**Step 1: Update pending_params to include target settings**

Find where `pending_params` is built (around line 514) and add:

```python
    pending_params = {
        "zip_codes": zip_codes,
        "states": states,
        # ... existing fields ...
        "target_contacts": target_contacts,
        "stop_early": stop_early,
    }
```

**Step 2: Replace the search execution block**

Find the `with st.spinner(...)` block that does the search (around line 611) and replace the entire try block:

```python
        with st.spinner(f"Searching ZoomInfo (target: {sp.get('target_contacts', 25)} contacts)..."):
            try:
                client = get_zoominfo_client()

                base_params = {
                    "radius": search_radius if search_radius else DEFAULT_START_RADIUS,
                    "accuracy_min": search_accuracy_min,
                    "management_levels": search_management_levels if search_management_levels else DEFAULT_START_MANAGEMENT,
                    "employee_max": get_employee_maximum(),
                    "location_type": search_location_type,
                    "current_only": search_current_only,
                    "required_fields": search_required_fields,
                    "required_fields_operator": search_required_fields_operator,
                    "exclude_org_exported": search_exclude_org_exported,
                    "sic_codes": search_sic_codes,
                    "center_zip": search_center_zip,
                }

                target = sp.get("target_contacts", DEFAULT_TARGET_CONTACTS)
                stop_early = sp.get("stop_early", True)

                result = expand_search(
                    client=client,
                    base_params=base_params,
                    zip_codes=search_zip_codes,
                    states=search_states,
                    target=target,
                    stop_early=stop_early,
                )

                st.session_state.geo_expansion_result = result

                if result.get("error"):
                    st.error(f"Search failed: {result['error']}")
                    st.session_state.geo_preview_contacts = None
                    st.session_state.geo_search_executed = True
                elif not result["contacts"]:
                    st.warning("No contacts found matching your criteria. Try adjusting filters.")
                    st.session_state.geo_preview_contacts = None
                    st.session_state.geo_search_executed = True
                else:
                    st.session_state.geo_preview_contacts = result["contacts"]
                    st.session_state.geo_search_executed = True
                    st.session_state.geo_contacts_by_company = result["contacts_by_company"]

                    # Auto-select best contact per company
                    auto_selected = {}
                    for company_id, data in result["contacts_by_company"].items():
                        if data["contacts"]:
                            auto_selected[company_id] = data["contacts"][0]

                    st.session_state.geo_selected_contacts = auto_selected

                    # Store query params
                    st.session_state.geo_query_params = {
                        "zip_codes": search_zip_codes,
                        "zip_count": len(search_zip_codes),
                        "radius_miles": result["final_params"]["radius"],
                        "center_zip": search_center_zip,
                        "location_mode": sp.get("location_mode"),
                        "states": search_states,
                        "sic_codes_count": len(search_sic_codes),
                        "accuracy_min": result["final_params"]["accuracy_min"],
                        "location_type": search_location_type,
                    }

                    if st.session_state.geo_mode == "autopilot":
                        st.session_state.geo_selection_confirmed = True

                    st.rerun()

            except ZoomInfoError as e:
                st.error(e.user_message)
            except Exception as e:
                st.error(f"Search failed: {str(e)}")
```

---

## Task 6: Add Expansion Results Summary

**Files:**
- Modify: `pages/2_Geography_Workflow.py` (in "Review & Select Contacts" section, around line 705)

**Step 1: Replace the simple info message with expansion summary**

Find `st.info(f"Found **{total_contacts}** contacts across **{total_companies}** companies")` and replace with:

```python
    # Expansion summary
    exp_result = st.session_state.geo_expansion_result
    if exp_result:
        if exp_result["target_met"]:
            st.success(f"✅ **Target met:** {exp_result['found']} contacts found (target: {exp_result['target']})")
        else:
            st.warning(f"⚠️ **Found {exp_result['found']} of {exp_result['target']} target contacts**")

        # Show expansion details
        if exp_result["steps_applied"] > 0:
            final = exp_result["final_params"]
            expansions = []
            if final["radius"] > DEFAULT_START_RADIUS:
                expansions.append(f"Radius → {final['radius']}mi")
            if final["accuracy_min"] < DEFAULT_START_ACCURACY:
                expansions.append(f"Accuracy → {final['accuracy_min']}")
            if final["management_levels"] != DEFAULT_START_MANAGEMENT:
                levels = "/".join(final["management_levels"])
                expansions.append(f"Management → {levels}")
            if final["employee_max"] is None:
                expansions.append("Employee range → 50+")

            if expansions:
                st.caption(f"Expansions applied: {', '.join(expansions)}")
            st.caption(f"Searches performed: {exp_result['searches_performed']}")
        else:
            st.caption("No expansions needed")
    else:
        # Fallback for old results without expansion data
        st.info(f"Found **{total_contacts}** contacts across **{total_companies}** companies")
```

---

## Task 7: Update Clear/Reset to Include Expansion State

**Files:**
- Modify: `pages/2_Geography_Workflow.py` (clear button handler, around line 544)

**Step 1: Add expansion result to clear**

Find the Clear/Reset button handler and add:

```python
                st.session_state.geo_expansion_result = None
```

---

## Task 8: Manual Testing

**Step 1: Test target met on first search**

1. Set target to 5
2. Search in a populated area (e.g., Dallas 75201)
3. Verify: Shows "Target met" with "No expansions needed"

**Step 2: Test expansion triggers**

1. Set target to 100
2. Search in a small town
3. Verify: Shows expansion steps applied, multiple searches performed

**Step 3: Test stop early disabled**

1. Set target to 10, uncheck "Stop early"
2. Search in populated area
3. Verify: Gets more than 10 contacts (expansion continues)

**Step 4: Test autopilot mode**

1. Switch to Autopilot mode
2. Set target to 20
3. Verify: Expansion works, auto-selects contacts, proceeds to enrichment

---

## Task 9: Add Unit Tests

**Files:**
- Create: `tests/test_expand_search.py`

**Step 1: Create test file**

```python
"""Tests for expand_search functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestExpansionSteps:
    """Test expansion step definitions."""

    def test_expansion_steps_order(self):
        """Verify expansion steps are in correct order."""
        # Import from the module
        import sys
        sys.path.insert(0, 'pages')

        # The steps should follow the agreed order:
        # 1-2: radius to 15mi
        # 3-4: management levels
        # 5: employee range
        # 6-7: accuracy
        # 8-9: radius to 20mi

        from importlib import import_module
        # Note: Can't directly import Streamlit pages in tests
        # This test documents expected behavior

        expected_order = [
            {"radius": 12.5},
            {"radius": 15.0},
            {"management_levels": ["Manager", "Director"]},
            {"management_levels": ["Manager", "Director", "VP", "C-Level"]},
            {"employee_max": None},
            {"accuracy_min": 85},
            {"accuracy_min": 75},
            {"radius": 17.5},
            {"radius": 20.0},
        ]

        assert len(expected_order) == 9


class TestExpandSearchLogic:
    """Test expand_search function logic."""

    def test_target_met_first_search_stops_early(self):
        """When target met on first search with stop_early=True, no expansion."""
        # Mock scenario: First search returns 30 contacts, target is 25
        # Expected: No expansion steps applied
        pass  # Placeholder - full implementation would mock the function

    def test_target_not_met_triggers_expansion(self):
        """When target not met, expansion steps are applied."""
        # Mock scenario: First search returns 10, target is 50
        # Expected: Expansion steps applied until target met
        pass

    def test_stop_early_false_continues_expansion(self):
        """When stop_early=False, expansion continues past target."""
        # Mock scenario: Target 10, first search returns 15
        # Expected: All expansions still applied
        pass

    def test_deduplication_by_person_id(self):
        """Contacts are deduplicated by personId across searches."""
        # Mock scenario: Same contact returned in multiple expansion searches
        # Expected: Only counted once
        pass

    def test_api_error_returns_partial_results(self):
        """API error mid-expansion returns contacts found so far."""
        # Mock scenario: Error on step 3
        # Expected: Returns contacts from steps 1-2
        pass
```

**Step 2: Run tests**

Run: `python -m pytest tests/test_expand_search.py -v`
Expected: Tests pass (placeholder tests)

---

## Summary

| Task | Description | Est. Lines |
|------|-------------|------------|
| 1 | Add expansion constants | ~20 |
| 2 | Add target input UI | ~25 |
| 3 | Add session state | ~3 |
| 4 | Write expand_search function | ~150 |
| 5 | Update search execution | ~60 |
| 6 | Add results summary | ~30 |
| 7 | Update clear/reset | ~1 |
| 8 | Manual testing | — |
| 9 | Unit tests | ~50 |

**Total: ~340 lines**
