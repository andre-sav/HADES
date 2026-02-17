"""
Tests for the pipeline error hierarchy.

Run with: pytest tests/test_errors.py -v
"""

import sys
from unittest.mock import MagicMock

# Mock streamlit before importing modules that depend on it
sys.modules["streamlit"] = MagicMock()

from errors import PipelineError
from zoominfo_client import (
    ZoomInfoError,
    ZoomInfoAuthError,
    ZoomInfoRateLimitError,
    ZoomInfoAPIError,
)
from cost_tracker import BudgetExceededError


class TestPipelineErrorBase:
    """Tests for PipelineError base class."""

    def test_has_message_and_user_message(self):
        e = PipelineError(
            message="technical detail",
            user_message="user-safe text",
            recoverable=True,
        )
        assert e.message == "technical detail"
        assert e.user_message == "user-safe text"
        assert e.recoverable is True

    def test_str_returns_message(self):
        e = PipelineError(message="tech msg", user_message="user msg")
        assert str(e) == "tech msg"

    def test_recoverable_defaults_true(self):
        e = PipelineError(message="m", user_message="u")
        assert e.recoverable is True

    def test_is_exception(self):
        assert issubclass(PipelineError, Exception)


class TestZoomInfoErrorHierarchy:
    """Tests that ZoomInfo errors inherit from PipelineError."""

    def test_zoominfo_error_is_pipeline_error(self):
        assert issubclass(ZoomInfoError, PipelineError)

    def test_zoominfo_auth_error_is_pipeline_error(self):
        e = ZoomInfoAuthError("auth failed")
        assert isinstance(e, PipelineError)
        assert e.recoverable is False
        assert "credentials" in e.user_message.lower()

    def test_zoominfo_rate_limit_error_is_pipeline_error(self):
        e = ZoomInfoRateLimitError(retry_after=60)
        assert isinstance(e, PipelineError)
        assert e.recoverable is True
        assert "1 minute" in e.user_message

    def test_zoominfo_api_error_is_pipeline_error(self):
        e = ZoomInfoAPIError(status_code=500, message="Internal Server Error")
        assert isinstance(e, PipelineError)
        assert e.recoverable is True  # 5xx = recoverable
        assert "(500)" in e.user_message

    def test_zoominfo_api_error_4xx_not_recoverable(self):
        e = ZoomInfoAPIError(status_code=400, message="Bad Request")
        assert e.recoverable is False

    def test_zoominfo_api_error_truncates_long_message(self):
        long_msg = "x" * 500
        e = ZoomInfoAPIError(status_code=400, message=long_msg)
        assert len(e.user_message) < 300  # Truncated in user_message
        assert long_msg in e.message  # Full detail in technical message

    def test_zoominfo_api_error_strips_newlines_in_user_message(self):
        e = ZoomInfoAPIError(status_code=400, message="line1\nline2\nline3")
        assert "\n" not in e.user_message


class TestBudgetExceededErrorHierarchy:
    """Tests that BudgetExceededError inherits from PipelineError."""

    def test_budget_error_is_pipeline_error(self):
        e = BudgetExceededError(
            workflow_type="intent",
            current_usage=480,
            cap=500,
            requested=25,
        )
        assert isinstance(e, PipelineError)

    def test_budget_error_has_user_message(self):
        e = BudgetExceededError(
            workflow_type="intent",
            current_usage=480,
            cap=500,
            requested=25,
        )
        assert "Intent" in e.user_message  # Title-cased
        assert "480" in e.user_message
        assert "500" in e.user_message
        assert "25" in e.user_message
        assert "Monday" in e.user_message

    def test_budget_error_not_recoverable(self):
        e = BudgetExceededError(
            workflow_type="intent",
            current_usage=480,
            cap=500,
            requested=25,
        )
        assert e.recoverable is False

    def test_budget_error_preserves_numeric_fields(self):
        e = BudgetExceededError(
            workflow_type="geography",
            current_usage=100,
            cap=200,
            requested=150,
        )
        assert e.workflow_type == "geography"
        assert e.current_usage == 100
        assert e.cap == 200
        assert e.requested == 150
        assert e.remaining == 100

    def test_budget_error_technical_message(self):
        e = BudgetExceededError(
            workflow_type="intent",
            current_usage=480,
            cap=500,
            requested=25,
        )
        assert "intent" in e.message  # Technical message has raw workflow type
        assert "480" in e.message


class TestCatchPipelineError:
    """Tests that catching PipelineError catches all subtypes."""

    def test_catches_zoominfo_error(self):
        try:
            raise ZoomInfoAuthError("auth failed")
        except PipelineError as e:
            assert e.user_message  # Caught successfully
        else:
            assert False, "PipelineError should catch ZoomInfoAuthError"

    def test_catches_budget_error(self):
        try:
            raise BudgetExceededError("intent", 480, 500, 25)
        except PipelineError as e:
            assert e.user_message  # Caught successfully
        else:
            assert False, "PipelineError should catch BudgetExceededError"

    def test_catches_api_error(self):
        try:
            raise ZoomInfoAPIError(429, "Too Many Requests")
        except PipelineError as e:
            assert "(429)" in e.user_message
        else:
            assert False, "PipelineError should catch ZoomInfoAPIError"
