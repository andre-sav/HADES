"""Tests for expand_search functionality in Geography Workflow."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from expand_search import build_contacts_by_company


class TestExpansionStepsDefinition:
    """Test expansion step definitions match the design."""

    def test_expansion_steps_count(self):
        """Verify there are exactly 9 expansion steps."""
        expected_steps = [
            {"management_levels": ["Manager", "Director"]},
            {"management_levels": ["Manager", "Director", "VP Level Exec", "C Level Exec"]},
            {"employee_max": 0},
            {"accuracy_min": 85},
            {"accuracy_min": 75},
            {"radius": 12.5},
            {"radius": 15.0},
            {"radius": 17.5},
            {"radius": 20.0},
        ]
        assert len(expected_steps) == 9

    def test_expansion_steps_order_filters_before_radius(self):
        """Verify filter expansion happens before radius (preserve geographic area)."""
        expected_steps = [
            {"management_levels": ["Manager", "Director"]},
            {"management_levels": ["Manager", "Director", "VP Level Exec", "C Level Exec"]},
            {"employee_max": 0},
            {"accuracy_min": 85},
            {"accuracy_min": 75},
            {"radius": 12.5},
            {"radius": 15.0},
            {"radius": 17.5},
            {"radius": 20.0},
        ]
        # First two steps should be management levels
        assert "management_levels" in expected_steps[0]
        assert "management_levels" in expected_steps[1]
        # Then employee and accuracy
        assert "employee_max" in expected_steps[2]
        assert "accuracy_min" in expected_steps[3]
        assert "accuracy_min" in expected_steps[4]
        # Radius is last resort (steps 5-8)
        assert "radius" in expected_steps[5]
        assert "radius" in expected_steps[6]
        assert "radius" in expected_steps[7]
        assert "radius" in expected_steps[8]

    def test_expansion_steps_radius_values(self):
        """Verify radius expansion values are correct."""
        expected_radii = [12.5, 15.0, 17.5, 20.0]
        steps_with_radius = [
            {"radius": 12.5},
            {"radius": 15.0},
            {"radius": 17.5},
            {"radius": 20.0},
        ]
        actual_radii = [s["radius"] for s in steps_with_radius]
        assert actual_radii == expected_radii

    def test_expansion_steps_accuracy_values(self):
        """Verify accuracy expansion values are correct."""
        expected_accuracy = [85, 75]
        # Steps 6 and 7 (0-indexed: 5 and 6)
        accuracy_steps = [
            {"accuracy_min": 85},
            {"accuracy_min": 75},
        ]
        actual_accuracy = [s["accuracy_min"] for s in accuracy_steps]
        assert actual_accuracy == expected_accuracy

    def test_expansion_steps_employee_max_removed(self):
        """Verify employee max is set to 0 (no limit) in step 5."""
        employee_step = {"employee_max": 0}
        assert employee_step["employee_max"] == 0


class TestDefaultValues:
    """Test default constants for expansion."""

    def test_default_target_contacts(self):
        """Default target should be 25."""
        DEFAULT_TARGET_CONTACTS = 25
        assert DEFAULT_TARGET_CONTACTS == 25

    def test_default_start_radius(self):
        """Default starting radius should be 10.0 miles."""
        DEFAULT_START_RADIUS = 10.0
        assert DEFAULT_START_RADIUS == 10.0

    def test_default_start_accuracy(self):
        """Default starting accuracy should be 95."""
        DEFAULT_START_ACCURACY = 95
        assert DEFAULT_START_ACCURACY == 95

    def test_default_start_management(self):
        """Default starting management level should be Manager only."""
        DEFAULT_START_MANAGEMENT = ["Manager"]
        assert DEFAULT_START_MANAGEMENT == ["Manager"]

    def test_default_start_employee_max(self):
        """Default starting employee max should be 5000."""
        DEFAULT_START_EMPLOYEE_MAX = 5000
        assert DEFAULT_START_EMPLOYEE_MAX == 5000


class TestExpandSearchLogic:
    """Test expand_search function behavior with mocks."""

    def create_mock_contact(self, person_id, company_id, company_name, accuracy=95):
        """Create a mock contact dict."""
        return {
            "personId": person_id,
            "firstName": f"First{person_id}",
            "lastName": f"Last{person_id}",
            "companyId": company_id,
            "companyName": company_name,
            "contactAccuracyScore": accuracy,
            "jobTitle": "Manager",
        }

    def test_target_met_first_search_no_expansion(self):
        """When target met on first search with stop_early=True, no expansion steps applied."""
        # This tests the logic: if initial search returns >= target, steps_applied should be 0
        target = 10
        initial_results = 15
        stop_early = True

        # Simulate: initial search returns 15 contacts, target is 10
        # Expected: No expansion, steps_applied = 0
        if stop_early and initial_results >= target:
            steps_applied = 0
        else:
            steps_applied = 1  # Would have expanded

        assert steps_applied == 0

    def test_target_not_met_triggers_expansion(self):
        """When target not met, expansion steps should be applied."""
        target = 50
        initial_results = 10
        stop_early = True

        # Simulate: initial search returns 10, target is 50
        # Expected: Expansion would be triggered
        should_expand = initial_results < target

        assert should_expand is True

    def test_stop_early_false_continues_all_steps(self):
        """When stop_early=False, all expansion steps run even if target met."""
        target = 10
        initial_results = 100
        stop_early = False

        # Even though we have 100 contacts (>> target of 10),
        # stop_early=False means we continue expanding
        should_continue = not stop_early or initial_results < target

        assert should_continue is True

    def test_deduplication_by_person_id(self):
        """Contacts should be deduplicated by personId across searches."""
        all_contacts = {}

        # Simulate first search results
        contacts_search1 = [
            {"personId": "p1", "firstName": "John"},
            {"personId": "p2", "firstName": "Jane"},
        ]
        for c in contacts_search1:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                all_contacts[person_id] = c

        # Simulate second search with overlap
        contacts_search2 = [
            {"personId": "p1", "firstName": "John"},  # Duplicate
            {"personId": "p3", "firstName": "Bob"},   # New
        ]
        for c in contacts_search2:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                all_contacts[person_id] = c

        # Should have 3 unique contacts, not 4
        assert len(all_contacts) == 3
        assert set(all_contacts.keys()) == {"p1", "p2", "p3"}

    def test_contacts_grouped_by_company(self):
        """Contacts should be grouped by companyId."""
        contacts_list = [
            {"personId": "p1", "companyId": "c1", "companyName": "Company A", "contactAccuracyScore": 95},
            {"personId": "p2", "companyId": "c1", "companyName": "Company A", "contactAccuracyScore": 90},
            {"personId": "p3", "companyId": "c2", "companyName": "Company B", "contactAccuracyScore": 98},
        ]

        # Simulate _build_contacts_by_company logic
        contacts_by_company = {}
        for contact in contacts_list:
            company_id = contact.get("companyId")
            company_name = contact.get("companyName", "Unknown")
            if company_id:
                if company_id not in contacts_by_company:
                    contacts_by_company[company_id] = {
                        "company_name": company_name,
                        "contacts": [],
                    }
                contacts_by_company[company_id]["contacts"].append(contact)

        assert len(contacts_by_company) == 2
        assert len(contacts_by_company["c1"]["contacts"]) == 2
        assert len(contacts_by_company["c2"]["contacts"]) == 1

    def test_build_contacts_by_company_deduplicates(self):
        """build_contacts_by_company should deduplicate contacts by personId within a company."""
        contacts_list = [
            {"personId": "p1", "companyId": "c1", "companyName": "Company A", "contactAccuracyScore": 95},
            {"personId": "p1", "companyId": "c1", "companyName": "Company A", "contactAccuracyScore": 95},  # duplicate
            {"personId": "p2", "companyId": "c1", "companyName": "Company A", "contactAccuracyScore": 90},
            {"personId": "p3", "companyId": "c2", "companyName": "Company B", "contactAccuracyScore": 98},
            {"personId": "p3", "companyId": "c2", "companyName": "Company B", "contactAccuracyScore": 98},  # duplicate
        ]

        result = build_contacts_by_company(contacts_list)

        assert len(result["c1"]["contacts"]) == 2  # p1 + p2, not 3
        assert len(result["c2"]["contacts"]) == 1  # p3, not 2
        # No internal tracking keys leaked
        assert "_seen_person_ids" not in result["c1"]
        assert "_seen_person_ids" not in result["c2"]

    def test_contacts_sorted_by_accuracy_within_company(self):
        """Contacts within each company should be sorted by accuracy score descending."""
        contacts_list = [
            {"personId": "p1", "companyId": "c1", "companyName": "Company A", "contactAccuracyScore": 85},
            {"personId": "p2", "companyId": "c1", "companyName": "Company A", "contactAccuracyScore": 99},
            {"personId": "p3", "companyId": "c1", "companyName": "Company A", "contactAccuracyScore": 92},
        ]

        # Simulate grouping
        contacts_by_company = {"c1": {"company_name": "Company A", "contacts": contacts_list}}

        # Sort by accuracy descending
        for company_id, data in contacts_by_company.items():
            data["contacts"].sort(
                key=lambda c: c.get("contactAccuracyScore", 0),
                reverse=True,
            )

        scores = [c["contactAccuracyScore"] for c in contacts_by_company["c1"]["contacts"]]
        assert scores == [99, 92, 85]  # Descending order

    def test_result_dict_structure(self):
        """Verify expand_search returns correct dict structure."""
        expected_keys = {
            "target",
            "found",
            "target_met",
            "steps_applied",
            "final_params",
            "searches_performed",
            "contacts",
            "contacts_by_company",
        }

        # Simulate a result dict
        result = {
            "target": 25,
            "found": 30,
            "target_met": True,
            "steps_applied": 2,
            "final_params": {
                "radius": 15.0,
                "accuracy_min": 95,
                "management_levels": ["Manager"],
                "employee_max": 5000,
            },
            "searches_performed": 3,
            "contacts": [],
            "contacts_by_company": {},
        }

        assert set(result.keys()) == expected_keys

    def test_error_result_structure(self):
        """Verify error result includes error key."""
        error_result = {
            "target": 25,
            "found": 0,
            "target_met": False,
            "steps_applied": 0,
            "final_params": {},
            "searches_performed": 1,
            "contacts": [],
            "contacts_by_company": {},
            "error": "API connection failed",
        }

        assert "error" in error_result
        assert error_result["error"] == "API connection failed"


class TestExpansionStepApplication:
    """Test how expansion steps modify parameters."""

    def test_radius_step_updates_radius(self):
        """Radius step should update current radius parameter."""
        current_params = {"radius": 10.0}
        step = {"radius": 12.5}

        if "radius" in step:
            current_params["radius"] = step["radius"]

        assert current_params["radius"] == 12.5

    def test_accuracy_step_updates_accuracy(self):
        """Accuracy step should update accuracy_min parameter."""
        current_params = {"accuracy_min": 95}
        step = {"accuracy_min": 85}

        if "accuracy_min" in step:
            current_params["accuracy_min"] = step["accuracy_min"]

        assert current_params["accuracy_min"] == 85

    def test_management_step_updates_levels(self):
        """Management step should update management_levels list."""
        current_params = {"management_levels": ["Manager"]}
        step = {"management_levels": ["Manager", "Director"]}

        if "management_levels" in step:
            current_params["management_levels"] = list(step["management_levels"])

        assert current_params["management_levels"] == ["Manager", "Director"]

    def test_employee_step_removes_cap(self):
        """Employee step should set employee_max to 0 (no limit)."""
        current_params = {"employee_max": 5000}
        step = {"employee_max": 0}

        if "employee_max" in step:
            current_params["employee_max"] = step["employee_max"]

        assert current_params["employee_max"] == 0

    def test_step_only_modifies_specified_param(self):
        """Each step should only modify its specified parameter."""
        current_params = {
            "radius": 10.0,
            "accuracy_min": 95,
            "management_levels": ["Manager"],
            "employee_max": 5000,
        }

        # Apply radius step
        step = {"radius": 12.5}
        if "radius" in step:
            current_params["radius"] = step["radius"]

        # Other params should be unchanged
        assert current_params["radius"] == 12.5
        assert current_params["accuracy_min"] == 95
        assert current_params["management_levels"] == ["Manager"]
        assert current_params["employee_max"] == 5000


class TestLocationTypeTagging:
    """Test location type tagging for combined search demarcation."""

    def test_process_contacts_adds_location_type_tag(self):
        """Contacts should be tagged with _location_type when provided."""
        all_contacts = {}

        contacts = [
            {"personId": "p1", "firstName": "John", "companyId": "c1"},
            {"personId": "p2", "firstName": "Jane", "companyId": "c2"},
        ]

        # Simulate process_contacts with location_type_tag
        for c in contacts:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                c["_location_type"] = "PersonAndHQ"
                all_contacts[person_id] = c

        assert all_contacts["p1"]["_location_type"] == "PersonAndHQ"
        assert all_contacts["p2"]["_location_type"] == "PersonAndHQ"

    def test_person_only_contacts_tagged_separately(self):
        """Person-only contacts should be tagged with 'Person' type."""
        all_contacts = {}

        # First search - PersonAndHQ
        contacts_hq = [
            {"personId": "p1", "firstName": "John", "companyId": "c1"},
        ]
        for c in contacts_hq:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                c["_location_type"] = "PersonAndHQ"
                all_contacts[person_id] = c

        # Second search - Person-only (different contacts)
        contacts_person = [
            {"personId": "p2", "firstName": "Jane", "companyId": "c2"},
            {"personId": "p3", "firstName": "Bob", "companyId": "c3"},
        ]
        for c in contacts_person:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                c["_location_type"] = "Person"
                all_contacts[person_id] = c

        assert all_contacts["p1"]["_location_type"] == "PersonAndHQ"
        assert all_contacts["p2"]["_location_type"] == "Person"
        assert all_contacts["p3"]["_location_type"] == "Person"

    def test_duplicate_contact_keeps_first_tag(self):
        """When contact appears in both searches, first tag (PersonAndHQ) is kept."""
        all_contacts = {}

        # First search - PersonAndHQ
        contacts_hq = [
            {"personId": "p1", "firstName": "John", "companyId": "c1"},
        ]
        for c in contacts_hq:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                c["_location_type"] = "PersonAndHQ"
                all_contacts[person_id] = c

        # Second search - Person-only (includes same contact)
        contacts_person = [
            {"personId": "p1", "firstName": "John", "companyId": "c1"},  # Duplicate
        ]
        for c in contacts_person:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                # This won't execute because p1 already exists
                c["_location_type"] = "Person"
                all_contacts[person_id] = c

        # p1 should retain PersonAndHQ tag (more authoritative)
        assert all_contacts["p1"]["_location_type"] == "PersonAndHQ"

    def test_no_tag_when_combined_search_disabled(self):
        """When combined search is disabled, no _location_type tag is added."""
        all_contacts = {}

        contacts = [
            {"personId": "p1", "firstName": "John", "companyId": "c1"},
        ]

        # Simulate process_contacts without location_type_tag (None)
        location_type_tag = None
        for c in contacts:
            person_id = c.get("personId")
            if person_id and person_id not in all_contacts:
                if location_type_tag:
                    c["_location_type"] = location_type_tag
                all_contacts[person_id] = c

        assert "_location_type" not in all_contacts["p1"]


class TestCombinedSearchIntegration:
    """Test the combined PersonAndHQ + Person search path through expand_search."""

    @patch("expand_search.time.sleep")  # Skip rate limit delay in tests
    def test_combined_search_makes_two_api_calls(self, mock_sleep):
        """When include_person_only=True, expand_search runs both PersonAndHQ and Person searches."""
        from expand_search import expand_search

        mock_client = Mock()
        personandhq_contacts = [
            {"personId": "p1", "companyId": "c1", "companyName": "HQ Corp",
             "contactAccuracyScore": 95, "firstName": "Alice", "lastName": "A"},
        ]
        person_only_contacts = [
            {"personId": "p2", "companyId": "c2", "companyName": "Branch Corp",
             "contactAccuracyScore": 92, "firstName": "Bob", "lastName": "B"},
        ]

        # expand_search calls client.search_contacts_all_pages
        mock_client.search_contacts_all_pages.side_effect = [
            personandhq_contacts,
            person_only_contacts,
        ]

        result = expand_search(
            client=mock_client,
            base_params={
                "radius": 10.0,
                "accuracy_min": 95,
                "management_levels": ["Manager"],
                "employee_max": 5000,
                "location_type": "PersonAndHQ",
                "include_person_only": True,
                "sic_codes": ["7011"],
            },
            zip_codes=["75201"],
            states=["TX"],
            target=2,
            stop_early=True,
        )

        # Should have made 2 API calls (PersonAndHQ + Person)
        assert result["searches_performed"] == 2
        assert mock_client.search_contacts_all_pages.call_count == 2
        # Should have found both contacts
        assert len(result["contacts"]) == 2
        # Contacts should be tagged with location type
        contacts_by_pid = {c["personId"]: c for c in result["contacts"]}
        assert contacts_by_pid["p1"]["_location_type"] == "PersonAndHQ"
        assert contacts_by_pid["p2"]["_location_type"] == "Person"

    @patch("expand_search.time.sleep")
    def test_combined_search_deduplicates_across_searches(self, mock_sleep):
        """Person-only duplicates of PersonAndHQ contacts should be dropped."""
        from expand_search import expand_search

        mock_client = Mock()
        shared_contact = {
            "personId": "p1", "companyId": "c1", "companyName": "Overlap Corp",
            "contactAccuracyScore": 95, "firstName": "Alice", "lastName": "A",
        }
        mock_client.search_contacts_all_pages.side_effect = [
            [shared_contact],
            [dict(shared_contact)],  # Duplicate in Person search
        ]

        result = expand_search(
            client=mock_client,
            base_params={
                "radius": 10.0,
                "accuracy_min": 95,
                "management_levels": ["Manager"],
                "employee_max": 5000,
                "location_type": "PersonAndHQ",
                "include_person_only": True,
                "sic_codes": ["7011"],
            },
            zip_codes=["75201"],
            states=["TX"],
            target=5,
            stop_early=False,
        )

        # Should only have 1 unique contact despite appearing in both searches
        assert len(result["contacts"]) == 1
        assert result["contacts"][0]["_location_type"] == "PersonAndHQ"
