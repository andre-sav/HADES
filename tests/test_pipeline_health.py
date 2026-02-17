"""
Tests for Pipeline Health page helpers.

Run with: pytest tests/test_pipeline_health.py -v
"""

import sys
from unittest.mock import MagicMock
from datetime import datetime, timedelta

# Mock streamlit before importing
sys.modules["streamlit"] = MagicMock()
sys.modules["streamlit_shadcn_ui"] = MagicMock()

# Import after mocking
from pages import __path__ as pages_path  # noqa: F401

# We can't import the page directly (it runs on import), so test the logic directly


def time_ago(iso_str: str | None) -> str:
    """Copy of the helper for testing — same logic as in the page."""
    if not iso_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = now - dt
        minutes = diff.total_seconds() / 60
        if minutes < 1:
            return "Just now"
        if minutes < 60:
            return f"{int(minutes)}m ago"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)}h ago"
        days = hours / 24
        return f"{int(days)}d ago"
    except (ValueError, TypeError):
        return "Unknown"


class TestTimeAgo:
    """Tests for time_ago helper."""

    def test_none_input(self):
        assert time_ago(None) == "Never"

    def test_empty_string(self):
        assert time_ago("") == "Never"

    def test_just_now(self):
        now = datetime.now().isoformat()
        assert time_ago(now) == "Just now"

    def test_minutes_ago(self):
        dt = (datetime.now() - timedelta(minutes=15)).isoformat()
        result = time_ago(dt)
        assert "m ago" in result
        assert "15" in result

    def test_hours_ago(self):
        dt = (datetime.now() - timedelta(hours=3)).isoformat()
        result = time_ago(dt)
        assert "h ago" in result

    def test_days_ago(self):
        dt = (datetime.now() - timedelta(days=2)).isoformat()
        result = time_ago(dt)
        assert "d ago" in result

    def test_invalid_timestamp(self):
        assert time_ago("not-a-date") == "Unknown"
