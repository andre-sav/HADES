"""
Tests for Turso database module.

Run with: pytest tests/test_turso_db.py -v
"""

import json
import sys
import pytest
from unittest.mock import MagicMock, patch

# Mock external dependencies before importing turso_db
sys.modules["libsql_experimental"] = MagicMock()
sys.modules["streamlit"] = MagicMock()

from turso_db import TursoDatabase


class TestTursoDatabase:
    """Tests for TursoDatabase class."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database instance."""
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn
        return db, mock_conn

    def test_init(self, mock_db):
        """Test database initialization."""
        db, _ = mock_db
        assert db.url == "libsql://test.turso.io"
        assert db.auth_token == "test-token"

    def test_execute(self, mock_db):
        """Test query execution."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "test")]
        mock_conn.execute.return_value = mock_cursor

        result = db.execute("SELECT * FROM test")

        mock_conn.execute.assert_called_once_with("SELECT * FROM test", ())
        assert result == [(1, "test")]

    def test_execute_write(self, mock_db):
        """Test write execution."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 42
        mock_conn.execute.return_value = mock_cursor

        result = db.execute_write("INSERT INTO test VALUES (?)", ("value",))

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
        assert result == 42

    def test_get_operators_empty(self, mock_db):
        """Test getting operators when none exist."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        result = db.get_operators()

        assert result == []

    def test_get_operators(self, mock_db):
        """Test getting operators."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        # Columns: id, operator_name, vending_business_name, operator_phone,
        #          operator_email, operator_zip, operator_website, team,
        #          zoho_id, synced_at, created_at
        mock_cursor.fetchall.return_value = [
            (1, "Test Op", "Test Business", "555-1234", "test@example.com",
             "12345", "test.com", "Team A", "zoho123", "2024-01-01T00:00:00", "2024-01-01")
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_operators()

        assert len(result) == 1
        assert result[0]["operator_name"] == "Test Op"
        assert result[0]["vending_business_name"] == "Test Business"
        assert result[0]["zoho_id"] == "zoho123"
        assert result[0]["synced_at"] == "2024-01-01T00:00:00"

    def test_create_operator(self, mock_db):
        """Test creating an operator."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 1
        mock_conn.execute.return_value = mock_cursor

        result = db.create_operator(
            operator_name="New Op",
            vending_business_name="New Business",
            operator_phone="555-9999",
            operator_email="new@example.com",
            operator_zip="54321",
            operator_website="new.com",
            team="Team B",
        )

        assert result == 1
        mock_conn.commit.assert_called_once()

    def test_cache_results(self, mock_db):
        """Test caching query results."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 1
        mock_conn.execute.return_value = mock_cursor

        leads = [{"company": "Test Co", "phone": "555-1111"}]
        db.cache_results(
            cache_id="test-hash",
            workflow_type="intent",
            query_params={"topic": "Vending"},
            leads=leads,
        )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "INSERT OR REPLACE INTO zoominfo_cache" in call_args[0]
        assert call_args[1][0] == "test-hash"
        assert call_args[1][1] == "intent"

    def test_get_cached_results_hit(self, mock_db):
        """Test cache hit."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        leads = [{"company": "Cached Co"}]
        mock_cursor.fetchall.return_value = [(json.dumps(leads),)]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_cached_results("test-hash")

        assert result == leads

    def test_get_cached_results_miss(self, mock_db):
        """Test cache miss."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        result = db.get_cached_results("nonexistent")

        assert result is None

    def test_log_credit_usage(self, mock_db):
        """Test logging credit usage."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor

        db.log_credit_usage(
            workflow_type="intent",
            query_params={"topic": "Vending"},
            credits_used=50,
            leads_returned=50,
        )

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_get_weekly_usage(self, mock_db):
        """Test getting weekly credit usage."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(150,)]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_weekly_usage("intent")

        assert result == 150

    def test_save_location_template(self, mock_db):
        """Test saving location template."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 1
        mock_conn.execute.return_value = mock_cursor

        result = db.save_location_template(
            name="Dallas Metro",
            zip_codes=["75201", "75202"],
            radius_miles=25,
        )

        assert result == 1

    def test_get_location_templates(self, mock_db):
        """Test getting location templates."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "Dallas Metro", '["75201", "75202"]', 25)
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_location_templates()

        assert len(result) == 1
        assert result[0]["name"] == "Dallas Metro"
        assert result[0]["zip_codes"] == ["75201", "75202"]
        assert result[0]["radius_miles"] == 25

    def test_get_last_query_found(self, mock_db):
        """Test getting last query when one exists."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (42, "intent", '{"topics": ["Vending"]}', 25, 0, "2026-02-10T14:30:00")
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_last_query("intent")

        assert result is not None
        assert result["id"] == 42
        assert result["workflow_type"] == "intent"
        assert result["leads_returned"] == 25
        assert result["leads_exported"] == 0
        assert result["created_at"] == "2026-02-10T14:30:00"
        assert result["query_params"] == {"topics": ["Vending"]}

        # Verify correct SQL was called
        call_args = mock_conn.execute.call_args[0]
        assert "WHERE workflow_type = ?" in call_args[0]
        assert "ORDER BY created_at DESC LIMIT 1" in call_args[0]
        assert call_args[1] == ("intent",)

    def test_get_last_query_not_found(self, mock_db):
        """Test getting last query when none exist."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        result = db.get_last_query("geography")

        assert result is None

    def test_get_last_query_null_params(self, mock_db):
        """Test getting last query when query_params is NULL."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "geography", None, 10, 5, "2026-02-10T12:00:00")
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_last_query("geography")

        assert result is not None
        assert result["query_params"] == {}

    def test_update_query_exported(self, mock_db):
        """Test updating exported count for a query."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor

        db.update_query_exported(42, 25)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "UPDATE query_history SET leads_exported = ? WHERE id = ?" in call_args[0]
        assert call_args[1] == (25, 42)
        mock_conn.commit.assert_called_once()

    def test_update_query_exported_zero(self, mock_db):
        """Test updating exported count to zero."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor

        db.update_query_exported(1, 0)

        call_args = mock_conn.execute.call_args[0]
        assert call_args[1] == (0, 1)


class TestLeadOutcomes:
    """Tests for lead outcome CRUD methods."""

    @pytest.fixture
    def mock_db(self):
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn
        return db, mock_conn

    def test_record_lead_outcomes_batch(self, mock_db):
        """Test batch inserting lead outcomes (13-element tuples with person_id)."""
        db, mock_conn = mock_db

        params = [
            ("HADES-20260212-001", "Acme Corp", "123", "person-001", "7011", 150,
             12.5, "75201", "TX", 85, "geography", "2026-02-12T10:00:00", '{"_score": 85}'),
            ("HADES-20260212-001", "Beta Inc", "456", None, "8211", 200,
             5.0, "75202", "TX", 72, "geography", "2026-02-12T10:00:00", None),
        ]
        db.record_lead_outcomes_batch(params)

        # Should have called execute for each param tuple + commit
        assert mock_conn.execute.call_count == 2
        mock_conn.commit.assert_called_once()

        # Verify the INSERT includes person_id column
        insert_sql = mock_conn.execute.call_args_list[0][0][0]
        assert "person_id" in insert_sql
        # Verify 13 placeholders
        assert insert_sql.count("?") == 13

    def test_record_lead_outcomes_with_person_id(self, mock_db):
        """Test that person_id is correctly passed as 4th tuple element."""
        db, mock_conn = mock_db

        params = [
            ("HADES-20260212-001", "Acme Corp", "123", "person-abc-123", "7011", 150,
             12.5, "75201", "TX", 85, "geography", "2026-02-12T10:00:00", None),
        ]
        db.record_lead_outcomes_batch(params)

        # Verify the tuple passed to execute includes person_id
        call_params = mock_conn.execute.call_args_list[0][0][1]
        assert call_params[3] == "person-abc-123"

    def test_get_outcomes_by_batch(self, mock_db):
        """Test retrieving outcomes by batch ID."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (1, "HADES-20260212-001", "Acme Corp", "7011", 150, 85,
             "geography", "2026-02-12", None, None),
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_outcomes_by_batch("HADES-20260212-001")

        assert len(result) == 1
        assert result[0]["company_name"] == "Acme Corp"
        assert result[0]["batch_id"] == "HADES-20260212-001"
        assert result[0]["outcome"] is None

    def test_get_all_outcomes_for_calibration(self, mock_db):
        """Test UNION query for calibration."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("Acme Corp", "7011", 150, "75201", "TX", "delivery", "historical"),
            ("Beta Inc", "8211", 200, "75202", "TX", "no_delivery", "hades"),
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_all_outcomes_for_calibration()

        assert len(result) == 2
        assert result[0]["source"] == "historical"
        assert result[1]["source"] == "hades"

    def test_get_historical_count(self, mock_db):
        """Test counting historical outcomes."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(42,)]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_historical_count()
        assert result == 42

    def test_get_historical_count_empty(self, mock_db):
        """Test counting with no historical data."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(0,)]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_historical_count()
        assert result == 0

    def test_update_lead_outcome(self, mock_db):
        """Test updating a lead outcome."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor

        db.update_lead_outcome(
            batch_id="HADES-20260212-001",
            company_name="Acme Corp",
            outcome="delivery",
            outcome_at="2026-03-01",
        )

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "UPDATE lead_outcomes" in call_args[0]
        assert call_args[1] == ("delivery", "2026-03-01", "HADES-20260212-001", "Acme Corp")

    def test_get_recent_batches(self, mock_db):
        """Test getting recent batch summaries."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("HADES-20260212-001", "geography", "2026-02-12T10:00:00", 25, 3, 5),
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_recent_batches(limit=5)

        assert len(result) == 1
        assert result[0]["batch_id"] == "HADES-20260212-001"
        assert result[0]["lead_count"] == 25
        assert result[0]["deliveries"] == 3
        assert result[0]["outcomes_known"] == 5

    def test_get_exported_company_ids(self, mock_db):
        """Test get_exported_company_ids returns correct structure."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("123", "Acme Corp", "2026-02-01T10:00:00", "geography"),
            ("456", "Beta Inc", "2026-01-15T08:00:00", "intent"),
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_exported_company_ids(days_back=180)

        assert "123" in result
        assert result["123"]["company_name"] == "Acme Corp"
        assert result["123"]["exported_at"] == "2026-02-01T10:00:00"
        assert result["123"]["workflow_type"] == "geography"
        assert "456" in result
        assert result["456"]["company_name"] == "Beta Inc"

        # Verify SQL uses days_back parameter
        call_args = mock_conn.execute.call_args[0]
        assert "date('now', ?)" in call_args[0]
        assert call_args[1] == ("-180 days",)

    def test_get_exported_company_ids_respects_window(self, mock_db):
        """Test that days_back parameter is passed correctly."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        db.get_exported_company_ids(days_back=30)

        call_args = mock_conn.execute.call_args[0]
        assert call_args[1] == ("-30 days",)

    def test_get_exported_company_ids_deduplicates(self, mock_db):
        """Test that duplicate company_ids keep only first (most recent) entry."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        # Same company_id exported twice — query returns newest first (ORDER BY exported_at DESC)
        mock_cursor.fetchall.return_value = [
            ("123", "Acme Corp", "2026-02-01T10:00:00", "geography"),
            ("123", "Acme Corp", "2026-01-01T10:00:00", "intent"),
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_exported_company_ids()

        assert len(result) == 1
        # Should keep the first (most recent) entry
        assert result["123"]["exported_at"] == "2026-02-01T10:00:00"

    def test_get_exported_company_ids_empty(self, mock_db):
        """Test with no exported companies."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        result = db.get_exported_company_ids()

        assert result == {}

    def test_insert_historical_outcomes_batch(self, mock_db):
        """Test batch inserting historical outcomes."""
        db, mock_conn = mock_db

        params = [
            ("Company A", "7011", 100, "75201", "TX", "delivery",
             "enriched_locatings.csv", "2026-01-01", "2026-02-12T10:00:00"),
        ]
        db.insert_historical_outcomes_batch(params)

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
