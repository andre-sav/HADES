"""Tests for export.py - VanillaSoft CSV generation."""

import csv
import io
import sys
from unittest.mock import MagicMock

# Mock Streamlit before importing modules that use it
sys.modules["streamlit"] = MagicMock()
sys.modules["libsql_experimental"] = MagicMock()

from export import build_vanillasoft_row, export_leads_to_csv, get_export_summary
from utils import VANILLASOFT_COLUMNS


class TestBuildVanillasoftRow:
    """Tests for build_vanillasoft_row function."""

    def test_basic_lead_mapping(self):
        """Test that ZoomInfo fields map to VanillaSoft columns."""
        lead = {
            "companyName": "Acme Corp",
            "phone": "5551234567",
            "city": "Dallas",
            "state": "TX",
            "zip": "75201",
            "employees": 150,
            "sicCode": "5812",
        }
        row = build_vanillasoft_row(lead)

        assert row["Company"] == "Acme Corp"
        assert row["City"] == "Dallas"
        assert row["State"] == "TX"
        assert row["ZIP code"] == "75201"
        assert row["Number of Employees"] == "150"
        assert row["Primary SIC"] == "5812"

    def test_phone_formatting(self):
        """Test that phone numbers are formatted correctly."""
        lead = {"phone": "5551234567"}
        row = build_vanillasoft_row(lead)
        assert row["Business"] == "(555) 123-4567"

    def test_list_source_attribution(self):
        """Test that List Source follows VSDP format: '{DataSource} {Date}'."""
        from datetime import datetime

        lead = {"companyName": "Test Co"}
        row = build_vanillasoft_row(lead)

        # List Source should be "ZoomInfo {date}" format
        today = datetime.now().strftime("%b %d %Y")
        assert row["List Source"] == f"ZoomInfo {today}"

    def test_list_source_custom_data_source(self):
        """Test that custom data source is used in List Source."""
        from datetime import datetime

        lead = {"companyName": "Test Co"}
        row = build_vanillasoft_row(lead, data_source="SalesGenie")

        today = datetime.now().strftime("%b %d %Y")
        assert row["List Source"] == f"SalesGenie {today}"

    def test_lead_source_empty_by_default(self):
        """Test that Lead Source is empty (List Source has attribution)."""
        lead = {"companyName": "Test Co"}
        row = build_vanillasoft_row(lead)
        assert row["Lead Source"] == ""

    def test_priority_as_call_priority(self):
        """Test that priority maps to Call Priority."""
        lead = {"companyName": "Test Co", "_priority": "High"}
        row = build_vanillasoft_row(lead)
        assert row["Call Priority"] == "High"

    def test_import_notes_with_score(self):
        """Test import notes includes score info."""
        lead = {
            "companyName": "Test Co",
            "_score": 85,
            "_age_days": 5,
            "_freshness_label": "Hot",
        }
        row = build_vanillasoft_row(lead)
        assert "Score: 85" in row["Import Notes"]
        assert "Age: 5d" in row["Import Notes"]
        assert "Freshness: Hot" in row["Import Notes"]

    def test_import_notes_with_distance(self):
        """Test import notes includes distance for geography leads."""
        lead = {
            "companyName": "Test Co",
            "_score": 75,
            "_distance_miles": 12.5,
        }
        row = build_vanillasoft_row(lead)
        assert "Distance: 12.5mi" in row["Import Notes"]

    def test_operator_metadata(self):
        """Test that operator metadata is added to row."""
        lead = {"companyName": "Test Co"}
        operator = {
            "operator_name": "John Smith",
            "vending_business_name": "ABC Vending",
            "operator_phone": "5559876543",
            "operator_email": "john@abc.com",
            "operator_zip": "75202",
            "operator_website": "https://abc.com",
            "team": "North Texas",
        }

        row = build_vanillasoft_row(lead, operator)

        assert row["Operator Name"] == "John Smith"
        assert row["Vending Business Name"] == "ABC Vending"
        assert row["Operator Phone #"] == "(555) 987-6543"
        assert row["Operator Email Address"] == "john@abc.com"
        assert row["Operator Zip Code"] == "75202"
        assert row["Operator Website Address"] == "https://abc.com"
        assert row["Team"] == "North Texas"
        assert row["Contact Owner"] == "John Smith"

    def test_all_columns_present(self):
        """Test that all VanillaSoft columns are in output."""
        lead = {"companyName": "Test"}
        row = build_vanillasoft_row(lead)

        for col in VANILLASOFT_COLUMNS:
            assert col in row, f"Missing column: {col}"

    def test_none_values_handled(self):
        """Test that None values don't cause errors."""
        lead = {
            "companyName": "Test",
            "phone": None,
            "employees": None,
        }
        row = build_vanillasoft_row(lead)
        assert row["Company"] == "Test"
        assert row["Business"] == ""

    def test_operator_with_none_fields(self):
        """Test operator with None fields."""
        lead = {"companyName": "Test"}
        operator = {
            "operator_name": "Jane Doe",
            "vending_business_name": None,
            "operator_phone": None,
            "operator_email": None,
            "operator_zip": None,
            "operator_website": None,
            "team": None,
        }
        row = build_vanillasoft_row(lead, operator)
        assert row["Operator Name"] == "Jane Doe"
        assert row["Vending Business Name"] == ""


class TestExportLeadsToCsv:
    """Tests for export_leads_to_csv function."""

    def test_csv_has_all_columns(self):
        """Test that CSV has all VanillaSoft columns."""
        leads = [{"companyName": "Test Corp"}]
        csv_content, filename = export_leads_to_csv(leads)

        reader = csv.DictReader(io.StringIO(csv_content))
        headers = reader.fieldnames

        assert headers == VANILLASOFT_COLUMNS

    def test_csv_content_correct(self):
        """Test that CSV content is correct."""
        leads = [
            {"companyName": "Acme Corp", "city": "Dallas"},
            {"companyName": "Beta Inc", "city": "Houston"},
        ]
        csv_content, filename = export_leads_to_csv(leads)

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert len(rows) == 2
        assert rows[0]["Company"] == "Acme Corp"
        assert rows[0]["City"] == "Dallas"
        assert rows[1]["Company"] == "Beta Inc"

    def test_filename_format(self):
        """Test that filename includes workflow type and timestamp."""
        leads = [{"companyName": "Test"}]

        _, filename = export_leads_to_csv(leads, workflow_type="intent")
        assert filename.startswith("intent_leads_")
        assert filename.endswith(".csv")

        _, filename = export_leads_to_csv(leads, workflow_type="geography")
        assert filename.startswith("geography_leads_")

    def test_operator_added_to_all_rows(self):
        """Test that operator is added to all rows."""
        leads = [
            {"companyName": "Company A"},
            {"companyName": "Company B"},
        ]
        operator = {
            "operator_name": "Test Op",
            "vending_business_name": "Test Vending",
            "operator_phone": None,
            "operator_email": None,
            "operator_zip": None,
            "operator_website": None,
            "team": None,
        }

        csv_content, _ = export_leads_to_csv(leads, operator=operator)
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        for row in rows:
            assert row["Operator Name"] == "Test Op"

    def test_empty_leads_list(self):
        """Test export with empty leads list."""
        csv_content, filename = export_leads_to_csv([])

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert len(rows) == 0
        assert reader.fieldnames == VANILLASOFT_COLUMNS

    def test_list_source_in_csv(self):
        """Test that List Source is correctly set in CSV output."""
        from datetime import datetime

        leads = [{"companyName": "Test Corp"}]
        csv_content, _ = export_leads_to_csv(leads, data_source="ZoomInfo")

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        today = datetime.now().strftime("%b %d %Y")
        assert rows[0]["List Source"] == f"ZoomInfo {today}"


class TestGetExportSummary:
    """Tests for get_export_summary function."""

    def test_empty_leads(self):
        """Test summary for empty leads list."""
        summary = get_export_summary([])
        assert summary["total"] == 0
        assert summary["by_priority"] == {}
        assert summary["by_state"] == {}

    def test_total_count(self):
        """Test that total count is correct."""
        leads = [
            {"companyName": "A"},
            {"companyName": "B"},
            {"companyName": "C"},
        ]
        summary = get_export_summary(leads)
        assert summary["total"] == 3

    def test_priority_breakdown(self):
        """Test priority breakdown."""
        leads = [
            {"_priority": "High"},
            {"_priority": "High"},
            {"_priority": "Medium"},
            {"_priority": "Low"},
        ]
        summary = get_export_summary(leads)

        assert summary["by_priority"]["High"] == 2
        assert summary["by_priority"]["Medium"] == 1
        assert summary["by_priority"]["Low"] == 1

    def test_state_breakdown(self):
        """Test state breakdown (top 5)."""
        leads = [
            {"state": "TX"},
            {"state": "TX"},
            {"state": "TX"},
            {"state": "CA"},
            {"state": "CA"},
            {"state": "FL"},
        ]
        summary = get_export_summary(leads)

        assert summary["by_state"]["TX"] == 3
        assert summary["by_state"]["CA"] == 2
        assert summary["by_state"]["FL"] == 1

    def test_missing_priority(self):
        """Test handling of missing priority."""
        leads = [
            {"companyName": "A"},
            {"companyName": "B", "_priority": "High"},
        ]
        summary = get_export_summary(leads)

        assert summary["by_priority"].get("Unknown", 0) == 1
        assert summary["by_priority"].get("High", 0) == 1

    def test_state_limit_to_top_5(self):
        """Test that state breakdown is limited to top 5."""
        leads = [
            {"state": "TX"}, {"state": "TX"}, {"state": "TX"},
            {"state": "CA"}, {"state": "CA"},
            {"state": "FL"},
            {"state": "NY"},
            {"state": "WA"},
            {"state": "OR"},
            {"state": "AZ"},
        ]
        summary = get_export_summary(leads)

        # Should only have top 5 states
        assert len(summary["by_state"]) <= 5
