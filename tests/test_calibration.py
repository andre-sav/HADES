"""Tests for calibration.py - Outcome-driven scoring calibration engine."""

import sys
import os
import tempfile
from unittest.mock import MagicMock

# Mock Streamlit before importing modules
sys.modules["streamlit"] = MagicMock()
sys.modules["libsql_experimental"] = MagicMock()

import yaml
from calibration import (
    min_max_scale,
    compute_conversion_rates,
    compare_to_current,
    apply_calibration,
    SCORE_MIN,
    SCORE_MAX,
)


class TestMinMaxScale:
    """Tests for min_max_scale function."""

    def test_min_value(self):
        assert min_max_scale(0.0, 0.0, 1.0) == SCORE_MIN

    def test_max_value(self):
        assert min_max_scale(1.0, 0.0, 1.0) == SCORE_MAX

    def test_midpoint(self):
        result = min_max_scale(0.5, 0.0, 1.0)
        expected = round((SCORE_MIN + SCORE_MAX) / 2)
        assert result == expected

    def test_equal_min_max(self):
        """When all rates are equal, return midpoint."""
        result = min_max_scale(0.5, 0.5, 0.5)
        assert result == round((SCORE_MIN + SCORE_MAX) / 2)

    def test_clamps_to_range(self):
        """Should never exceed SCORE_MIN..SCORE_MAX."""
        result = min_max_scale(2.0, 0.0, 1.0)
        assert result <= SCORE_MAX
        result = min_max_scale(-1.0, 0.0, 1.0)
        assert result >= SCORE_MIN


class TestComputeConversionRates:
    """Tests for compute_conversion_rates."""

    def test_empty_data(self):
        mock_db = MagicMock()
        mock_db.get_all_outcomes_for_calibration.return_value = []

        result = compute_conversion_rates(mock_db)

        assert result["sic_scores"] == {}
        assert result["overall"]["total"] == 0

    def test_sic_rates(self):
        """Test per-SIC delivery rate computation."""
        mock_db = MagicMock()
        # 15 rows of SIC 7011 (3 deliveries = 20%)
        outcomes = []
        for i in range(15):
            outcomes.append({
                "company_name": f"Co {i}",
                "sic_code": "7011",
                "employee_count": 100,
                "zip_code": "75201",
                "state": "TX",
                "outcome": "delivery" if i < 3 else "no_delivery",
                "source": "historical",
            })
        mock_db.get_all_outcomes_for_calibration.return_value = outcomes

        result = compute_conversion_rates(mock_db)

        assert "7011" in result["sic_scores"]
        assert result["sic_scores"]["7011"]["delivered"] == 3
        assert result["sic_scores"]["7011"]["total"] == 15
        assert abs(result["sic_scores"]["7011"]["rate"] - 0.2) < 0.01

    def test_low_n_excluded(self):
        """SICs with < 10 records should be excluded."""
        mock_db = MagicMock()
        outcomes = [
            {"company_name": f"Co {i}", "sic_code": "9999",
             "employee_count": None, "zip_code": None, "state": None,
             "outcome": "delivery", "source": "historical"}
            for i in range(5)
        ]
        mock_db.get_all_outcomes_for_calibration.return_value = outcomes

        result = compute_conversion_rates(mock_db)

        assert "9999" not in result["sic_scores"]

    def test_employee_buckets(self):
        """Test employee bucket classification."""
        mock_db = MagicMock()
        outcomes = []
        # 20 small (50-100), 10 deliveries
        for i in range(20):
            outcomes.append({
                "company_name": f"Small {i}", "sic_code": None,
                "employee_count": 75, "zip_code": None, "state": None,
                "outcome": "delivery" if i < 10 else "no_delivery",
                "source": "historical",
            })
        # 20 medium (101-500), 2 deliveries
        for i in range(20):
            outcomes.append({
                "company_name": f"Med {i}", "sic_code": None,
                "employee_count": 300, "zip_code": None, "state": None,
                "outcome": "delivery" if i < 2 else "no_delivery",
                "source": "historical",
            })
        mock_db.get_all_outcomes_for_calibration.return_value = outcomes

        result = compute_conversion_rates(mock_db)

        assert result["employee_scores"]["50-100"]["delivered"] == 10
        assert result["employee_scores"]["101-500"]["delivered"] == 2
        assert result["employee_scores"]["50-100"]["score"] > result["employee_scores"]["101-500"]["score"]


class TestCompareToCurrentConfig:
    """Tests for compare_to_current."""

    def _make_config(self, tmp_path):
        config = {
            "onsite_likelihood": {
                "sic_scores": {"7011": 40, "8211": 37},
                "default": 40,
            },
            "employee_scale": [
                {"min": 50, "max": 100, "score": 100},
                {"min": 101, "max": 500, "score": 80},
                {"min": 501, "max": 999999, "score": 20},
            ],
        }
        config_path = os.path.join(tmp_path, "icp.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        return config_path

    def test_comparison_output(self, tmp_path):
        """Test that comparison produces correct deltas."""
        config_path = self._make_config(tmp_path)

        rates = {
            "sic_scores": {
                "7011": {"delivered": 10, "total": 100, "rate": 0.10, "score": 50},
            },
            "employee_scores": {
                "50-100": {"delivered": 5, "total": 50, "rate": 0.10, "score": 90},
                "101-500": {"delivered": 0, "total": 0, "rate": 0.0, "score": 20},
                "501+": {"delivered": 0, "total": 0, "rate": 0.0, "score": 20},
            },
            "overall": {"delivered": 15, "total": 150, "rate": 0.10},
        }

        comparisons = compare_to_current(rates, config_path)

        sic_comp = [c for c in comparisons if c["dimension"] == "sic" and c["key"] == "7011"][0]
        assert sic_comp["current"] == 40
        assert sic_comp["suggested"] == 50
        assert sic_comp["delta"] == 10
        assert sic_comp["confidence"] == "High"

    def test_confidence_levels(self, tmp_path):
        """Test confidence based on sample size."""
        config_path = self._make_config(tmp_path)

        rates = {
            "sic_scores": {
                "7011": {"delivered": 1, "total": 15, "rate": 0.067, "score": 30},
                "8211": {"delivered": 50, "total": 200, "rate": 0.25, "score": 80},
            },
            "employee_scores": {},
            "overall": {"delivered": 51, "total": 215, "rate": 0.24},
        }

        comparisons = compare_to_current(rates, config_path)

        low_conf = [c for c in comparisons if c["key"] == "7011"][0]
        high_conf = [c for c in comparisons if c["key"] == "8211"][0]

        assert low_conf["confidence"] == "Low"
        assert high_conf["confidence"] == "High"


class TestApplyCalibration:
    """Tests for apply_calibration."""

    def test_apply_sic_update(self, tmp_path):
        """Test applying a SIC score update to config."""
        config = {
            "onsite_likelihood": {
                "sic_scores": {"7011": 40},
                "default": 40,
            },
            "employee_scale": [
                {"min": 50, "max": 100, "score": 100},
            ],
        }
        config_path = os.path.join(tmp_path, "icp.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        updates = [{"dimension": "sic", "key": "7011", "suggested": 55}]
        apply_calibration(updates, config_path)

        with open(config_path) as f:
            result = yaml.safe_load(f)

        assert result["onsite_likelihood"]["sic_scores"]["7011"] == 55

    def test_apply_employee_update(self, tmp_path):
        """Test applying an employee score update."""
        config = {
            "onsite_likelihood": {"sic_scores": {}, "default": 40},
            "employee_scale": [
                {"min": 50, "max": 100, "score": 100},
                {"min": 101, "max": 500, "score": 80},
                {"min": 501, "max": 999999, "score": 20},
            ],
        }
        config_path = os.path.join(tmp_path, "icp.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        updates = [{"dimension": "employee", "key": "501+", "suggested": 45}]
        apply_calibration(updates, config_path)

        with open(config_path) as f:
            result = yaml.safe_load(f)

        assert result["employee_scale"][2]["score"] == 45

    def test_records_calibration_timestamp(self, tmp_path):
        """Test that calibration records timestamp in sync_metadata."""
        config = {"onsite_likelihood": {"sic_scores": {}, "default": 40}, "employee_scale": []}
        config_path = os.path.join(tmp_path, "icp.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        mock_db = MagicMock()
        apply_calibration([], config_path, db=mock_db)

        mock_db.execute_write.assert_called_once()
        call_args = mock_db.execute_write.call_args
        assert "last_calibration" in call_args[0][1]
