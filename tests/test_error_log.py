"""Tests for ErrorLogMixin (db/_error_log.py)."""

import sys
import json
from unittest.mock import MagicMock

sys.modules.setdefault("libsql_experimental", MagicMock())
sys.modules.setdefault("streamlit", MagicMock())

from db._error_log import ErrorLogMixin


class _StubDB(ErrorLogMixin):
    def __init__(self):
        self.execute = MagicMock()
        self.execute_write = MagicMock()


class TestErrorLogMixin:

    def test_log_error(self):
        db = _StubDB()
        db.log_error(
            workflow_type="intent",
            error_type="ZoomInfoAPIError",
            user_message="API error occurred",
            technical_message="HTTP 500",
            recoverable=True,
        )
        db.execute_write.assert_called_once()
        sql, params = db.execute_write.call_args[0]
        assert "INSERT" in sql.upper()
        assert params[0] == "intent"
        assert params[1] == "ZoomInfoAPIError"
        assert params[4] == 1  # recoverable

    def test_log_error_with_context(self):
        db = _StubDB()
        ctx = {"batch_id": "HADES-001", "zip": "75201"}
        db.log_error(
            workflow_type="geography",
            error_type="BudgetExceededError",
            user_message="Budget exceeded",
            context=ctx,
        )
        sql, params = db.execute_write.call_args[0]
        assert json.loads(params[5]) == ctx

    def test_log_error_without_context(self):
        db = _StubDB()
        db.log_error(
            workflow_type="intent",
            error_type="TestError",
            user_message="Test",
        )
        sql, params = db.execute_write.call_args[0]
        assert params[5] is None  # context_json

    def test_get_recent_errors(self):
        db = _StubDB()
        db.execute.return_value = [
            (1, "intent", "ZoomInfoAPIError", "API error", "HTTP 500", 1, None, "2026-02-23T10:00:00"),
        ]
        errors = db.get_recent_errors(limit=10)
        assert len(errors) == 1
        assert errors[0]["workflow_type"] == "intent"
        assert errors[0]["recoverable"] is True

    def test_get_recent_errors_empty(self):
        db = _StubDB()
        db.execute.return_value = []
        errors = db.get_recent_errors()
        assert errors == []

    def test_get_errors_by_workflow(self):
        db = _StubDB()
        db.execute.return_value = [
            (2, "geography", "BudgetExceededError", "Budget exceeded", "", 0, '{"cap": 500}', "2026-02-23T11:00:00"),
        ]
        errors = db.get_errors_by_workflow("geography")
        assert len(errors) == 1
        assert errors[0]["error_type"] == "BudgetExceededError"
        assert errors[0]["recoverable"] is False
