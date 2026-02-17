"""Tests for scripts/run_intent_pipeline.py — Automated Intent Pipeline."""

import json
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from unittest.mock import MagicMock, patch, PropertyMock

# Mock Streamlit and libsql before importing modules
sys.modules["streamlit"] = MagicMock()
sys.modules["libsql_experimental"] = MagicMock()

from scripts._credentials import load_credentials
from scripts.run_intent_pipeline import run_pipeline, build_email, _has_smtp_creds


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    base = {
        "topics": ["Vending Machines"],
        "signal_strengths": ["High", "Medium"],
        "target_companies": 3,
        "management_levels": ["Manager", "Director"],
        "accuracy_min": 95,
        "phone_fields": ["mobilePhone", "directPhone", "phone"],
        "dedup_days_back": 180,
    }
    base.update(overrides)
    return base


def _make_creds(**overrides):
    base = {
        "TURSO_DATABASE_URL": "libsql://test.turso.io",
        "TURSO_AUTH_TOKEN": "test-token",
        "ZOOMINFO_CLIENT_ID": "test-id",
        "ZOOMINFO_CLIENT_SECRET": "test-secret",
        "SMTP_USER": "test@gmail.com",
        "SMTP_PASSWORD": "app-pass",
        "EMAIL_RECIPIENTS": "user@example.com",
        "EMAIL_FROM": "HADES <test@gmail.com>",
    }
    base.update(overrides)
    return base


def _make_intent_lead(company_id="c1", company_name="Acme Corp", strength="High",
                      topic="Vending Machines", sic="7011", employees=200):
    return {
        "companyId": company_id,
        "companyName": company_name,
        "companyWebsite": "https://acme.com",
        "intentStrength": strength,
        "intentTopic": topic,
        "intentDate": datetime.now().isoformat(),
        "sicCode": sic,
        "city": "Dallas",
        "state": "TX",
        "employees": employees,
        "signalScore": 80,
        "audienceStrength": "A",
        "category": "Vending",
        "recommendedContacts": [{"id": f"p_{company_id}"}],
    }


def _make_contact(person_id="p1", company_id="c1", company_name="Acme Corp"):
    return {
        "personId": person_id,
        "id": person_id,
        "firstName": "John",
        "lastName": "Doe",
        "email": "john@acme.com",
        "mobilePhone": "5551234567",
        "directPhone": "5559876543",
        "phone": "5559876543",
        "jobTitle": "Facilities Manager",
        "managementLevel": "Manager",
        "contactAccuracyScore": 98,
        "companyId": company_id,
        "companyName": company_name,
        "city": "Dallas",
        "state": "TX",
        "zipCode": "75201",
        "sicCode": "7011",
        "employeeCount": 200,
    }


# ---------------------------------------------------------------------------
# Credential loader tests
# ---------------------------------------------------------------------------

class TestCredentialLoading:
    """Test credential loading priority (env > secrets.toml)."""

    @patch.dict("os.environ", {
        "TURSO_DATABASE_URL": "libsql://env.turso.io",
        "TURSO_AUTH_TOKEN": "env-token",
        "ZOOMINFO_CLIENT_ID": "env-id",
        "ZOOMINFO_CLIENT_SECRET": "env-secret",
    }, clear=False)
    @patch("scripts._credentials.Path.exists", return_value=False)
    def test_env_vars_take_priority(self, _mock_exists):
        creds = load_credentials()
        assert creds["TURSO_DATABASE_URL"] == "libsql://env.turso.io"
        assert creds["ZOOMINFO_CLIENT_ID"] == "env-id"

    @patch.dict("os.environ", {}, clear=True)
    @patch("scripts._credentials.Path.exists", return_value=False)
    def test_missing_required_raises(self, _mock_exists):
        import pytest
        with pytest.raises(ValueError, match="Missing required credential"):
            load_credentials()

    @patch.dict("os.environ", {}, clear=True)
    @patch("scripts._credentials.Path.exists", return_value=False)
    def test_streamlit_secrets_fallback(self, _mock_exists):
        """When running inside Streamlit, should use st.secrets."""
        secrets_data = {
            "TURSO_DATABASE_URL": "libsql://st-secrets.turso.io",
            "TURSO_AUTH_TOKEN": "st-token",
            "ZOOMINFO_CLIENT_ID": "st-id",
            "ZOOMINFO_CLIENT_SECRET": "st-secret",
        }
        # Simulate st.secrets as an object that supports bool and dict()
        mock_secrets = MagicMock()
        mock_secrets.__bool__ = lambda self: True
        mock_secrets.__iter__ = lambda self: iter(secrets_data)
        mock_secrets.__getitem__ = lambda self, k: secrets_data[k]
        mock_secrets.keys = lambda: secrets_data.keys()

        mock_st = MagicMock()
        mock_st.secrets = mock_secrets

        with patch.dict("sys.modules", {"streamlit": mock_st}):
            import importlib
            import scripts._credentials as cred_mod
            importlib.reload(cred_mod)
            creds = cred_mod.load_credentials()
            assert creds["TURSO_DATABASE_URL"] == "libsql://st-secrets.turso.io"

    def test_smtp_keys_optional(self):
        """SMTP keys should be None when not configured, not raise."""
        with patch.dict("os.environ", {
            "TURSO_DATABASE_URL": "libsql://test.turso.io",
            "TURSO_AUTH_TOKEN": "tok",
            "ZOOMINFO_CLIENT_ID": "id",
            "ZOOMINFO_CLIENT_SECRET": "sec",
        }, clear=True):
            with patch("scripts._credentials.Path.exists", return_value=False):
                creds = load_credentials()
                assert creds["SMTP_USER"] is None
                assert creds["SMTP_PASSWORD"] is None
                assert creds["EMAIL_RECIPIENTS"] is None


# ---------------------------------------------------------------------------
# Dry-run test
# ---------------------------------------------------------------------------

class TestDryRun:
    """Dry-run should validate config without making API calls."""

    def test_dry_run_no_api_calls(self):
        config = _make_config()
        creds = _make_creds()
        result = run_pipeline(config, creds, dry_run=True)

        assert result["success"] is True
        assert result["csv_content"] is None
        assert result["batch_id"] is None


# ---------------------------------------------------------------------------
# Full pipeline tests (mocked)
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Full pipeline happy path with all APIs mocked."""

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_happy_path(self, MockClient, MockDB, MockCostTracker):
        config = _make_config(target_companies=2)
        creds = _make_creds()

        # Mock client
        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
            _make_intent_lead("c2", "Beta Inc"),
            _make_intent_lead("c3", "Gamma LLC"),
        ]
        client.search_contacts_all_pages.return_value = [
            _make_contact("p1", "100", "Acme Corp"),
            _make_contact("p2", "200", "Beta Inc"),
        ]
        client.enrich_contacts_batch.side_effect = [
            # First call: resolve company IDs (uncached)
            [{"company": {"id": 100, "name": "Acme Corp"}, "companyId": 100}],
            # Second call: resolve company IDs (uncached)
            [{"company": {"id": 200, "name": "Beta Inc"}, "companyId": 200}],
            # Third call: full enrichment
            [_make_contact("p1", "100", "Acme Corp"),
             _make_contact("p2", "200", "Beta Inc")],
        ]

        # Mock DB
        db = MockDB.return_value
        db.get_company_ids_bulk.return_value = {}  # No cache hits
        db.get_exported_company_ids.return_value = {}  # No previous exports
        db.execute_write = MagicMock()
        db.execute.return_value = [("1",)]  # batch ID sequence

        # Mock cost tracker
        budget = MagicMock()
        budget.alert_level = None
        MockCostTracker.return_value.check_budget.return_value = budget

        result = run_pipeline(config, creds)

        assert result["success"] is True
        assert result["csv_content"] is not None
        assert result["batch_id"] is not None
        assert result["summary"]["contacts_exported"] == 2
        assert len(result["summary"]["top_leads"]) == 2

        # Verify outcomes were recorded
        db.record_lead_outcomes_batch.assert_called_once()
        outcomes = db.record_lead_outcomes_batch.call_args[0][0]
        assert len(outcomes) == 2

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_budget_exceeded_skips_gracefully(self, MockClient, MockDB, MockCostTracker):
        config = _make_config()
        creds = _make_creds()

        budget = MagicMock()
        budget.alert_level = "exceeded"
        budget.alert_message = "Weekly cap reached"
        MockCostTracker.return_value.check_budget.return_value = budget

        result = run_pipeline(config, creds)

        assert result["success"] is True
        assert result["csv_content"] is None
        assert result["summary"].get("budget_exceeded") is True
        # Client should NOT have been called for search
        MockClient.return_value.search_intent_all_pages.assert_not_called()

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_zero_intent_results(self, MockClient, MockDB, MockCostTracker):
        config = _make_config()
        creds = _make_creds()

        budget = MagicMock()
        budget.alert_level = None
        MockCostTracker.return_value.check_budget.return_value = budget

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = []

        db = MockDB.return_value
        db.init_schema = MagicMock()

        result = run_pipeline(config, creds)

        assert result["success"] is True
        assert result["csv_content"] is None
        assert result["summary"]["intent_results"] == 0

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_cross_session_dedup_filters(self, MockClient, MockDB, MockCostTracker):
        """Previously exported companies should be filtered out."""
        config = _make_config(target_companies=5)
        creds = _make_creds()

        budget = MagicMock()
        budget.alert_level = None
        MockCostTracker.return_value.check_budget.return_value = budget

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
            _make_intent_lead("c2", "Beta Inc"),
        ]
        # Return empty contacts (test only cares about dedup filtering)
        client.search_contacts_all_pages.return_value = []
        client.enrich_contacts_batch.return_value = [
            {"company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
        ]

        db = MockDB.return_value
        # c1 was previously exported
        db.get_exported_company_ids.return_value = {
            "c1": {"company_name": "Acme Corp", "exported_at": "2026-02-01", "workflow_type": "intent"},
        }
        db.get_company_ids_bulk.return_value = {"c2": {"numeric_id": 200}}

        result = run_pipeline(config, creds)

        assert result["summary"]["dedup_filtered"] == 1
        assert result["summary"]["companies_selected"] == 1  # Only c2


# ---------------------------------------------------------------------------
# Email tests
# ---------------------------------------------------------------------------

class TestEmailBuilding:
    """Test email MIME construction."""

    def test_email_with_csv_attachment(self):
        result = {
            "success": True,
            "csv_content": "col1,col2\nval1,val2\n",
            "csv_filename": "intent_leads_20260216_0600.csv",
            "batch_id": "HADES-20260216-001",
            "summary": {
                "topics": ["Vending Machines"],
                "signal_strengths": ["High"],
                "intent_results": 50,
                "scored_results": 30,
                "companies_selected": 10,
                "contacts_found": 10,
                "contacts_enriched": 10,
                "contacts_exported": 10,
                "dedup_filtered": 5,
                "credits_used": 10,
                "top_leads": [
                    {"name": "John Doe", "company": "Acme", "title": "FM",
                     "score": 85, "topic": "Vending Machines"},
                ],
            },
        }
        creds = _make_creds()

        msg = build_email(result, creds, "2026-02-16")

        assert msg["Subject"] == "[HADES] Intent Pipeline: 10 leads — 2026-02-16"
        assert msg["To"] == "user@example.com"

        # Should have HTML body + CSV attachment = 2 parts
        parts = list(msg.walk())
        content_types = [p.get_content_type() for p in parts]
        assert "text/html" in content_types
        assert "text/csv" in content_types

    def test_email_no_results(self):
        result = {
            "summary": {
                "topics": ["Vending Machines"],
                "signal_strengths": ["High"],
                "intent_results": 0,
                "contacts_exported": 0,
                "top_leads": [],
            },
            "batch_id": None,
            "csv_content": None,
        }
        creds = _make_creds()

        msg = build_email(result, creds, "2026-02-16")

        assert "No Results" in msg["Subject"]
        # No CSV attachment — only multipart + html
        parts = list(msg.walk())
        content_types = [p.get_content_type() for p in parts]
        assert "text/csv" not in content_types

    def test_email_budget_exceeded(self):
        result = {
            "summary": {
                "topics": ["Vending Machines"],
                "signal_strengths": ["High"],
                "contacts_exported": 0,
                "budget_exceeded": True,
                "top_leads": [],
            },
            "batch_id": None,
            "csv_content": None,
        }
        creds = _make_creds()

        msg = build_email(result, creds, "2026-02-16")

        # Body should mention budget exceeded
        html_part = None
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html_part = part.get_payload(decode=True).decode()
                break
        assert "Budget exceeded" in html_part


class TestHasSmtpCreds:
    def test_all_present(self):
        assert _has_smtp_creds(_make_creds()) is True

    def test_missing_user(self):
        assert _has_smtp_creds(_make_creds(SMTP_USER=None)) is False

    def test_missing_password(self):
        assert _has_smtp_creds(_make_creds(SMTP_PASSWORD=None)) is False

    def test_missing_recipients(self):
        assert _has_smtp_creds(_make_creds(EMAIL_RECIPIENTS=None)) is False


# ---------------------------------------------------------------------------
# Config accessor test
# ---------------------------------------------------------------------------

class TestAutomationConfig:
    def test_get_automation_config_returns_intent(self):
        from utils import get_automation_config
        config = get_automation_config("intent")
        assert config["topics"] == ["Vending Machines", "Breakroom Solutions"]
        assert config["target_companies"] == 25
        assert config["accuracy_min"] == 95

    def test_get_automation_config_missing_type(self):
        from utils import get_automation_config
        config = get_automation_config("nonexistent")
        assert config == {}


# ---------------------------------------------------------------------------
# Pipeline run logging tests
# ---------------------------------------------------------------------------

class TestPipelineRunLogging:
    """Pipeline should log runs to pipeline_runs table."""

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_successful_run_logs_to_db(self, MockClient, MockDB, MockCostTracker):
        config = _make_config(target_companies=1)
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
        ]
        client.search_contacts_all_pages.return_value = [
            _make_contact("p1", "100", "Acme Corp"),
        ]
        client.enrich_contacts_batch.side_effect = [
            [{"company": {"id": 100, "name": "Acme Corp"}, "companyId": 100}],
            [_make_contact("p1", "100", "Acme Corp")],
        ]

        db = MockDB.return_value
        db.get_company_ids_bulk.return_value = {}
        db.get_exported_company_ids.return_value = {}
        db.execute_write = MagicMock()
        db.execute.return_value = [("1",)]
        db.start_pipeline_run.return_value = 42

        result = run_pipeline(config, creds, trigger="manual")

        db.start_pipeline_run.assert_called_once_with("intent", "manual", config)
        db.complete_pipeline_run.assert_called_once()
        call_args = db.complete_pipeline_run.call_args
        assert call_args[0][0] == 42  # run_id
        assert call_args[0][1] == "success"  # status

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_budget_exceeded_logs_skipped(self, MockClient, MockDB, MockCostTracker):
        config = _make_config()
        creds = _make_creds()

        budget = MagicMock()
        budget.alert_level = "exceeded"
        budget.alert_message = "Weekly cap reached"
        MockCostTracker.return_value.check_budget.return_value = budget

        db = MockDB.return_value
        db.start_pipeline_run.return_value = 7

        result = run_pipeline(config, creds, trigger="scheduled")

        db.complete_pipeline_run.assert_called_once()
        call_args = db.complete_pipeline_run.call_args
        assert call_args[0][1] == "skipped"

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_accepts_external_db(self, MockClient, MockDB, MockCostTracker):
        """When db is passed, should use it instead of creating new one."""
        config = _make_config()
        creds = _make_creds()
        external_db = MagicMock()
        external_db.start_pipeline_run.return_value = 1

        budget = MagicMock()
        budget.alert_level = "exceeded"
        budget.alert_message = "cap"
        MockCostTracker.return_value.check_budget.return_value = budget

        result = run_pipeline(config, creds, trigger="manual", db=external_db)

        # Should NOT have created a new TursoDatabase
        MockDB.assert_not_called()
        # Should have used external_db
        external_db.start_pipeline_run.assert_called_once()
