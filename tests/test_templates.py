"""Tests for TemplatesMixin (db/_templates.py)."""

import sys
from unittest.mock import MagicMock

# Mock external dependencies before importing
sys.modules.setdefault("libsql_experimental", MagicMock())
sys.modules.setdefault("streamlit", MagicMock())

from db._templates import TemplatesMixin


class _StubDB(TemplatesMixin):
    """Minimal stub that provides execute/execute_write via mock."""

    def __init__(self):
        self.execute = MagicMock()
        self.execute_write = MagicMock()


class TestRenameLocationTemplate:
    """Tests for rename_location_template."""

    def test_rename_calls_update(self):
        db = _StubDB()
        db.rename_location_template(42, "New Name")
        db.execute_write.assert_called_once()
        sql, params = db.execute_write.call_args[0]
        assert "UPDATE" in sql.upper()
        assert params == ("New Name", 42)

    def test_rename_then_verify(self):
        """Rename + get should reflect new name."""
        db = _StubDB()
        db.rename_location_template(1, "Renamed Template")
        # Verify the UPDATE was called with correct params
        sql, params = db.execute_write.call_args[0]
        assert "location_templates" in sql.lower()
        assert params[0] == "Renamed Template"
        assert params[1] == 1
