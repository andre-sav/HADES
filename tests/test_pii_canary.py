"""
PII sanitization canary tests.

Regression guard: every PipelineError subclass must produce a user_message
that contains no email addresses or phone numbers.  If a new error class
leaks raw API messages into user_message, these tests will catch it.
"""

import re
import sys
from unittest.mock import MagicMock

# Mock streamlit before importing modules that depend on it
sys.modules.setdefault("streamlit", MagicMock())

import pytest
from errors import (
    PipelineError,
    ZoomInfoAuthError,
    ZoomInfoRateLimitError,
    ZoomInfoAPIError,
    BudgetExceededError,
    ZohoAPIError,
)

# PII patterns that must never appear in user-facing messages
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")

PII_MESSAGE = (
    "Contact john.doe@example.com at (555) 123-4567 "
    "or jane@test.org for account 12345"
)


def _assert_no_pii(user_message: str, error_class: str):
    """Assert user_message contains no email or phone patterns."""
    emails = EMAIL_RE.findall(user_message)
    phones = PHONE_RE.findall(user_message)
    assert not emails, f"{error_class}.user_message leaks email: {emails}"
    assert not phones, f"{error_class}.user_message leaks phone: {phones}"


class TestPIICanary:
    """Every error subclass must sanitize user_message."""

    def test_pipeline_error_base(self):
        err = PipelineError(
            message=PII_MESSAGE,
            user_message="Safe message",
        )
        _assert_no_pii(err.user_message, "PipelineError")

    def test_zoominfo_auth_error(self):
        err = ZoomInfoAuthError(message=PII_MESSAGE)
        _assert_no_pii(err.user_message, "ZoomInfoAuthError")

    def test_zoominfo_rate_limit_error(self):
        err = ZoomInfoRateLimitError(retry_after=60, detail=PII_MESSAGE)
        _assert_no_pii(err.user_message, "ZoomInfoRateLimitError")

    def test_zoominfo_api_error(self):
        err = ZoomInfoAPIError(status_code=500, message=PII_MESSAGE)
        _assert_no_pii(err.user_message, "ZoomInfoAPIError")

    def test_budget_exceeded_error(self):
        err = BudgetExceededError(
            workflow_type="intent",
            current_usage=400,
            cap=500,
            requested=200,
        )
        _assert_no_pii(err.user_message, "BudgetExceededError")

    def test_zoho_api_error(self):
        err = ZohoAPIError(message=PII_MESSAGE, status_code=400)
        _assert_no_pii(err.user_message, "ZohoAPIError")

    def test_zoho_api_error_zero_status(self):
        err = ZohoAPIError(message=PII_MESSAGE, status_code=0)
        _assert_no_pii(err.user_message, "ZohoAPIError(status=0)")
