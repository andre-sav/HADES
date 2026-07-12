"""Tests for scripts/run_intent_pipeline.py — Automated Intent Pipeline."""

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

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
    """Dry-run should execute intent search + scoring but skip contacts/export."""

    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_dry_run_no_api_calls(self, MockClient):
        config = _make_config()
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = []

        result = run_pipeline(config, creds, dry_run=True)

        assert result["success"] is True
        assert result["csv_content"] is None
        assert result["batch_id"] is None

    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_dry_run_returns_real_counts(self, MockClient):
        """Dry run should execute intent search + scoring and return real numbers."""
        config = _make_config(target_companies=2)
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
            _make_intent_lead("c2", "Beta Inc"),
            _make_intent_lead("c3", "Gamma LLC"),
        ]

        result = run_pipeline(config, creds, dry_run=True)

        assert result["success"] is True
        assert result["csv_content"] is None
        assert result["batch_id"] is None
        # Real counts from intent search + scoring
        assert result["summary"]["intent_results"] == 3
        assert result["summary"]["scored_results"] > 0
        assert result["summary"]["companies_selected"] <= 2  # capped at target
        # Top companies populated
        assert isinstance(result["summary"]["top_companies"], list)
        assert len(result["summary"]["top_companies"]) > 0
        assert "companyName" in result["summary"]["top_companies"][0]

    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_dry_run_does_not_call_contacts_or_enrich(self, MockClient):
        """Dry run must NOT call contact search, enrich, or export."""
        config = _make_config()
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
        ]

        run_pipeline(config, creds, dry_run=True)

        # Intent search SHOULD be called
        client.search_intent_all_pages.assert_called_once()
        # These should NOT be called
        client.search_contacts_all_pages.assert_not_called()
        client.enrich_contacts_batch.assert_not_called()

    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_dry_run_does_not_log_pipeline_run(self, MockClient):
        """Dry run must NOT create a pipeline run record in the DB."""
        config = _make_config()
        creds = _make_creds()

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
        ]

        # Provide a mock DB to verify it's not called
        mock_db = MagicMock()
        result = run_pipeline(config, creds, dry_run=True, db=mock_db)

        assert result["success"] is True
        mock_db.start_pipeline_run.assert_not_called()
        mock_db.complete_pipeline_run.assert_not_called()


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
            # First call: batch resolve ALL company IDs (was N+1, now single batch)
            [
                {"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
                {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200},
            ],
            # Second call: full enrichment
            [_make_contact("p1", "100", "Acme Corp"),
             _make_contact("p2", "200", "Beta Inc")],
        ]

        # Mock DB
        db = MockDB.return_value
        db.has_running_pipeline.return_value = False
        db.get_company_ids_bulk.return_value = {}  # No cache hits
        db.get_exported_company_ids.return_value = {}  # No previous exports
        db.execute_write = MagicMock()
        db.execute.return_value = [(1,)]  # batch ID sequence

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

        MockDB.return_value.has_running_pipeline.return_value = False

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
        db.has_running_pipeline.return_value = False
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
            {"id": "p_c2", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
        ]

        db = MockDB.return_value
        db.has_running_pipeline.return_value = False
        # c1 was previously exported
        db.get_exported_company_ids.return_value = {
            "c1": {"company_name": "Acme Corp", "exported_at": "2026-02-01", "workflow_type": "intent"},
        }
        db.get_company_ids_bulk.return_value = {"c2": {"numeric_id": 200}}

        result = run_pipeline(config, creds)

        assert result["summary"]["dedup_filtered"] == 1
        assert result["summary"]["companies_selected"] == 1  # Only c2

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_step3_batch_resolves_company_ids(self, MockClient, MockDB, MockCostTracker):
        """Step 3 resolves all uncached company IDs in one batch enrich call."""
        config = _make_config(target_companies=3)
        creds = _make_creds()

        budget = MagicMock()
        budget.alert_level = None
        MockCostTracker.return_value.check_budget.return_value = budget

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
            _make_intent_lead("c2", "Beta Inc"),
            _make_intent_lead("c3", "Gamma LLC"),
        ]
        client.search_contacts_all_pages.return_value = []
        client.enrich_contacts_batch.return_value = [
            {"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
            {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200},
            {"id": "p_c3", "company": {"id": 300, "name": "Gamma LLC"}, "companyId": 300},
        ]

        db = MockDB.return_value
        db.has_running_pipeline.return_value = False
        db.get_company_ids_bulk.return_value = {}  # Nothing cached
        db.get_exported_company_ids.return_value = {}

        run_pipeline(config, creds)

        # Step 3 should make exactly ONE enrich call for ID resolution (not 3)
        first_enrich_call = client.enrich_contacts_batch.call_args_list[0]
        assert first_enrich_call[1]["person_ids"] == ["p_c1", "p_c2", "p_c3"]
        assert first_enrich_call[1]["output_fields"] == ["id", "companyId", "companyName"]


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
        assert config["topics"] == ["Vending Machines", "Breakroom Solutions", "Coffee Services", "Water Coolers"]
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
            [{"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100}],
            [_make_contact("p1", "100", "Acme Corp")],
        ]

        db = MockDB.return_value
        db.has_running_pipeline.return_value = False
        db.get_company_ids_bulk.return_value = {}
        db.get_exported_company_ids.return_value = {}
        db.execute_write = MagicMock()
        db.execute.return_value = [(1,)]
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
        db.has_running_pipeline.return_value = False
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
        external_db.has_running_pipeline.return_value = False
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

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_concurrent_run_guard_aborts(self, MockClient, MockDB, MockCostTracker):
        """Pipeline aborts if another run is already in progress."""
        config = _make_config()
        creds = _make_creds()

        db = MockDB.return_value
        db.has_running_pipeline.return_value = True

        result = run_pipeline(config, creds)

        assert result["success"] is False
        assert result["error"] == "Pipeline already running"
        db.start_pipeline_run.assert_not_called()


class TestHashedNumericIdBridge:
    """R-02/R-15 (HADES-hec/HADES-oq9): the hashed↔numeric companyId split.

    Intent search returns hashed IDs; contact search + lead_outcomes use
    numeric IDs. Scoring and cross-session dedup must bridge the two spaces.
    """

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_contact_scoring_uses_company_intent_score(self, MockClient, MockDB, MockCostTracker):
        """The 60%-weighted company component must come from the intent lead,
        not silently default to 50 because the numeric companyId missed the
        hashed-keyed company_scores dict."""
        from scoring import score_intent_leads

        config = _make_config(target_companies=1)
        creds = _make_creds()

        intent_lead = _make_intent_lead("c1", "Acme Corp", strength="High")
        expected_company_score = score_intent_leads([intent_lead])[0]["_score"]
        assert expected_company_score != 50  # oracle must be distinguishable

        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [_make_intent_lead("c1", "Acme Corp", strength="High")]
        client.search_contacts_all_pages.return_value = [_make_contact("p1", "100", "Acme Corp")]
        client.enrich_contacts_batch.side_effect = [
            [{"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100}],
            [_make_contact("p1", "100", "Acme Corp")],
        ]

        db = MockDB.return_value
        db.has_running_pipeline.return_value = False
        db.get_company_ids_bulk.return_value = {}
        db.get_exported_company_ids.return_value = {}
        db.execute.return_value = [(1,)]

        budget = MagicMock()
        budget.alert_level = None
        MockCostTracker.return_value.check_budget.return_value = budget

        result = run_pipeline(config, creds)
        assert result["success"] is True

        # The lead dict handed to build_outcome_row is the scored contact —
        # its _company_intent_score must be the intent lead's score, not the
        # default-50 that a hashed-key miss produces.
        lead_arg = db.build_outcome_row.call_args_list[0][0][0]
        assert lead_arg["_company_intent_score"] == expected_company_score

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_cross_session_dedup_matches_numeric_history(self, MockClient, MockDB, MockCostTracker):
        """A company exported last month (numeric id in lead_outcomes) must be
        filtered even though the incoming intent lead carries a hashed id and
        the stored company name differs (name fallback cannot rescue)."""
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
        client.search_contacts_all_pages.return_value = []
        client.enrich_contacts_batch.return_value = []

        db = MockDB.return_value
        db.has_running_pipeline.return_value = False
        # History stores the NUMERIC id, under a name that does not normalize
        # to the incoming "Acme Corp" — only the id bridge can match.
        db.get_exported_company_ids.return_value = {
            "100": {"company_name": "Acme Holdings International Group",
                    "exported_at": "2026-06-01", "workflow_type": "intent"},
        }
        # The persistent mapping cache knows c1 → 100 (resolution ran when it
        # was first exported). c2 has never been seen.
        db.get_company_ids_bulk.return_value = {"c1": {"numeric_id": 100, "company_name": "Acme Corp"}}

        result = run_pipeline(config, creds)

        assert result["summary"]["dedup_filtered"] == 1
        assert result["summary"]["companies_selected"] == 1  # only c2


class TestFailLoudAutomation:
    """R-06/R-13 (HADES-wr2/HADES-guz): the headless pipeline must fail loud.

    Blank-lead guard (C1), resolution-failure honesty, budget-skip alerting,
    email-delivery flags.
    """

    def _standard_mocks(self, MockClient, MockDB, MockCostTracker, target=2):
        config = _make_config(target_companies=target)
        creds = _make_creds()
        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
            _make_intent_lead("c2", "Beta Inc"),
        ]
        client.search_contacts_all_pages.return_value = [
            _make_contact("p1", "100", "Acme Corp"),
            _make_contact("p2", "200", "Beta Inc"),
        ]
        db = MockDB.return_value
        db.has_running_pipeline.return_value = False
        db.get_company_ids_bulk.return_value = {}
        db.get_exported_company_ids.return_value = {}
        db.execute.return_value = [(1,)]
        budget = MagicMock()
        budget.alert_level = None
        MockCostTracker.return_value.check_budget.return_value = budget
        return config, creds, client, db

    @patch("scripts.run_intent_pipeline.send_alert")
    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_fieldless_enriched_contacts_dropped(self, MockClient, MockDB, MockCostTracker, mock_alert):
        """A merged-but-still-fieldless record must not be scored/exported."""
        config, creds, client, db = self._standard_mocks(MockClient, MockDB, MockCostTracker)
        client.enrich_contacts_batch.side_effect = [
            [
                {"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
                {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200},
            ],
            # one real contact + one fieldless record whose id matches no
            # search-phase contact (so the C2 merge cannot backfill it)
            [_make_contact("p1", "100", "Acme Corp"),
             {"id": "p_stranger", "personId": "p_stranger"}],
        ]
        result = run_pipeline(config, creds)
        assert result["success"] is True
        assert result["summary"]["contacts_exported"] == 1
        assert result["summary"]["fieldless_dropped"] == 1

    @patch("scripts.run_intent_pipeline.send_alert")
    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_all_fieldless_enrichment_fails_run(self, MockClient, MockDB, MockCostTracker, mock_alert):
        """The 2026-06-15 shape: every enriched record fieldless → error run + alert, no export."""
        config, creds, client, db = self._standard_mocks(MockClient, MockDB, MockCostTracker)
        client.enrich_contacts_batch.side_effect = [
            [
                {"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
                {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200},
            ],
            [{"id": "p_ghost1"}, {"id": "p_ghost2"}],
        ]
        result = run_pipeline(config, creds)
        assert result["success"] is False
        # run completed with error status
        status_arg = db.complete_pipeline_run.call_args[0][1]
        assert status_arg == "error"
        # nothing exported, nothing recorded
        db.record_lead_outcomes_batch.assert_not_called()
        # operator alerted
        assert mock_alert.called

    @patch("scripts.run_intent_pipeline.send_alert")
    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_resolution_failure_is_error_run(self, MockClient, MockDB, MockCostTracker, mock_alert):
        """Company-ID resolution API failure must not report 'success'."""
        config, creds, client, db = self._standard_mocks(MockClient, MockDB, MockCostTracker)
        client.enrich_contacts_batch.side_effect = Exception("429 rate limited")
        result = run_pipeline(config, creds)
        assert result["success"] is False
        status_arg = db.complete_pipeline_run.call_args[0][1]
        assert status_arg == "error"

    @patch("scripts.run_intent_pipeline.send_alert")
    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_budget_exceeded_sends_alert(self, MockClient, MockDB, MockCostTracker, mock_alert):
        """The silent green budget-skip must at least attempt an alert."""
        config = _make_config()
        creds = _make_creds()
        MockDB.return_value.has_running_pipeline.return_value = False
        budget = MagicMock()
        budget.alert_level = "exceeded"
        budget.alert_message = "Weekly cap reached"
        MockCostTracker.return_value.check_budget.return_value = budget
        result = run_pipeline(config, creds)
        assert result["summary"].get("budget_exceeded") is True
        assert mock_alert.called

    @patch("scripts.run_intent_pipeline.send_email")
    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_email_failure_sets_flag(self, MockClient, MockDB, MockCostTracker, mock_send):
        """Email delivery failure must be visible in the summary (drives a red run)."""
        config, creds, client, db = self._standard_mocks(MockClient, MockDB, MockCostTracker)
        creds = _make_creds(SMTP_USER="u", SMTP_PASSWORD="p", EMAIL_RECIPIENTS="a@b.c")
        client.enrich_contacts_batch.side_effect = [
            [{"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
             {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200}],
            [_make_contact("p1", "100", "Acme Corp"),
             _make_contact("p2", "200", "Beta Inc")],
        ]
        mock_send.side_effect = Exception("SMTP down")
        result = run_pipeline(config, creds)
        assert result["success"] is True  # leads ARE staged
        assert result["summary"].get("email_failed") is True

    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_email_skipped_no_smtp_sets_flag(self, MockClient, MockDB, MockCostTracker):
        """SMTP unconfigured on an email-flagged run must be visible in the summary."""
        config, creds, client, db = self._standard_mocks(MockClient, MockDB, MockCostTracker)
        client.enrich_contacts_batch.side_effect = [
            [{"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
             {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200}],
            [_make_contact("p1", "100", "Acme Corp"),
             _make_contact("p2", "200", "Beta Inc")],
        ]
        creds = _make_creds(SMTP_USER=None, SMTP_PASSWORD=None, EMAIL_RECIPIENTS=None)
        result = run_pipeline(config, creds)
        assert result["success"] is True
        assert result["summary"].get("email_skipped_no_smtp") is True


class TestResolutionCreditAccounting:
    """R-21 (HADES-n7u): ID-resolution enriches spend credits that were never
    logged — the Usage Dashboard and weekly budget gate were blind to them."""

    @patch("scripts.run_intent_pipeline.send_alert")
    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_resolution_enriches_logged(self, MockClient, MockDB, MockCostTracker, _alert):
        config = _make_config(target_companies=2)
        creds = _make_creds()
        client = MockClient.return_value
        client.search_intent_all_pages.return_value = [
            _make_intent_lead("c1", "Acme Corp"),
            _make_intent_lead("c2", "Beta Inc"),
        ]
        client.search_contacts_all_pages.return_value = [
            _make_contact("p1", "100", "Acme Corp")]
        client.enrich_contacts_batch.side_effect = [
            [{"id": "p_c1", "company": {"id": 100, "name": "Acme Corp"}, "companyId": 100},
             {"id": "p_c2", "company": {"id": 200, "name": "Beta Inc"}, "companyId": 200}],
            [_make_contact("p1", "100", "Acme Corp")],
        ]
        db = MockDB.return_value
        db.has_running_pipeline.return_value = False
        db.get_company_ids_bulk.return_value = {}
        db.get_exported_company_ids.return_value = {}
        db.execute.return_value = [(1,)]
        tracker = MockCostTracker.return_value
        budget = MagicMock()
        budget.alert_level = None
        tracker.check_budget.return_value = budget

        result = run_pipeline(config, creds)
        assert result["success"] is True

        # One log_usage call must be the resolution spend (2 credits)
        resolution_logs = [
            c for c in tracker.log_usage.call_args_list
            if c.kwargs.get("query_params", {}).get("source") == "id_resolution"
        ]
        assert len(resolution_logs) == 1
        assert resolution_logs[0].kwargs["credits_used"] == 2

    @patch("scripts.run_intent_pipeline.send_alert")
    @patch("scripts.run_intent_pipeline.CostTracker")
    @patch("scripts.run_intent_pipeline.TursoDatabase")
    @patch("scripts.run_intent_pipeline.ZoomInfoClient")
    def test_budget_estimate_covers_worst_case(self, MockClient, MockDB, MockCostTracker, _alert):
        """Estimate was target (25) while worst case is resolution+enrich (2x)."""
        config = _make_config(target_companies=25)
        creds = _make_creds()
        MockDB.return_value.has_running_pipeline.return_value = False
        tracker = MockCostTracker.return_value
        budget = MagicMock()
        budget.alert_level = "exceeded"
        budget.alert_message = "cap"
        tracker.check_budget.return_value = budget
        run_pipeline(config, creds)
        estimate = tracker.check_budget.call_args[0][1]
        assert estimate == 50  # 2 x target: resolution + full enrich
