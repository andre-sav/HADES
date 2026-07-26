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
        # 2 commits: the operator INSERT + the mutation-log audit row
        # (HADES-6if). The operator write itself is what matters here.
        assert mock_conn.commit.call_count == 2
        assert any("INSERT INTO operators" in c[0][0]
                   for c in mock_conn.execute.call_args_list)

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
        db._in_transaction = False
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
            (1, "HADES-20260212-001", "Acme Corp", "C123", "P456",
             "7011", 150, 85, "geography", "2026-02-12", None, None,
             "75201", "TX"),
        ]
        mock_conn.execute.return_value = mock_cursor

        result = db.get_outcomes_by_batch("HADES-20260212-001")

        assert len(result) == 1
        assert result[0]["company_name"] == "Acme Corp"
        assert result[0]["batch_id"] == "HADES-20260212-001"
        assert result[0]["company_id"] == "C123"
        assert result[0]["person_id"] == "P456"
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

        # The outcome UPDATE plus the mutation-log audit row (HADES-6if).
        outcome_calls = [c[0] for c in mock_conn.execute.call_args_list
                         if "UPDATE lead_outcomes" in c[0][0]]
        assert len(outcome_calls) == 1
        assert outcome_calls[0][1] == ("delivery", "2026-03-01", "HADES-20260212-001", "Acme Corp")
        assert any("mutation_log" in c[0][0] for c in mock_conn.execute.call_args_list)

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
        assert flat == ("a", 1, "b", 2, "c", 3)

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


class TestExecuteManyTransactionSafety:
    """N-01/N-10: execute_many must roll back leaked statements on non-stale
    failures (or the next unrelated commit silently persists a partial batch
    on the shared connection) and defer commits to an enclosing transaction()
    exactly like execute_write does."""

    def _db(self):
        mock_conn = MagicMock()
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="test-token")
        db._conn = mock_conn
        return db, mock_conn

    def test_fallback_rolls_back_on_non_stale_failure(self):
        """Row 2 of an UPDATE batch fails: row 1 must be rolled back, not
        left pending for an unrelated later commit."""
        db, conn = self._db()
        conn.execute.side_effect = [MagicMock(), ValueError("constraint")]
        with pytest.raises(ValueError):
            db.execute_many("UPDATE t SET name = ? WHERE id = ?", [("a", 1), ("b", 2)])
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_multi_row_insert_rolls_back_on_non_stale_failure(self):
        """Batch 2 of a chunked INSERT fails: batch 1 must be rolled back."""
        db, conn = self._db()
        conn.execute.side_effect = [MagicMock(), ValueError("bind error")]
        # 2 cols → batch_size 450; 500 rows → 2 batches
        params = [("a", i) for i in range(500)]
        with pytest.raises(ValueError):
            db.execute_many("INSERT INTO t (name, val) VALUES (?, ?)", params)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_fallback_defers_commit_inside_transaction(self):
        db, conn = self._db()
        db._in_transaction = True
        db.execute_many("UPDATE t SET name = ? WHERE id = ?", [("a", 1)])
        conn.commit.assert_not_called()

    def test_multi_row_insert_defers_commit_inside_transaction(self):
        db, conn = self._db()
        db._in_transaction = True
        db.execute_many("INSERT INTO t (name) VALUES (?)", [("a",)])
        conn.commit.assert_not_called()

    def test_failure_inside_transaction_leaves_rollback_to_owner(self):
        """transaction() owns the rollback (matching execute/execute_write) —
        execute_many must raise without rolling back the enclosing
        transaction's earlier statements itself."""
        db, conn = self._db()
        db._in_transaction = True
        conn.execute.side_effect = ValueError("constraint")
        with pytest.raises(ValueError):
            db.execute_many("UPDATE t SET name = ?", [("a",)])
        conn.rollback.assert_not_called()

    def test_stale_stream_inside_transaction_raises_without_replay(self):
        """HADES-638 contract: replaying only the current statement inside an
        open transaction would let transaction() commit a PARTIAL transaction."""
        db, conn = self._db()
        db._in_transaction = True
        conn.execute.side_effect = Exception("Hrana: stream not found (404)")
        with pytest.raises(Exception, match="stream not found"):
            db.execute_many("INSERT INTO t (name) VALUES (?)", [("a",)])
        assert db._conn is conn  # no reconnect happened
        conn.commit.assert_not_called()

    def test_rollback_failure_does_not_mask_original_error(self):
        db, conn = self._db()
        conn.execute.side_effect = ValueError("original")
        conn.rollback.side_effect = Exception("stream dead")
        with pytest.raises(ValueError, match="original"):
            db.execute_many("UPDATE t SET name = ?", [("a",)])


class TestPipelineRuns:
    """Test pipeline_runs table operations."""

    def _get_db(self):
        """Create an in-memory DB with schema using stdlib sqlite3."""
        import sqlite3
        db = TursoDatabase.__new__(TursoDatabase)
        db._conn = sqlite3.connect(":memory:")
        db.url = ":memory:"
        db._in_transaction = False
        db.init_schema()
        return db

    def test_start_pipeline_run_returns_id(self):
        db = self._get_db()
        run_id = db.start_pipeline_run("intent", "scheduled", {"topics": ["Vending"]})
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_claim_pipeline_run_returns_id_when_free(self):
        db = self._get_db()
        run_id = db.claim_pipeline_run("intent", "scheduled", {"topics": ["Vending"]})
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_claim_pipeline_run_refuses_second_concurrent_claim(self):
        """N-16: the old check-then-insert pair had a TOCTOU window — the
        scheduled cron firing while a user clicks Run Now double-ran the
        pipeline and double-spent credits. The claim is one atomic statement."""
        db = self._get_db()
        first = db.claim_pipeline_run("intent", "scheduled", {})
        second = db.claim_pipeline_run("intent", "manual", {})
        assert first is not None
        assert second is None

    def test_claim_ignores_stale_running_rows(self):
        """A crashed run must not hold the lock forever (mirrors
        has_running_pipeline's 30-minute staleness window)."""
        db = self._get_db()
        first = db.claim_pipeline_run("intent", "scheduled", {})
        db.execute_write(
            "UPDATE pipeline_runs SET started_at = datetime('now', '-45 minutes') WHERE id = ?",
            (first,),
        )
        second = db.claim_pipeline_run("intent", "manual", {})
        assert second is not None

    def test_claim_scoped_per_workflow(self):
        db = self._get_db()
        assert db.claim_pipeline_run("intent", "scheduled", {}) is not None
        assert db.claim_pipeline_run("geography", "manual", {}) is not None

    def test_claim_frees_after_completion(self):
        db = self._get_db()
        first = db.claim_pipeline_run("intent", "scheduled", {})
        db.complete_pipeline_run(first, "success", {}, None, 0, 0, None)
        assert db.claim_pipeline_run("intent", "scheduled", {}) is not None

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
        db._in_transaction = False
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
        db._in_transaction = False
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
                (3, "deleted_at", "TIMESTAMP", 0, None, 0),
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
                (4, "deleted_at", "TIMESTAMP", 0, None, 0),
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


class TestExcludeBatchId:
    """HADES-guz: a loaded staged batch must not be blocked by its own outcome rows."""

    def _db(self):
        from turso_db import TursoDatabase
        from unittest.mock import MagicMock, patch
        with patch.object(TursoDatabase, "__init__", lambda self: None):
            db = TursoDatabase()
        db._conn = MagicMock()
        return db

    def test_exclude_batch_id_added_to_query(self):
        db = self._db()
        captured = {}
        def fake_execute(query, params=()):
            captured["query"] = query
            captured["params"] = params
            return []
        db.execute = fake_execute
        db.get_exported_company_ids(days_back=365, exclude_batch_id="HADES-20260711-001")
        assert "batch_id != ?" in captured["query"]
        assert "HADES-20260711-001" in captured["params"]

    def test_no_exclude_means_no_batch_condition(self):
        db = self._db()
        captured = {}
        def fake_execute(query, params=()):
            captured["query"] = query
            captured["params"] = params
            return []
        db.execute = fake_execute
        db.get_exported_company_ids(days_back=365)
        assert "batch_id" not in captured["query"]


class TestCacheExpiryFormat:
    """R-17 (HADES-8s5): expires_at was written as local 'T'-ISO but compared
    lexicographically against CURRENT_TIMESTAMP (UTC, space) — 'T' > ' ' kept
    entries 'fresh' through their whole expiry date."""

    def _db(self):
        from turso_db import TursoDatabase
        from unittest.mock import MagicMock, patch
        with patch.object(TursoDatabase, "__init__", lambda self: None):
            db = TursoDatabase()
        db._conn = MagicMock()
        return db

    def test_expires_at_written_in_sqlite_utc_format(self):
        import re
        from datetime import datetime, timezone
        db = self._db()
        captured = {}
        db.execute_write = lambda q, p=(): captured.update({"q": q, "p": p})
        db.cache_results("cid", "intent", {}, [], ttl_days=7)
        expires_at = captured["p"][4]
        # SQLite-native: 'YYYY-MM-DD HH:MM:SS' — no 'T', no microseconds, no offset
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", expires_at), expires_at
        # and it is UTC-based: within a minute of now(UTC)+7d
        dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        drift = abs((dt - datetime.now(timezone.utc)).total_seconds() - 7 * 86400)
        assert drift < 60

    def test_reads_normalize_legacy_t_format(self):
        """The read/purge/stats SQL must compare via datetime(expires_at) so
        legacy 'T'-format rows expire correctly. Verified against real SQLite."""
        import sqlite3
        from datetime import datetime, timedelta, timezone
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE zoominfo_cache (id TEXT, expires_at TEXT)")
        now_utc = datetime.now(timezone.utc)
        expired_dt = now_utc - timedelta(seconds=5)
        expired_t = expired_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")
        fresh_t = (now_utc + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")
        conn.execute("INSERT INTO zoominfo_cache VALUES ('old', ?)", (expired_t,))
        conn.execute("INSERT INTO zoominfo_cache VALUES ('new', ?)", (fresh_t,))
        # the buggy raw compare keeps the expired row "fresh" whenever the
        # expiry DATE equals today's UTC date ('T' > ' ' at position 10)
        buggy = conn.execute(
            "SELECT id FROM zoominfo_cache WHERE expires_at > CURRENT_TIMESTAMP").fetchall()
        if expired_dt.date() == now_utc.date():  # skip only across UTC midnight
            assert ("old",) in buggy  # documents the bug this fix removes
        # the fixed compare expires it
        fixed = conn.execute(
            "SELECT id FROM zoominfo_cache WHERE datetime(expires_at) > datetime('now')").fetchall()
        assert fixed == [("new",)]

    def test_mixin_sql_uses_datetime_normalization(self):
        import inspect
        from db._cache import CacheMixin
        src = inspect.getsource(CacheMixin)
        assert "datetime(expires_at)" in src
        assert "expires_at > CURRENT_TIMESTAMP" not in src
        assert "expires_at <= CURRENT_TIMESTAMP" not in src


class TestConnectionThreadSafety:
    """R-19 (HADES-638): one cached connection is shared by every Streamlit
    session/thread with no lock, and a stale-stream reconnect inside an open
    transaction silently replayed only the failing statement — committing a
    partial transaction."""

    def _db(self):
        from turso_db import TursoDatabase
        from unittest.mock import MagicMock, patch
        with patch.object(TursoDatabase, "__init__", lambda self: None):
            db = TursoDatabase()
        db._conn = MagicMock()
        db._in_transaction = False
        return db

    def test_stale_stream_inside_transaction_raises(self):
        """No single-statement replay inside a transaction: earlier uncommitted
        statements died with the old stream — replaying just this one and then
        committing would persist a partial transaction."""
        import pytest
        db = self._db()
        stale = Exception("Hrana: api error: status=404, `stream not found`")
        db._conn.execute.side_effect = stale
        reconnected = MagicMock()
        db._reconnect = MagicMock(return_value=reconnected)
        with pytest.raises(Exception, match="stream not found"):
            with db.transaction():
                db.execute_write("INSERT INTO t VALUES (?)", ("x",))
        db._reconnect.assert_not_called()
        reconnected.execute.assert_not_called()

    def test_stale_stream_outside_transaction_still_replays(self):
        db = self._db()
        stale = Exception("Hrana: api error: status=404, `stream not found`")
        db._conn.execute.side_effect = stale
        reconnected = MagicMock()
        cursor = MagicMock()
        cursor.lastrowid = 7
        reconnected.execute.return_value = cursor
        db._reconnect = MagicMock(return_value=reconnected)
        assert db.execute_write("INSERT INTO t VALUES (?)", ("x",)) == 7
        reconnected.commit.assert_called_once()

    def test_transaction_holds_the_lock(self):
        """While one thread is inside transaction(), another thread must not
        be able to acquire the connection lock (serialized access)."""
        import threading
        db = self._db()
        acquired_during_txn = []
        with db.transaction():
            def _try():
                acquired_during_txn.append(db.lock.acquire(blocking=False))
            t = threading.Thread(target=_try)
            t.start()
            t.join()
        assert acquired_during_txn == [False]
        # and it is released afterwards
        assert db.lock.acquire(blocking=False) is True
        db.lock.release()

    def test_execute_serialized_under_lock(self):
        """execute() must run under the shared lock."""
        db = self._db()
        db._conn.execute.return_value.fetchall.return_value = []
        seen = []
        real_lock = db.lock

        class SpyLock:
            def __enter__(self):
                seen.append("acquired")
                return real_lock.__enter__()
            def __exit__(self, *a):
                return real_lock.__exit__(*a)

        db._lock = SpyLock()
        db.execute("SELECT 1")
        assert seen == ["acquired"]


class TestP3QuickWins:
    """Grouped P3 fixes from the 2026-07-11 review (HADES-7qi)."""

    def test_init_schema_wires_cache_and_error_log_purges(self):
        """clear_expired_cache and purge_old_error_logs had ZERO callers —
        unbounded Turso growth. They belong next to the staged purge."""
        import inspect
        from db._schema import SchemaMixin
        src = inspect.getsource(SchemaMixin.init_schema)
        assert "clear_expired_cache" in src
        assert "purge_old_error_logs" in src


class TestRetentionPurges:
    """Review N-14: credit_usage and query_history grow one row per API call
    forever; company_id_mapping is a cache with no TTL. Cap them like the
    other purged tables."""

    def _db(self):
        db = TursoDatabase(url="libsql://test.turso.io", auth_token="t")
        db._conn = MagicMock()
        db.execute = MagicMock(return_value=[(3,)])
        db.execute_write = MagicMock()
        return db

    def test_purge_old_credit_usage(self):
        db = self._db()
        deleted = db.purge_old_credit_usage(days=365)
        assert deleted == 3
        sql = db.execute_write.call_args[0][0]
        assert "DELETE FROM credit_usage" in sql
        assert "created_at" in sql
        assert "-365 days" in db.execute_write.call_args[0][1]

    def test_purge_old_query_history(self):
        db = self._db()
        deleted = db.purge_old_query_history(days=365)
        assert deleted == 3
        sql = db.execute_write.call_args[0][0]
        assert "DELETE FROM query_history" in sql
        assert "created_at" in sql

    def test_purge_old_company_id_mappings(self):
        db = self._db()
        deleted = db.purge_old_company_id_mappings(days=180)
        assert deleted == 3
        sql = db.execute_write.call_args[0][0]
        assert "DELETE FROM company_id_mapping" in sql
        assert "resolved_at" in sql
        assert "-180 days" in db.execute_write.call_args[0][1]

    def test_purges_skip_delete_when_nothing_old(self):
        db = self._db()
        db.execute = MagicMock(return_value=[(0,)])
        assert db.purge_old_credit_usage() == 0
        db.execute_write.assert_not_called()

    def test_init_schema_wires_retention_purges(self):
        import inspect
        from db._schema import SchemaMixin
        src = inspect.getsource(SchemaMixin.init_schema)
        assert "purge_old_credit_usage" in src
        assert "purge_old_query_history" in src
        assert "purge_old_company_id_mappings" in src

    def test_recent_operator_ids_orders_by_max_created(self):
        """DISTINCT + ORDER BY created_at returns an arbitrary row's timestamp
        per operator (observed: the oldest) — wrong recent-operators order."""
        from turso_db import TursoDatabase
        from unittest.mock import patch
        with patch.object(TursoDatabase, "__init__", lambda self: None):
            db = TursoDatabase()
        captured = {}
        db.execute = lambda q, p=(): captured.update({"q": q}) or []
        db.get_recent_operator_ids(limit=5)
        q = captured["q"].upper()
        assert "GROUP BY" in q
        assert "MAX(S.CREATED_AT)" in q
