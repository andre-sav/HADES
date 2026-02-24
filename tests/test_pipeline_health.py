"""
Tests for Pipeline Health page helpers.

Run with: pytest tests/test_pipeline_health.py -v
"""

import sys
from unittest.mock import MagicMock
from datetime import datetime, timedelta

# Mock streamlit before importing
sys.modules["streamlit"] = MagicMock()

# Import the real time_ago from utils (tests the actual implementation)
from utils import time_ago


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
