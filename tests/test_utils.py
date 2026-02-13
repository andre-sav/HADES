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
        assert len(codes) == 25  # 22 original + 3 from HLM delivery data
        assert "7011" in codes  # Hotels
        assert "4213" in codes  # Trucking (new)
        assert "4581" in codes  # Aviation (new)
        assert "4731" in codes  # Freight (new)

    def test_get_employee_minimum(self):
        """Test employee minimum."""
        minimum = get_employee_minimum()
        assert minimum == 50

    def test_get_sic_codes_with_descriptions(self):
        """Test SIC codes return with descriptions."""
        result = get_sic_codes_with_descriptions()

        assert len(result) == 25
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
        assert weights["proximity"] == 0.40
        assert weights["onsite_likelihood"] == 0.25
        assert weights["authority"] == 0.15
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

    def test_get_onsite_likelihood_empirical_scores(self):
        """Test per-SIC scores from HLM delivery data calibration."""
        assert get_onsite_likelihood_score("4581") == 100  # Aviation (27.3% rate)
        assert get_onsite_likelihood_score("4731") == 79   # Freight (20.0% rate)
        assert get_onsite_likelihood_score("4213") == 76   # Trucking (19.0% rate)
        assert get_onsite_likelihood_score("8361") == 71   # Residential Care (17.4%)
        assert get_onsite_likelihood_score("8059") == 56   # Nursing Care (12.3%)
        assert get_onsite_likelihood_score("8331") == 51   # Job Training (10.4%)
        assert get_onsite_likelihood_score("7991") == 50   # Fitness (10.3%)
        assert get_onsite_likelihood_score("3599") == 47   # Industrial Machinery (9.1%)
        assert get_onsite_likelihood_score("5511") == 43   # Auto Dealers (7.9%)
        assert get_onsite_likelihood_score("8051") == 42   # Skilled Nursing (7.3%)
        assert get_onsite_likelihood_score("8221") == 41   # Colleges (7.1%)
        assert get_onsite_likelihood_score("7011") == 40   # Hotels (6.8%)
        assert get_onsite_likelihood_score("8211") == 37   # Schools (5.9%)
        assert get_onsite_likelihood_score("3999") == 35   # Manufacturing NEC (5.3%)
        assert get_onsite_likelihood_score("8062") == 33   # Hospitals (4.5%)
        assert get_onsite_likelihood_score("8322") == 31   # Social Services (3.8%)

    def test_get_onsite_likelihood_default(self):
        """Test SICs without sufficient data use default score."""
        assert get_onsite_likelihood_score("9999") == 40  # Unknown SIC
        assert get_onsite_likelihood_score("3531") == 40  # ICP but no data
        assert get_onsite_likelihood_score("9229") == 40  # ICP but no data

    def test_get_employee_scale_score(self):
        """Test employee scale scoring (inverted — small companies convert best)."""
        assert get_employee_scale_score(50) == 100   # Small: 10.0% delivery rate
        assert get_employee_scale_score(100) == 100
        assert get_employee_scale_score(101) == 80    # Medium: 7.7% delivery rate
        assert get_employee_scale_score(500) == 80
        assert get_employee_scale_score(501) == 20    # Large: 1.0% delivery rate
        assert get_employee_scale_score(10000) == 20

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
