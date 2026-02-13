"""Tests for scripts/import_historical.py - Historical CSV import."""

import sys
from unittest.mock import MagicMock

# Mock Streamlit before importing modules
sys.modules["streamlit"] = MagicMock()
sys.modules["libsql_experimental"] = MagicMock()

from scripts.import_historical import normalize_state, normalize_zip


class TestNormalizeState:
    """Tests for state normalization."""

    def test_abbreviation_passthrough(self):
        assert normalize_state("TX") == "TX"

    def test_lowercase_abbreviation(self):
        assert normalize_state("tx") == "TX"

    def test_mixed_case_abbreviation(self):
        assert normalize_state("Ca") == "CA"

    def test_full_name(self):
        assert normalize_state("California") == "CA"

    def test_full_name_lowercase(self):
        assert normalize_state("kansas") == "KS"

    def test_full_name_with_spaces(self):
        assert normalize_state("New York") == "NY"

    def test_none(self):
        assert normalize_state(None) is None

    def test_empty(self):
        assert normalize_state("") is None

    def test_whitespace(self):
        assert normalize_state("  ") is None

    def test_unknown_returns_none(self):
        assert normalize_state("NotAState") is None


class TestNormalizeZip:
    """Tests for ZIP code normalization."""

    def test_five_digit(self):
        assert normalize_zip("75201") == "75201"

    def test_nine_digit(self):
        assert normalize_zip("75201-1234") == "75201"

    def test_four_digit_padded(self):
        assert normalize_zip("6101") == "06101"

    def test_none(self):
        assert normalize_zip(None) is None

    def test_empty(self):
        assert normalize_zip("") is None

    def test_invalid(self):
        assert normalize_zip("ABCDE") is None

    def test_whitespace_stripped(self):
        assert normalize_zip("  75201  ") == "75201"
