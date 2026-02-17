"""
Tests for ui_components module - workflow_run_state and export_validation_checklist.

Run with: pytest tests/test_ui_components.py -v
"""

import sys
import pytest
from unittest.mock import MagicMock, patch

# Mock streamlit before importing
mock_st = MagicMock()
mock_st.session_state = {}
sys.modules["streamlit"] = mock_st

from ui_components import workflow_run_state, export_validation_checklist, narrative_metric, company_card_header, score_breakdown


class TestWorkflowRunState:
    """Tests for workflow_run_state() deriving state from session state."""

    def setup_method(self):
        """Reset mock session state before each test."""
        mock_st.session_state = {}

    def test_idle_state_intent(self):
        """Intent workflow: no search executed, no companies = idle."""
        mock_st.session_state = {
            "intent_search_executed": False,
            "intent_companies": None,
            "intent_exported": False,
            "intent_enrichment_done": False,
            "intent_contacts_by_company": None,
        }
        assert workflow_run_state("intent") == "idle"

    def test_idle_state_geo(self):
        """Geo workflow: no search executed, no contacts = idle."""
        mock_st.session_state = {
            "geo_search_executed": False,
            "geo_preview_contacts": None,
            "geo_exported": False,
            "geo_enrichment_done": False,
            "geo_contacts_by_company": None,
        }
        assert workflow_run_state("geo") == "idle"

    def test_searched_state_intent(self):
        """Intent workflow: search executed with companies = searched."""
        mock_st.session_state = {
            "intent_search_executed": True,
            "intent_companies": [{"companyId": "1"}],
            "intent_exported": False,
            "intent_enrichment_done": False,
            "intent_contacts_by_company": None,
            "intent_mode": "autopilot",
            "intent_companies_confirmed": True,
        }
        assert workflow_run_state("intent") == "searched"

    def test_searched_state_geo(self):
        """Geo workflow: search executed with preview contacts = searched."""
        mock_st.session_state = {
            "geo_search_executed": True,
            "geo_preview_contacts": [{"personId": "1"}],
            "geo_exported": False,
            "geo_enrichment_done": False,
            "geo_contacts_by_company": None,
        }
        assert workflow_run_state("geo") == "searched"

    def test_selecting_state_intent(self):
        """Intent workflow: manual mode, companies found, not confirmed = selecting."""
        mock_st.session_state = {
            "intent_search_executed": True,
            "intent_companies": [{"companyId": "1"}],
            "intent_exported": False,
            "intent_enrichment_done": False,
            "intent_contacts_by_company": None,
            "intent_mode": "manual",
            "intent_companies_confirmed": False,
        }
        assert workflow_run_state("intent") == "selecting"

    def test_contacts_found_state_intent(self):
        """Intent workflow: contacts by company populated = contacts_found."""
        mock_st.session_state = {
            "intent_search_executed": True,
            "intent_companies": [{"companyId": "1"}],
            "intent_exported": False,
            "intent_enrichment_done": False,
            "intent_contacts_by_company": {"1": {"contacts": [{}], "company_name": "Test"}},
        }
        assert workflow_run_state("intent") == "contacts_found"

    def test_contacts_found_state_geo(self):
        """Geo workflow: contacts by company populated = contacts_found."""
        mock_st.session_state = {
            "geo_search_executed": True,
            "geo_preview_contacts": [{"personId": "1"}],
            "geo_exported": False,
            "geo_enrichment_done": False,
            "geo_contacts_by_company": {"1": {"contacts": [{}], "company_name": "Test"}},
        }
        assert workflow_run_state("geo") == "contacts_found"

    def test_enriched_state_intent(self):
        """Intent workflow: enrichment done = enriched."""
        mock_st.session_state = {
            "intent_search_executed": True,
            "intent_companies": [{"companyId": "1"}],
            "intent_exported": False,
            "intent_enrichment_done": True,
            "intent_contacts_by_company": {"1": {"contacts": [{}], "company_name": "Test"}},
        }
        assert workflow_run_state("intent") == "enriched"

    def test_enriched_state_geo(self):
        """Geo workflow: enrichment done = enriched."""
        mock_st.session_state = {
            "geo_search_executed": True,
            "geo_preview_contacts": [{"personId": "1"}],
            "geo_exported": False,
            "geo_enrichment_done": True,
            "geo_contacts_by_company": {"1": {"contacts": [{}], "company_name": "Test"}},
        }
        assert workflow_run_state("geo") == "enriched"

    def test_exported_state_intent(self):
        """Intent workflow: exported flag = exported."""
        mock_st.session_state = {
            "intent_search_executed": True,
            "intent_companies": [{"companyId": "1"}],
            "intent_exported": True,
            "intent_enrichment_done": True,
            "intent_contacts_by_company": {"1": {"contacts": [{}], "company_name": "Test"}},
        }
        assert workflow_run_state("intent") == "exported"

    def test_exported_state_geo(self):
        """Geo workflow: exported flag = exported."""
        mock_st.session_state = {
            "geo_search_executed": True,
            "geo_preview_contacts": [{"personId": "1"}],
            "geo_exported": True,
            "geo_enrichment_done": True,
            "geo_contacts_by_company": {"1": {"contacts": [{}], "company_name": "Test"}},
        }
        assert workflow_run_state("geo") == "exported"

    def test_exported_overrides_all(self):
        """Exported state takes priority over everything else."""
        mock_st.session_state = {
            "intent_exported": True,
            "intent_enrichment_done": True,
            "intent_contacts_by_company": {"1": {"contacts": [{}]}},
            "intent_search_executed": True,
            "intent_companies": [{"companyId": "1"}],
        }
        assert workflow_run_state("intent") == "exported"

    def test_enriched_overrides_contacts_found(self):
        """Enriched state takes priority over contacts_found."""
        mock_st.session_state = {
            "intent_exported": False,
            "intent_enrichment_done": True,
            "intent_contacts_by_company": {"1": {"contacts": [{}]}},
            "intent_search_executed": True,
            "intent_companies": [{"companyId": "1"}],
        }
        assert workflow_run_state("intent") == "enriched"


class TestExportValidationChecklist:
    """Tests for export_validation_checklist() validation logic."""

    def test_empty_leads(self):
        """Empty leads returns empty checklist."""
        result = export_validation_checklist([])
        assert result == []

    def test_all_checks_pass(self):
        """Leads with all fields pass all checks."""
        leads = [
            {
                "directPhone": "555-1234",
                "email": "test@test.com",
                "contactAccuracyScore": 95,
                "personId": "1",
            },
            {
                "phone": "555-5678",
                "email": "test2@test.com",
                "contactAccuracyScore": 90,
                "personId": "2",
            },
        ]
        result = export_validation_checklist(leads)

        assert len(result) == 4
        # All should pass
        for check in result:
            assert check["status"] == "success"
            assert check["failed"] == 0

    def test_missing_phones_detected(self):
        """Leads missing phone numbers are detected."""
        leads = [
            {"personId": "1", "email": "a@b.com", "contactAccuracyScore": 95},
            {"personId": "2", "email": "c@d.com", "contactAccuracyScore": 95, "directPhone": "555"},
        ]
        result = export_validation_checklist(leads)

        phone_check = next(c for c in result if c["check"] == "Has phone number")
        assert phone_check["passed"] == 1
        assert phone_check["failed"] == 1

    def test_missing_emails_detected(self):
        """Leads missing email are detected."""
        leads = [
            {"personId": "1", "directPhone": "555", "contactAccuracyScore": 95},
            {"personId": "2", "directPhone": "666", "contactAccuracyScore": 95, "email": "a@b.com"},
        ]
        result = export_validation_checklist(leads)

        email_check = next(c for c in result if c["check"] == "Has email")
        assert email_check["passed"] == 1
        assert email_check["failed"] == 1

    def test_low_accuracy_detected(self):
        """Leads with low accuracy are detected."""
        leads = [
            {"personId": "1", "contactAccuracyScore": 80, "directPhone": "555", "email": "a@b.com"},
            {"personId": "2", "contactAccuracyScore": 95, "directPhone": "666", "email": "c@d.com"},
        ]
        result = export_validation_checklist(leads)

        acc_check = next(c for c in result if c["check"] == "Accuracy >= 85")
        assert acc_check["passed"] == 1
        assert acc_check["failed"] == 1

    def test_duplicates_detected(self):
        """Duplicate personIds are detected."""
        leads = [
            {"personId": "1", "directPhone": "555", "email": "a@b.com", "contactAccuracyScore": 95},
            {"personId": "1", "directPhone": "555", "email": "a@b.com", "contactAccuracyScore": 95},
            {"personId": "2", "directPhone": "666", "email": "c@d.com", "contactAccuracyScore": 95},
        ]
        result = export_validation_checklist(leads)

        dup_check = next(c for c in result if c["check"] == "No duplicates")
        assert dup_check["passed"] == 2  # 2 unique
        assert dup_check["failed"] == 1  # 1 duplicate

    def test_status_thresholds(self):
        """Status is correctly set based on pass rate."""
        # All pass (100%) -> success
        leads_good = [
            {"personId": str(i), "directPhone": "555", "email": "a@b.com", "contactAccuracyScore": 95}
            for i in range(10)
        ]
        result = export_validation_checklist(leads_good)
        for check in result:
            assert check["status"] == "success"

    def test_warning_threshold(self):
        """Pass rate 70-90% gives warning status."""
        # 8 have phone, 2 don't -> 80% pass rate -> warning
        leads = []
        for i in range(8):
            leads.append({"personId": str(i), "directPhone": "555", "email": "a@b.com", "contactAccuracyScore": 95})
        for i in range(8, 10):
            leads.append({"personId": str(i), "email": "a@b.com", "contactAccuracyScore": 95})

        result = export_validation_checklist(leads)
        phone_check = next(c for c in result if c["check"] == "Has phone number")
        assert phone_check["status"] == "warning"

    def test_error_threshold(self):
        """Pass rate below 70% gives error status."""
        # 3 have phone, 7 don't -> 30% pass rate -> error
        leads = []
        for i in range(3):
            leads.append({"personId": str(i), "directPhone": "555", "email": "a@b.com", "contactAccuracyScore": 95})
        for i in range(3, 10):
            leads.append({"personId": str(i), "email": "a@b.com", "contactAccuracyScore": 95})

        result = export_validation_checklist(leads)
        phone_check = next(c for c in result if c["check"] == "Has phone number")
        assert phone_check["status"] == "error"


class TestNarrativeMetric:
    """Tests for narrative_metric component."""

    def test_renders_with_highlight(self):
        """narrative_metric calls st.markdown with highlighted value."""
        mock_st.reset_mock()
        narrative_metric("{value} leads exported", highlight_value="312")
        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args[0][0]
        assert "312" in html
        assert "leads exported" in html

    def test_renders_with_subtext(self):
        """narrative_metric includes subtext when provided."""
        mock_st.reset_mock()
        narrative_metric("{value} credits used", highlight_value="500", subtext="Budget at 80%")
        html = mock_st.markdown.call_args[0][0]
        assert "Budget at 80%" in html

    def test_renders_without_highlight(self):
        """narrative_metric works without highlight_value."""
        mock_st.reset_mock()
        narrative_metric("No leads yet")
        html = mock_st.markdown.call_args[0][0]
        assert "No leads yet" in html

    def test_renders_without_subtext(self):
        """narrative_metric works without subtext."""
        mock_st.reset_mock()
        narrative_metric("{value} queries", highlight_value="10")
        html = mock_st.markdown.call_args[0][0]
        assert "10" in html
        # Should not contain subtext paragraph
        assert html.count("<p") == 1  # Only the main text paragraph


class TestXSSEscaping:
    """Test that API-sourced data is HTML-escaped in UI components."""

    def test_company_card_header_escapes_company_name(self):
        """Company name with HTML tags should be escaped."""
        html = company_card_header(
            company_name='<script>alert("xss")</script>',
            contact_count=1,
            best_contact_name="Safe Name",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_company_card_header_escapes_contact_name(self):
        """Contact name with HTML should be escaped."""
        html = company_card_header(
            company_name="Safe Co",
            contact_count=1,
            best_contact_name='<img src=x onerror="alert(1)">',
        )
        assert 'onerror="alert(1)"' not in html
        assert "&lt;img" in html

    def test_score_breakdown_escapes_management_level(self):
        """Management level from API should be HTML-escaped."""
        contact = {
            "contactAccuracyScore": 95,
            "managementLevel": '<b onmouseover="alert(1)">Manager</b>',
        }
        html = score_breakdown(contact)
        assert 'onmouseover="alert(1)"' not in html
        assert "&lt;b" in html
