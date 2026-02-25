"""
Tests for title preference tracking.

Run with: pytest tests/test_title_prefs.py -v
"""

import sys
from unittest.mock import MagicMock

# Mock streamlit before importing
sys.modules["streamlit"] = MagicMock()

from db._title_prefs import TitlePrefsMixin, _normalize_title


class TestNormalizeTitle:
    """Tests for title normalization."""

    def test_basic(self):
        assert _normalize_title("Director of Operations") == "director of operations"

    def test_strips_whitespace(self):
        assert _normalize_title("  VP Sales  ") == "vp sales"

    def test_none(self):
        assert _normalize_title(None) == ""

    def test_empty(self):
        assert _normalize_title("") == ""

    def test_preserves_punctuation(self):
        assert _normalize_title("VP, Sales & Marketing") == "vp, sales & marketing"


class FakeDB(TitlePrefsMixin):
    """In-memory fake database for testing."""

    def __init__(self):
        self._data = {}  # title -> (selected_count, skipped_count, last_selected)

    def execute(self, query, params=None):
        if "SELECT title, selected_count, skipped_count FROM" in query:
            return [(t, d[0], d[1]) for t, d in self._data.items()]
        if "SELECT selected_count, skipped_count FROM" in query and params:
            title = params[0]
            if title in self._data:
                return [self._data[title][:2]]
            return []
        if "SELECT title, selected_count, skipped_count, last_selected" in query:
            return [(t, d[0], d[1], d[2]) for t, d in self._data.items()]
        return []

    def execute_write(self, query, params=None):
        title = params[0]
        if "ON CONFLICT" in query and "selected_count = selected_count + 1" in query:
            if title in self._data:
                old = self._data[title]
                self._data[title] = (old[0] + 1, old[1], "now")
            else:
                self._data[title] = (1, 0, "now")
        elif "ON CONFLICT" in query and "skipped_count = skipped_count + 1" in query:
            if title in self._data:
                old = self._data[title]
                self._data[title] = (old[0], old[1] + 1, old[2])
            else:
                self._data[title] = (0, 1, None)
        return 0


class TestTitlePrefs:
    """Tests for TitlePrefsMixin."""

    def test_record_and_get_preferences(self):
        db = FakeDB()
        db.record_title_selections(
            selected_titles=["Director of Operations", "Facilities Manager"],
            skipped_titles=["HR Coordinator", "Facilities Manager"],
        )
        prefs = db.get_title_preferences()
        # Director of Operations: 1 selected, 0 skipped → 1.0
        assert prefs["director of operations"] == 1.0
        # Facilities Manager: 1 selected, 1 skipped → 0.5
        assert prefs["facilities manager"] == 0.5
        # HR Coordinator: 0 selected, 1 skipped → 0.0
        assert prefs["hr coordinator"] == 0.0

    def test_accumulates_over_sessions(self):
        db = FakeDB()
        db.record_title_selections(["Facilities Manager"], [])
        db.record_title_selections(["Facilities Manager"], [])
        db.record_title_selections([], ["Facilities Manager"])
        prefs = db.get_title_preferences()
        # 2 selected, 1 skipped → 2/3 ≈ 0.667
        assert abs(prefs["facilities manager"] - 2 / 3) < 0.01

    def test_single_preference(self):
        db = FakeDB()
        db.record_title_selections(["VP Operations"], [])
        score = db.get_title_preference("VP Operations")
        assert score == 1.0

    def test_unknown_title(self):
        db = FakeDB()
        assert db.get_title_preference("Never Seen Title") is None

    def test_empty_titles_skipped(self):
        db = FakeDB()
        db.record_title_selections(["", None], [None, ""])
        prefs = db.get_title_preferences()
        assert len(prefs) == 0

    def test_get_stats(self):
        db = FakeDB()
        db.record_title_selections(["Director"], ["Manager"])
        stats = db.get_title_stats()
        assert len(stats) == 2
        director = next(s for s in stats if s["title"] == "director")
        assert director["selected_count"] == 1
        assert director["preference"] == 1.0
