"""Tests for export.py - VanillaSoft CSV generation."""

import csv
import io
import sys
from unittest.mock import MagicMock

# Mock Streamlit before importing modules that use it
sys.modules["streamlit"] = MagicMock()
sys.modules["libsql_experimental"] = MagicMock()

from export import build_vanillasoft_row, export_leads_to_csv, get_export_summary, generate_batch_id
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

    def test_mobile_phone_formatting(self):
        """Test that mobile phone numbers are formatted correctly."""
        lead = {"mobilePhone": "5559876543"}
        row = build_vanillasoft_row(lead)
        assert row["Mobile"] == "(555) 987-6543"

    def test_direct_phone_preferred_over_generic_phone(self):
        """Test that directPhone wins when both directPhone and phone are present."""
        lead = {"directPhone": "5551111111", "phone": "5552222222"}
        row = build_vanillasoft_row(lead)
        assert row["Business"] == "(555) 111-1111"

    def test_generic_phone_used_as_fallback(self):
        """Test that phone is used when directPhone is absent."""
        lead = {"phone": "5553333333"}
        row = build_vanillasoft_row(lead)
        assert row["Business"] == "(555) 333-3333"

    def test_direct_phone_only(self):
        """Test that directPhone works when phone is absent."""
        lead = {"directPhone": "5554444444"}
        row = build_vanillasoft_row(lead)
        assert row["Business"] == "(555) 444-4444"

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

    def test_lead_source_from_lead_source_tag(self):
        """Test that Lead Source is populated from _lead_source."""
        lead = {"companyName": "Test Co", "_lead_source": "ZoomInfo Intent - Vending - 85 - 2d"}
        row = build_vanillasoft_row(lead)
        assert row["Lead Source"] == "ZoomInfo Intent - Vending - 85 - 2d"

    def test_lead_source_empty_when_no_tag(self):
        """Test that Lead Source is empty when no _lead_source set."""
        lead = {"companyName": "Test Co"}
        row = build_vanillasoft_row(lead)
        assert row["Lead Source"] == ""

    def test_call_priority_from_score(self):
        """Test that Call Priority is derived from _priority."""
        lead = {"companyName": "Test Co", "_priority": "High"}
        row = build_vanillasoft_row(lead)
        assert row["Call Priority"] == "High"

    def test_call_priority_empty_when_no_score(self):
        """Test that Call Priority is empty when no _priority set."""
        lead = {"companyName": "Test Co"}
        row = build_vanillasoft_row(lead)
        assert row["Call Priority"] == ""

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
        # Contact Owner is set by round-robin, not from operator
        assert row["Contact Owner"] == ""

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

    def test_contact_owner_from_parameter(self):
        """Test that Contact Owner is set from contact_owner param, not operator."""
        lead = {"companyName": "Test Co"}
        operator = {"operator_name": "John Smith"}
        row = build_vanillasoft_row(lead, operator, contact_owner="agent@hlmii.com")
        assert row["Contact Owner"] == "agent@hlmii.com"
        assert row["Operator Name"] == "John Smith"

    def test_home_phone_mapping(self):
        """Test that companyHQPhone maps to Home column."""
        lead = {"companyName": "Test Co", "companyHQPhone": "2125551234"}
        row = build_vanillasoft_row(lead)
        assert row["Home"] == "(212) 555-1234"

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
        csv_content, filename, _ = export_leads_to_csv(leads)

        reader = csv.DictReader(io.StringIO(csv_content))
        headers = reader.fieldnames

        assert headers == VANILLASOFT_COLUMNS

    def test_csv_content_correct(self):
        """Test that CSV content is correct."""
        leads = [
            {"companyName": "Acme Corp", "city": "Dallas"},
            {"companyName": "Beta Inc", "city": "Houston"},
        ]
        csv_content, filename, _ = export_leads_to_csv(leads)

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert len(rows) == 2
        assert rows[0]["Company"] == "Acme Corp"
        assert rows[0]["City"] == "Dallas"
        assert rows[1]["Company"] == "Beta Inc"

    def test_filename_format(self):
        """Test that filename includes workflow type and timestamp."""
        leads = [{"companyName": "Test"}]

        _, filename, _batch = export_leads_to_csv(leads, workflow_type="intent")
        assert filename.startswith("HADES-intent-")
        assert filename.endswith(".csv")

        _, filename, _batch = export_leads_to_csv(leads, workflow_type="geography")
        assert filename.startswith("HADES-geography-")

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

        csv_content, _, _batch = export_leads_to_csv(leads, operator=operator)
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        for row in rows:
            assert row["Operator Name"] == "Test Op"

    def test_empty_leads_list(self):
        """Test export with empty leads list."""
        csv_content, filename, _ = export_leads_to_csv([])

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert len(rows) == 0
        assert reader.fieldnames == VANILLASOFT_COLUMNS

    def test_list_source_in_csv(self):
        """Test that List Source is correctly set in CSV output."""
        from datetime import datetime

        leads = [{"companyName": "Test Corp"}]
        csv_content, _, _batch = export_leads_to_csv(leads, data_source="ZoomInfo")

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        today = datetime.now().strftime("%b %d %Y")
        assert rows[0]["List Source"] == f"ZoomInfo {today}"


class TestContactOwnerRoundRobin:
    """Tests for round-robin Contact Owner assignment in export."""

    def test_round_robin_assignment(self):
        """Test that agents are assigned evenly across leads."""
        leads = [
            {"companyName": "A"},
            {"companyName": "B"},
            {"companyName": "C"},
            {"companyName": "D"},
            {"companyName": "E"},
        ]
        agents = ["agent1@hlmii.com", "agent2@hlmii.com"]

        csv_content, _, _ = export_leads_to_csv(leads, agents=agents)
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        assert rows[0]["Contact Owner"] == "agent1@hlmii.com"
        assert rows[1]["Contact Owner"] == "agent2@hlmii.com"
        assert rows[2]["Contact Owner"] == "agent1@hlmii.com"
        assert rows[3]["Contact Owner"] == "agent2@hlmii.com"
        assert rows[4]["Contact Owner"] == "agent1@hlmii.com"

    def test_no_agents_leaves_empty(self):
        """Test that Contact Owner is empty when no agents provided."""
        leads = [{"companyName": "A"}]
        csv_content, _, _ = export_leads_to_csv(leads, agents=None)
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        assert rows[0]["Contact Owner"] == ""

    def test_empty_agents_list_no_crash(self):
        """Test that empty agents list [] doesn't crash with ZeroDivisionError."""
        leads = [{"companyName": "A"}, {"companyName": "B"}]
        csv_content, _, _ = export_leads_to_csv(leads, agents=[])
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        assert rows[0]["Contact Owner"] == ""
        assert rows[1]["Contact Owner"] == ""

    def test_single_agent_all_rows(self):
        """Test that single agent gets all rows."""
        leads = [{"companyName": "A"}, {"companyName": "B"}]
        csv_content, _, _ = export_leads_to_csv(leads, agents=["solo@hlmii.com"])
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        assert all(row["Contact Owner"] == "solo@hlmii.com" for row in rows)


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


class TestGenerateBatchId:
    """Tests for generate_batch_id function."""

    def test_first_batch_of_day(self):
        """Test first batch ID generation for a day."""
        mock_db = MagicMock()
        # Atomic upsert writes first, then reads back the value
        mock_db.execute.return_value = [("1",)]

        batch_id = generate_batch_id(mock_db)

        assert batch_id.startswith("HADES-")
        assert batch_id.endswith("-001")
        mock_db.execute_write.assert_called_once()

    def test_sequential_batch_ids(self):
        """Test that batch IDs increment correctly."""
        mock_db = MagicMock()
        # Atomic upsert already incremented; read returns new value
        mock_db.execute.return_value = [("4",)]

        batch_id = generate_batch_id(mock_db)

        assert batch_id.endswith("-004")

    def test_batch_id_format(self):
        """Test batch ID format: HADES-YYYYMMDD-NNN."""
        import re

        mock_db = MagicMock()
        mock_db.execute.return_value = [("1",)]

        batch_id = generate_batch_id(mock_db)

        assert re.match(r"^HADES-\d{8}-\d{3}$", batch_id)


class TestBatchIdInRow:
    """Tests for batch_id in build_vanillasoft_row."""

    def test_batch_id_in_import_notes(self):
        """Test that batch_id is prepended to Import Notes."""
        lead = {"companyName": "Test Co", "_score": 85}
        row = build_vanillasoft_row(lead, batch_id="HADES-20260212-001")

        assert row["Import Notes"].startswith("Batch: HADES-20260212-001")
        assert "Score: 85" in row["Import Notes"]

    def test_no_batch_id_when_none(self):
        """Test that Import Notes are normal when batch_id is None."""
        lead = {"companyName": "Test Co", "_score": 85}
        row = build_vanillasoft_row(lead, batch_id=None)

        assert not row["Import Notes"].startswith("Batch:")
        assert "Score: 85" in row["Import Notes"]

    def test_batch_id_only_when_no_other_notes(self):
        """Test batch_id alone when no scoring info."""
        lead = {"companyName": "Test Co"}
        row = build_vanillasoft_row(lead, batch_id="HADES-20260212-001")

        assert row["Import Notes"] == "Batch: HADES-20260212-001"


class TestExportWithBatchId:
    """Tests for export_leads_to_csv with batch_id."""

    def test_returns_three_values(self):
        """Test that export returns (csv_content, filename, batch_id)."""
        leads = [{"companyName": "Test"}]
        result = export_leads_to_csv(leads)

        assert len(result) == 3
        csv_content, filename, batch_id = result
        assert batch_id is None  # No db provided

    def test_batch_id_with_db(self):
        """Test that batch_id is generated when db is provided."""
        mock_db = MagicMock()
        mock_db.execute.return_value = [("1",)]

        leads = [{"companyName": "Test"}]
        csv_content, filename, batch_id = export_leads_to_csv(leads, db=mock_db)

        assert batch_id is not None
        assert batch_id.startswith("HADES-")

    def test_batch_id_in_csv_content(self):
        """Test that batch_id appears in CSV Import Notes."""
        mock_db = MagicMock()
        mock_db.execute.return_value = [("1",)]

        leads = [{"companyName": "Test", "_score": 90}]
        csv_content, _, batch_id = export_leads_to_csv(leads, db=mock_db)

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        assert f"Batch: {batch_id}" in rows[0]["Import Notes"]
