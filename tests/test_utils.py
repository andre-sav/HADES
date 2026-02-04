"""
Tests for utility functions.

Run with: pytest tests/test_utils.py -v
"""

import pytest
from utils import (
    load_config,
    get_hard_filters,
    get_scoring_weights,
    get_signal_strength_score,
    get_freshness_multiplier,
    get_onsite_likelihood_score,
    get_employee_scale_score,
    get_proximity_score,
    get_budget_config,
    get_sic_codes,
    get_sic_codes_with_descriptions,
    get_employee_minimum,
    remove_phone_extension,
    normalize_phone,
    format_phone,
    VANILLASOFT_COLUMNS,
    SIC_CODE_DESCRIPTIONS,
)


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_config(self):
        """Test that config loads successfully."""
        config = load_config()
        assert config is not None
        assert "hard_filters" in config
        assert "scoring" in config
        assert "budget" in config

    def test_get_hard_filters(self):
        """Test hard filters retrieval."""
        filters = get_hard_filters()
        assert "employee_count" in filters
        assert "sic_codes" in filters
        assert filters["employee_count"]["minimum"] == 50

    def test_get_sic_codes(self):
        """Test SIC codes list."""
        codes = get_sic_codes()
        assert isinstance(codes, list)
        assert len(codes) == 22  # 22 target SIC codes from ZoomInfo filter
        assert "7011" in codes  # Hotels

    def test_get_employee_minimum(self):
        """Test employee minimum."""
        minimum = get_employee_minimum()
        assert minimum == 50

    def test_get_sic_codes_with_descriptions(self):
        """Test SIC codes return with descriptions."""
        result = get_sic_codes_with_descriptions()

        assert len(result) == 22
        assert all(isinstance(item, tuple) for item in result)
        assert all(len(item) == 2 for item in result)

        # Check first item has code and description
        code, desc = result[0]
        assert code.isdigit()
        assert len(desc) > 0

    def test_sic_code_descriptions_coverage(self):
        """Test that all configured SIC codes have descriptions."""
        codes = get_sic_codes()
        for code in codes:
            assert code in SIC_CODE_DESCRIPTIONS, f"Missing description for SIC code {code}"

    def test_sic_code_descriptions_content(self):
        """Test specific SIC code descriptions."""
        assert SIC_CODE_DESCRIPTIONS["7011"] == "Hotels and Motels"
        assert SIC_CODE_DESCRIPTIONS["8062"] == "General Medical and Surgical Hospitals"
        assert SIC_CODE_DESCRIPTIONS["8211"] == "Elementary and Secondary Schools"


class TestScoringConfig:
    """Tests for scoring configuration."""

    def test_get_intent_scoring_weights(self):
        """Test intent scoring weights."""
        weights = get_scoring_weights("intent")
        assert weights["signal_strength"] == 0.50
        assert weights["onsite_likelihood"] == 0.25
        assert weights["freshness"] == 0.25
        # Weights should sum to 1.0
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_get_geography_scoring_weights(self):
        """Test geography scoring weights."""
        weights = get_scoring_weights("geography")
        assert weights["proximity"] == 0.50
        assert weights["onsite_likelihood"] == 0.30
        assert weights["employee_scale"] == 0.20
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_get_signal_strength_score(self):
        """Test signal strength scores."""
        assert get_signal_strength_score("High") == 100
        assert get_signal_strength_score("Medium") == 70
        assert get_signal_strength_score("Low") == 40
        assert get_signal_strength_score("Unknown") == 0

    def test_get_freshness_multiplier_hot(self):
        """Test hot freshness tier (0-3 days)."""
        mult, label = get_freshness_multiplier(0)
        assert mult == 1.0
        assert label == "Hot"

        mult, label = get_freshness_multiplier(3)
        assert mult == 1.0

    def test_get_freshness_multiplier_warm(self):
        """Test warm freshness tier (4-7 days)."""
        mult, label = get_freshness_multiplier(4)
        assert mult == 0.7
        assert label == "Warm"

        mult, label = get_freshness_multiplier(7)
        assert mult == 0.7

    def test_get_freshness_multiplier_cooling(self):
        """Test cooling freshness tier (8-14 days)."""
        mult, label = get_freshness_multiplier(8)
        assert mult == 0.4
        assert label == "Cooling"

        mult, label = get_freshness_multiplier(14)
        assert mult == 0.4

    def test_get_freshness_multiplier_stale(self):
        """Test stale freshness tier (15+ days)."""
        mult, label = get_freshness_multiplier(15)
        assert mult == 0.0
        assert label == "Stale"

        mult, label = get_freshness_multiplier(100)
        assert mult == 0.0

    def test_get_onsite_likelihood_high(self):
        """Test high on-site likelihood SIC codes."""
        assert get_onsite_likelihood_score("7011") == 100  # Hotels
        assert get_onsite_likelihood_score("8062") == 100  # Hospitals
        assert get_onsite_likelihood_score("8211") == 100  # Schools

    def test_get_onsite_likelihood_medium(self):
        """Test medium on-site likelihood SIC codes."""
        assert get_onsite_likelihood_score("5511") == 70  # Auto Dealers
        assert get_onsite_likelihood_score("7033") == 70  # RV Parks

    def test_get_onsite_likelihood_low(self):
        """Test low on-site likelihood SIC codes."""
        assert get_onsite_likelihood_score("3999") == 40  # Manufacturing NEC
        assert get_onsite_likelihood_score("9229") == 40  # Public Safety

    def test_get_onsite_likelihood_unknown(self):
        """Test unknown SIC code defaults to low."""
        assert get_onsite_likelihood_score("9999") == 40

    def test_get_employee_scale_score(self):
        """Test employee scale scoring."""
        assert get_employee_scale_score(50) == 40
        assert get_employee_scale_score(100) == 40
        assert get_employee_scale_score(101) == 70
        assert get_employee_scale_score(500) == 70
        assert get_employee_scale_score(501) == 100
        assert get_employee_scale_score(10000) == 100

    def test_get_proximity_score(self):
        """Test proximity scoring."""
        assert get_proximity_score(1) == 100
        assert get_proximity_score(5) == 100
        assert get_proximity_score(6) == 85
        assert get_proximity_score(10) == 85
        assert get_proximity_score(11) == 70
        assert get_proximity_score(25) == 70
        assert get_proximity_score(26) == 50
        assert get_proximity_score(50) == 50
        assert get_proximity_score(51) == 30
        assert get_proximity_score(100) == 30


class TestBudgetConfig:
    """Tests for budget configuration."""

    def test_intent_budget(self):
        """Test intent workflow budget."""
        budget = get_budget_config("intent")
        assert budget["weekly_cap"] == 500
        assert 0.50 in budget["alerts"]
        assert 0.80 in budget["alerts"]
        assert 0.95 in budget["alerts"]

    def test_geography_budget(self):
        """Test geography workflow budget (unlimited)."""
        budget = get_budget_config("geography")
        assert budget["weekly_cap"] is None
        assert budget["alerts"] == []


class TestPhoneCleaning:
    """Tests for phone cleaning functions."""

    def test_remove_extension_x(self):
        """Test removing x extension."""
        assert remove_phone_extension("555-1234 x123") == "555-1234"
        assert remove_phone_extension("555-1234 X 456") == "555-1234"

    def test_remove_extension_ext(self):
        """Test removing ext extension."""
        assert remove_phone_extension("555-1234 ext123") == "555-1234"
        assert remove_phone_extension("555-1234 EXT. 789") == "555-1234"

    def test_remove_extension_hash(self):
        """Test removing # extension."""
        assert remove_phone_extension("555-1234 #100") == "555-1234"

    def test_remove_extension_none(self):
        """Test phone without extension."""
        assert remove_phone_extension("555-1234") == "555-1234"

    def test_remove_extension_empty(self):
        """Test empty phone."""
        assert remove_phone_extension("") == ""
        assert remove_phone_extension(None) == ""

    def test_normalize_phone(self):
        """Test phone normalization."""
        assert normalize_phone("(555) 123-4567") == "5551234567"
        assert normalize_phone("555.123.4567") == "5551234567"
        assert normalize_phone("555-123-4567 x100") == "5551234567"

    def test_normalize_phone_country_code(self):
        """Test stripping US country code."""
        assert normalize_phone("1-555-123-4567") == "5551234567"
        assert normalize_phone("+1 555 123 4567") == "5551234567"

    def test_format_phone(self):
        """Test phone formatting."""
        assert format_phone("5551234567") == "(555) 123-4567"
        assert format_phone("(555) 123-4567") == "(555) 123-4567"
        assert format_phone("555.123.4567") == "(555) 123-4567"


class TestVanillaSoftColumns:
    """Tests for VanillaSoft column mapping."""

    def test_columns_defined(self):
        """Test that all required columns are defined."""
        assert "List Source" in VANILLASOFT_COLUMNS
        assert "Company" in VANILLASOFT_COLUMNS
        assert "Lead Source" in VANILLASOFT_COLUMNS
        assert "Operator Name" in VANILLASOFT_COLUMNS
        assert "Team" in VANILLASOFT_COLUMNS

    def test_column_count(self):
        """Test expected number of columns."""
        assert len(VANILLASOFT_COLUMNS) == 31
