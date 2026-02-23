"""
Tests for Turso database module.

Run with: pytest tests/test_turso_db.py -v
"""

import json
import sys
import pytest
from unittest.mock import MagicMock

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

    def test_search_operators_no_query(self, mock_db):
        """Test search_operators returns paginated results without query."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        # First call: COUNT(*), second call: SELECT with LIMIT/OFFSET
        mock_cursor.fetchall.side_effect = [
            [(50,)],  # total count
            [(1, "Alpha Op", "Biz A", "555-0001", "a@a.com", "10001", "a.com", "Team 1", None, None, "2024-01-01")],
        ]
        mock_conn.execute.return_value = mock_cursor

        operators, total = db.search_operators(query="", limit=20, offset=0)

        assert total == 50
        assert len(operators) == 1
        assert operators[0]["operator_name"] == "Alpha Op"

    def test_search_operators_with_query(self, mock_db):
        """Test search_operators filters by query with LIKE."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [(3,)],  # filtered count
            [(2, "Bob Smith", "Smith Vending", "555-0002", "bob@smith.com", "75201", "smith.com", "TX", None, None, "2024-01-01")],
        ]
        mock_conn.execute.return_value = mock_cursor

        operators, total = db.search_operators(query="Smith", limit=20, offset=0)

        assert total == 3
        assert len(operators) == 1
        assert operators[0]["operator_name"] == "Bob Smith"
        # Verify LIKE param was passed
        calls = mock_conn.execute.call_args_list
        assert any("%Smith%" in str(c) for c in calls)

    def test_search_operators_offset(self, mock_db):
        """Test search_operators respects offset for pagination."""
        db, mock_conn = mock_db
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [(100,)],
            [],  # page 6 empty
        ]
        mock_conn.execute.return_value = mock_cursor

        operators, total = db.search_operators(query="", limit=20, offset=100)

        assert total == 100
        assert len(operators) == 0

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


class TestQueriesByDateRange:
    """Tests for date range query filtering."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database instance."""
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn
        return db, mock_conn

    def _set_cursor_rows(self, mock_conn, rows):
        """Helper to set mock cursor fetchall return value."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_conn.execute.return_value = mock_cursor

    def test_date_range_no_workflow_filter(self, mock_db):
        """Test querying by date range without workflow filter."""
        db, mock_conn = mock_db
        self._set_cursor_rows(mock_conn, [
            (1, "intent", '{"topics": ["Vending"]}', 10, 5, "2026-02-15T10:00:00"),
        ])

        result = db.get_queries_by_date_range("2026-02-10", "2026-02-17")

        assert len(result) == 1
        assert result[0]["workflow_type"] == "intent"
        assert result[0]["leads_returned"] == 10
        call_sql = mock_conn.execute.call_args[0][0]
        assert "created_at >= ?" in call_sql
        assert "workflow_type = ?" not in call_sql

    def test_date_range_with_workflow_filter(self, mock_db):
        """Test querying by date range with workflow filter."""
        db, mock_conn = mock_db
        self._set_cursor_rows(mock_conn, [])

        db.get_queries_by_date_range("2026-02-10", "2026-02-17", workflow_type="intent")

        call_sql = mock_conn.execute.call_args[0][0]
        assert "workflow_type = ?" in call_sql
        assert mock_conn.execute.call_args[0][1] == ("2026-02-10", "2026-02-17", "intent")

    def test_date_range_empty_results(self, mock_db):
        """Test empty results for date range."""
        db, mock_conn = mock_db
        self._set_cursor_rows(mock_conn, [])

        result = db.get_queries_by_date_range("2026-01-01", "2026-01-07")

        assert result == []

    def test_date_range_parses_json_params(self, mock_db):
        """Test that query_params JSON is parsed."""
        db, mock_conn = mock_db
        self._set_cursor_rows(mock_conn, [
            (1, "geography", '{"zip_codes": ["75201"]}', 25, 0, "2026-02-15"),
        ])

        result = db.get_queries_by_date_range("2026-02-15", "2026-02-15")

        assert result[0]["query_params"] == {"zip_codes": ["75201"]}


class TestCacheStats:
    """Tests for cache statistics method."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database instance."""
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn
        return db, mock_conn

    def _set_cursor_rows(self, mock_conn, rows):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_conn.execute.return_value = mock_cursor

    def test_cache_stats_with_entries(self, mock_db):
        """Test cache stats with existing entries."""
        db, mock_conn = mock_db
        self._set_cursor_rows(mock_conn, [
            (10, "2026-02-10T10:00:00", "2026-02-17T10:00:00", 8),
        ])

        result = db.get_cache_stats()

        assert result["total"] == 10
        assert result["active"] == 8
        assert result["oldest"] == "2026-02-10T10:00:00"
        assert result["newest"] == "2026-02-17T10:00:00"

    def test_cache_stats_empty(self, mock_db):
        """Test cache stats with no entries."""
        db, mock_conn = mock_db
        self._set_cursor_rows(mock_conn, [(0, None, None, None)])

        result = db.get_cache_stats()

        assert result["total"] == 0
        assert result["active"] == 0

    def test_cache_stats_no_rows(self, mock_db):
        """Test cache stats when query returns no rows."""
        db, mock_conn = mock_db
        self._set_cursor_rows(mock_conn, [])

        result = db.get_cache_stats()

        assert result["total"] == 0


class TestLeadOutcomes:
    """Tests for lead outcome CRUD methods."""

    @pytest.fixture
    def mock_db(self):
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn
        return db, mock_conn

    def test_record_lead_outcomes_batch(self, mock_db):
        """Test batch inserting lead outcomes uses multi-row INSERT."""
        db, mock_conn = mock_db

        params = [
            ("HADES-20260212-001", "Acme Corp", "123", "person-001", "7011", 150,
             12.5, "75201", "TX", 85, "geography", "2026-02-12T10:00:00", '{"_score": 85}'),
            ("HADES-20260212-001", "Beta Inc", "456", None, "8211", 200,
             5.0, "75202", "TX", 72, "geography", "2026-02-12T10:00:00", None),
        ]
        db.record_lead_outcomes_batch(params)

        # Multi-row INSERT: single execute call with all rows + commit
        assert mock_conn.execute.call_count == 1
        mock_conn.commit.assert_called_once()

        # Verify the INSERT includes person_id column and 2 value groups (26 placeholders)
        insert_sql = mock_conn.execute.call_args_list[0][0][0]
        assert "person_id" in insert_sql
        assert insert_sql.count("?") == 26  # 13 columns × 2 rows

        # Verify flat params contain all values
        flat_params = mock_conn.execute.call_args_list[0][0][1]
        assert len(flat_params) == 26

    def test_record_lead_outcomes_with_person_id(self, mock_db):
        """Test that person_id is correctly passed in flat params."""
        db, mock_conn = mock_db

        params = [
            ("HADES-20260212-001", "Acme Corp", "123", "person-abc-123", "7011", 150,
             12.5, "75201", "TX", 85, "geography", "2026-02-12T10:00:00", None),
        ]
        db.record_lead_outcomes_batch(params)

        # Multi-row flat params: person_id is the 4th element (index 3)
        flat_params = mock_conn.execute.call_args_list[0][0][1]
        assert flat_params[3] == "person-abc-123"

    def test_record_lead_outcomes_rejects_duplicates(self):
        """Duplicate (batch_id, person_id) rows are silently ignored."""
        import sqlite3
        db = TursoDatabase.__new__(TursoDatabase)
        db._conn = sqlite3.connect(":memory:")
        db.url = ":memory:"
        db.init_schema()

        row = (
            "batch-1", "Acme Corp", "c-100", "p-200", "7011", 500,
            5.0, "75201", "TX", 85, "intent", "2026-02-22T10:00:00", None,
        )
        db.record_lead_outcomes_batch([row])
        db.record_lead_outcomes_batch([row])  # duplicate

        count = db.execute("SELECT COUNT(*) FROM lead_outcomes")[0][0]
        assert count == 1, f"Expected 1 row, got {count} — UNIQUE constraint missing"

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


class TestBuildOutcomeRow:
    """Tests for the consolidated build_outcome_row helper."""

    def test_basic_fields(self):
        """Test basic field extraction from a lead dict."""
        lead = {
            "companyName": "Acme Corp",
            "companyId": 123,
            "personId": "p-456",
            "sicCode": "7011",
            "employeeCount": 200,
            "_distance_miles": 12.5,
            "zipCode": "75201",
            "state": "TX",
            "_score": 85,
        }
        row = TursoDatabase.build_outcome_row(lead, "batch-1", "geography", "2026-01-01T10:00:00")

        assert row[0] == "batch-1"           # batch_id
        assert row[1] == "Acme Corp"         # company_name
        assert row[2] == "123"               # company_id (coerced to str)
        assert row[3] == "p-456"             # person_id
        assert row[4] == "7011"              # sic_code
        assert row[5] == 200                 # employee_count
        assert row[6] == 12.5               # distance_miles
        assert row[7] == "75201"             # zip_code
        assert row[8] == "TX"                # state
        assert row[9] == 85                  # hades_score
        assert row[10] == "geography"        # workflow_type
        assert row[11] == "2026-01-01T10:00:00"  # exported_at
        assert row[12] is None               # source_features (not provided)

    def test_company_dict_fallback(self):
        """Test field fallback to nested company dict."""
        lead = {
            "company": {"name": "Beta Inc", "id": "c-789", "sicCode": "8211",
                        "employeeCount": 300, "zip": "75202", "state": "CA"},
            "personId": "p-100",
        }
        row = TursoDatabase.build_outcome_row(lead, "batch-2", "intent", "2026-01-01")

        assert row[1] == "Beta Inc"    # falls back to company.name
        assert row[2] == "c-789"       # falls back to company.id
        assert row[4] == "8211"        # falls back to company.sicCode
        assert row[5] == 300           # falls back to company.employeeCount
        assert row[7] == "75202"       # falls back to company.zip
        assert row[8] == "CA"          # falls back to company.state

    def test_sic_code_computed_field_fallback(self):
        """Test _sic_code computed field is used when sicCode is missing."""
        lead = {"_sic_code": "3599", "personId": "p-1"}
        row = TursoDatabase.build_outcome_row(lead, "b", "geography", "now")
        assert row[4] == "3599"

    def test_employee_count_field_variants(self):
        """Test all employee count field name variants."""
        # 'employees' variant (from Contact Search)
        lead1 = {"employees": 50, "personId": "p-1"}
        assert TursoDatabase.build_outcome_row(lead1, "b", "geo", "now")[5] == 50

        # 'numberOfEmployees' variant (from Enrich)
        lead2 = {"numberOfEmployees": 100, "personId": "p-2"}
        assert TursoDatabase.build_outcome_row(lead2, "b", "geo", "now")[5] == 100

    def test_zip_field_variants(self):
        """Test all ZIP code field name variants."""
        # 'zip' variant
        lead1 = {"zip": "90210", "personId": "p-1"}
        assert TursoDatabase.build_outcome_row(lead1, "b", "geo", "now")[7] == "90210"

        # 'zipCode' variant
        lead2 = {"zipCode": "75201", "personId": "p-2"}
        assert TursoDatabase.build_outcome_row(lead2, "b", "geo", "now")[7] == "75201"

    def test_source_features_passed_through(self):
        """Test source_features parameter is included in tuple."""
        lead = {"personId": "p-1"}
        row = TursoDatabase.build_outcome_row(lead, "b", "intent", "now", '{"automated": true}')
        assert row[12] == '{"automated": true}'

    def test_missing_ids_produce_none(self):
        """Test that missing company/person IDs produce None."""
        lead = {"companyName": "No IDs Corp"}
        row = TursoDatabase.build_outcome_row(lead, "b", "geo", "now")
        assert row[2] is None  # company_id
        assert row[3] is None  # person_id (empty string from .get("id", "") is falsy)


class TestMultiRowInsert:
    """Tests for multi-row INSERT optimization in execute_many."""

    def test_multi_row_insert_single_execute(self):
        """Multi-row INSERT should produce 1 execute call, not N."""
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn

        params = [("a", 1), ("b", 2), ("c", 3)]
        db.execute_many("INSERT INTO t (name, val) VALUES (?, ?)", params)

        assert mock_conn.execute.call_count == 1
        sql = mock_conn.execute.call_args[0][0]
        assert sql.count("?") == 6  # 2 × 3 rows
        flat = mock_conn.execute.call_args[0][1]
        assert flat == ["a", 1, "b", 2, "c", 3]

    def test_empty_params_list_is_noop(self):
        """Empty params list should not call execute at all."""
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn

        db.execute_many("INSERT INTO t (x) VALUES (?)", [])

        mock_conn.execute.assert_not_called()
        mock_conn.commit.assert_not_called()

    def test_insert_or_ignore_optimized(self):
        """INSERT OR IGNORE should also use multi-row optimization."""
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn

        params = [("a",), ("b",)]
        db.execute_many("INSERT OR IGNORE INTO t (name) VALUES (?)", params)

        assert mock_conn.execute.call_count == 1
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT OR IGNORE" in sql
        assert sql.count("?") == 2

    def test_non_insert_uses_loop(self):
        """UPDATE statements should fall back to individual execute calls."""
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn

        params = [("a", 1), ("b", 2)]
        db.execute_many("UPDATE t SET name = ? WHERE id = ?", params)

        assert mock_conn.execute.call_count == 2  # one per row


class TestPipelineRuns:
    """Test pipeline_runs table operations."""

    def _get_db(self):
        """Create an in-memory DB with schema using stdlib sqlite3."""
        import sqlite3
        db = TursoDatabase.__new__(TursoDatabase)
        db._conn = sqlite3.connect(":memory:")
        db.url = ":memory:"
        db.init_schema()
        return db

    def test_start_pipeline_run_returns_id(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {"topics": ["Vending"]})
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_complete_pipeline_run_success(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "manual", {})
        db.complete_pipeline_run(
            run_id, "success",
            summary={"contacts_exported": 10},
            batch_id="HADES-20260216-001",
            credits_used=10,
            leads_exported=10,
            error=None,
        )
        runs = db.get_pipeline_runs("intent")
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["batch_id"] == "HADES-20260216-001"
        assert runs[0]["credits_used"] == 10
        assert runs[0]["leads_exported"] == 10
        assert runs[0]["completed_at"] is not None

    def test_complete_pipeline_run_failed(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(
            run_id, "failed",
            summary={}, batch_id=None,
            credits_used=0, leads_exported=0,
            error="API timeout",
        )
        runs = db.get_pipeline_runs("intent")
        assert runs[0]["status"] == "failed"
        assert runs[0]["error_message"] == "API timeout"

    def test_complete_pipeline_run_skipped(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {"topics": ["Vending"]})
        db.complete_pipeline_run(
            run_id, "skipped",
            summary={"budget_exceeded": True}, batch_id=None,
            credits_used=0, leads_exported=0,
            error="Weekly cap reached",
        )
        runs = db.get_pipeline_runs("intent")
        assert runs[0]["status"] == "skipped"

    def test_get_pipeline_runs_ordered_newest_first(self):
        db = self._get_db()
        id1 = db.start_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(id1, "success", {}, "B1", 5, 5, None)
        id2 = db.start_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(id2, "success", {}, "B2", 10, 10, None)
        runs = db.get_pipeline_runs("intent", limit=10)
        assert len(runs) == 2
        assert runs[0]["id"] == id2  # Newest first

    def test_get_pipeline_runs_respects_limit(self):
        db = self._get_db()
        for i in range(5):
            rid = db.start_pipeline_run("intent", "scheduled", {})
            db.complete_pipeline_run(rid, "success", {}, None, 0, 0, None)
        runs = db.get_pipeline_runs("intent", limit=3)
        assert len(runs) == 3

    def test_get_pipeline_runs_filters_by_workflow(self):
        db = self._get_db()
        rid = db.start_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(rid, "success", {}, None, 0, 0, None)
        runs = db.get_pipeline_runs("geography")
        assert len(runs) == 0

    def test_start_run_stores_config(self):
        db = self._get_db()
        config = {"topics": ["Vending"], "target_companies": 25}
        run_id = db.start_pipeline_run("intent", "manual", config)
        runs = db.get_pipeline_runs("intent")
        assert runs[0]["config"] == config

    def test_start_run_sets_running_status(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {})
        runs = db.get_pipeline_runs("intent")
        assert runs[0]["status"] == "running"
        assert runs[0]["completed_at"] is None

    def test_has_running_pipeline(self):
        """Detect if a pipeline run is already in progress."""
        db = self._get_db()
        assert db.has_running_pipeline("intent") is False

        run_id = db.start_pipeline_run("intent", "scheduled", {})
        assert db.has_running_pipeline("intent") is True

        db.complete_pipeline_run(run_id, "success", {}, None, 0, 0, None)
        assert db.has_running_pipeline("intent") is False


class TestStagedExportPushTracking:
    """Tests for push tracking columns on staged_exports."""

    def _get_db(self):
        """Create an in-memory DB with schema using stdlib sqlite3."""
        import sqlite3
        db = TursoDatabase.__new__(TursoDatabase)
        db._conn = sqlite3.connect(":memory:")
        db.url = ":memory:"
        db.init_schema()
        return db

    def test_mark_staged_pushed_complete(self):
        db = self._get_db()
        export_id = db.save_staged_export("geography", [{"name": "test"}])
        results_json = '{"succeeded": 5, "failed": 0}'
        db.mark_staged_pushed(export_id, "complete", results_json)
        row = db.get_staged_export(export_id)
        assert row["push_status"] == "complete"
        assert row["pushed_at"] is not None
        assert row["push_results_json"] == results_json

    def test_mark_staged_pushed_partial(self):
        db = self._get_db()
        export_id = db.save_staged_export("intent", [{"name": "test"}])
        results_json = '{"succeeded": 3, "failed": 2, "failed_indices": [1, 4]}'
        db.mark_staged_pushed(export_id, "partial", results_json)
        row = db.get_staged_export(export_id)
        assert row["push_status"] == "partial"
        assert row["push_results_json"] == results_json

    def test_get_staged_export_includes_push_fields(self):
        db = self._get_db()
        export_id = db.save_staged_export("geography", [{"name": "test"}])
        row = db.get_staged_export(export_id)
        assert row["push_status"] is None
        assert row["pushed_at"] is None
        assert row["push_results_json"] is None


class TestPurgeOldStagedExports:
    """Tests for PII retention: purging old staged exports."""

    def _get_db(self):
        """Create an in-memory DB with schema using stdlib sqlite3."""
        import sqlite3
        db = TursoDatabase.__new__(TursoDatabase)
        db._conn = sqlite3.connect(":memory:")
        db.url = ":memory:"
        db.init_schema()
        return db

    def test_purge_deletes_old_records(self):
        db = self._get_db()
        # Insert a record with old created_at
        db.execute_write(
            "INSERT INTO staged_exports (workflow_type, leads_json, lead_count, created_at) "
            "VALUES (?, ?, ?, datetime('now', '-100 days'))",
            ("intent", '[{"name": "old"}]', 1),
        )
        # Insert a recent record
        db.save_staged_export("geography", [{"name": "new"}])

        count = db.purge_old_staged_exports(days=90)
        assert count == 1

        # Recent record should still exist
        exports = db.get_staged_exports(limit=10)
        assert len(exports) == 1
        assert exports[0]["workflow_type"] == "geography"

    def test_purge_preserves_recent_records(self):
        db = self._get_db()
        db.save_staged_export("intent", [{"name": "recent"}])
        count = db.purge_old_staged_exports(days=90)
        assert count == 0

        exports = db.get_staged_exports(limit=10)
        assert len(exports) == 1

    def test_purge_empty_table(self):
        db = self._get_db()
        count = db.purge_old_staged_exports(days=90)
        assert count == 0

    def test_purge_custom_days(self):
        db = self._get_db()
        # Insert a record 10 days old
        db.execute_write(
            "INSERT INTO staged_exports (workflow_type, leads_json, lead_count, created_at) "
            "VALUES (?, ?, ?, datetime('now', '-10 days'))",
            ("intent", '[{"name": "ten_days_old"}]', 1),
        )
        # 30-day purge should delete it? No, 10 < 30
        assert db.purge_old_staged_exports(days=30) == 0
        # 5-day purge should delete it
        assert db.purge_old_staged_exports(days=5) == 1


class TestMigrations:
    """Tests for _run_migrations using PRAGMA table_info."""

    def test_migration_skips_existing_column(self):
        """Migration should skip columns that already exist (uses PRAGMA table_info)."""
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn

        # Return all migration-target columns as already existing per table
        table_columns = {
            "operators": [
                (0, "id", "INTEGER", 1, None, 1),
                (1, "zoho_id", "TEXT", 0, None, 0),
                (2, "synced_at", "TIMESTAMP", 0, None, 0),
            ],
            "lead_outcomes": [
                (0, "id", "INTEGER", 1, None, 1),
                (1, "person_id", "TEXT", 0, None, 0),
            ],
            "staged_exports": [
                (0, "id", "INTEGER", 1, None, 1),
                (1, "push_status", "TEXT", 0, None, 0),
                (2, "pushed_at", "TEXT", 0, None, 0),
                (3, "push_results_json", "TEXT", 0, None, 0),
            ],
        }

        def side_effect(query, *args):
            cursor = MagicMock()
            for table, cols in table_columns.items():
                if f"table_info({table})" in query:
                    cursor.fetchall.return_value = cols
                    return cursor
            cursor.fetchall.return_value = []
            return cursor

        mock_conn.execute.side_effect = side_effect

        db._run_migrations()

        # Should not have executed any ALTER TABLE since all columns exist
        all_queries = [str(c) for c in mock_conn.execute.call_args_list]
        alter_calls = [q for q in all_queries if "ALTER" in q]
        assert len(alter_calls) == 0
