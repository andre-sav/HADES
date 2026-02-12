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
