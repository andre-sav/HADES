"""Tests for MetadataMixin (db/_metadata.py)."""

import sys
import pytest
from unittest.mock import MagicMock

# Mock external dependencies before importing
sys.modules.setdefault("libsql_experimental", MagicMock())
sys.modules.setdefault("streamlit", MagicMock())

from db._metadata import MetadataMixin


class _StubDB(MetadataMixin):
    """Minimal stub that provides execute/execute_write via mock."""

    def __init__(self):
        self.execute = MagicMock()
        self.execute_write = MagicMock()


class TestMetadataMixin:
    """get_sync_value / set_sync_value CRUD."""

    def test_get_found(self):
        db = _StubDB()
        db.execute.return_value = [("some_value",)]
        assert db.get_sync_value("my_key") == "some_value"
        db.execute.assert_called_once()
        assert "my_key" in db.execute.call_args[0][1]

    def test_get_missing_returns_none(self):
        db = _StubDB()
        db.execute.return_value = []
        assert db.get_sync_value("missing") is None

    def test_set_new(self):
        db = _StubDB()
        db.set_sync_value("new_key", "new_value")
        db.execute_write.assert_called_once()
        sql, params = db.execute_write.call_args[0]
        assert "INSERT" in sql.upper()
        assert params == ("new_key", "new_value")

    def test_set_update(self):
        db = _StubDB()
        db.set_sync_value("key", "first")
        db.set_sync_value("key", "second")
        assert db.execute_write.call_count == 2
        _, params = db.execute_write.call_args[0]
        assert params == ("key", "second")
