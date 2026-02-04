"""
Tests for lead scoring engine.

Run with: pytest tests/test_scoring.py -v
"""

from datetime import date, timedelta
import pytest

from scoring import (
    calculate_intent_score,
    calculate_geography_score,
    score_intent_leads,
    score_geography_leads,
    get_priority_label,
    _calculate_age_days,
)


class TestIntentScoring:
    """Tests for intent lead scoring."""

    def test_high_signal_fresh_lead(self):
        """Test scoring for high signal, fresh lead."""
        today = date.today().isoformat()
        lead = {
            "intentStrength": "High",
            "intentDate": today,
            "sicCode": "7011",  # Hotels - high on-site
        }

        result = calculate_intent_score(lead)

        assert result["score"] >= 90  # Should be very high
        assert result["signal_score"] == 100
        assert result["onsite_score"] == 100
        assert result["freshness_score"] == 100
        assert result["freshness_label"] == "Hot"
        assert result["excluded"] is False

    def test_medium_signal_warm_lead(self):
        """Test scoring for medium signal, warm lead."""
        warm_date = (date.today() - timedelta(days=5)).isoformat()
        lead = {
            "intentStrength": "Medium",
            "intentDate": warm_date,
            "sicCode": "5511",  # Auto Dealers - medium on-site
        }

        result = calculate_intent_score(lead)

        assert 50 <= result["score"] <= 75
        assert result["signal_score"] == 70
        assert result["onsite_score"] == 70
        assert result["freshness_score"] == 70
        assert result["freshness_label"] == "Warm"
        assert result["excluded"] is False

    def test_low_signal_cooling_lead(self):
        """Test scoring for low signal, cooling lead."""
        cooling_date = (date.today() - timedelta(days=10)).isoformat()
        lead = {
            "intentStrength": "Low",
            "intentDate": cooling_date,
            "sicCode": "3999",  # Manufacturing NEC - low on-site
        }

        result = calculate_intent_score(lead)

        assert result["score"] <= 50
        assert result["signal_score"] == 40
        assert result["onsite_score"] == 40
        assert result["freshness_score"] == 40
        assert result["freshness_label"] == "Cooling"
        assert result["excluded"] is False

    def test_stale_lead_excluded(self):
        """Test that stale leads are excluded."""
        stale_date = (date.today() - timedelta(days=20)).isoformat()
        lead = {
            "intentStrength": "High",
            "intentDate": stale_date,
            "sicCode": "7011",
        }

        result = calculate_intent_score(lead)

        assert result["score"] == 0
        assert result["freshness_label"] == "Stale"
        assert result["excluded"] is True

    def test_missing_intent_date(self):
        """Test handling of missing intent date."""
        lead = {
            "intentStrength": "High",
            "sicCode": "7011",
        }

        result = calculate_intent_score(lead)

        # Missing date should be treated as stale
        assert result["excluded"] is True

    def test_score_weights_sum_correctly(self):
        """Test that score components are weighted correctly."""
        today = date.today().isoformat()
        lead = {
            "intentStrength": "High",  # 100 * 0.50 = 50
            "intentDate": today,        # 100 * 0.25 = 25
            "sicCode": "7011",          # 100 * 0.25 = 25
        }

        result = calculate_intent_score(lead)

        # All maxed out: 50 + 25 + 25 = 100
        assert result["score"] == 100


class TestGeographyScoring:
    """Tests for geography lead scoring."""

    def test_close_large_company(self):
        """Test scoring for close, large company."""
        lead = {
            "distance": 3.0,
            "sicCode": "7011",  # Hotels - high on-site
            "employees": 600,
        }

        result = calculate_geography_score(lead)

        assert result["score"] >= 90
        assert result["proximity_score"] == 100  # Within 5 miles
        assert result["onsite_score"] == 100
        assert result["employee_score"] == 100  # 500+

    def test_medium_distance_medium_company(self):
        """Test scoring for medium distance, medium company."""
        lead = {
            "distance": 15.0,
            "sicCode": "5511",  # Auto Dealers - medium on-site
            "employees": 200,
        }

        result = calculate_geography_score(lead)

        assert 50 <= result["score"] <= 80
        assert result["proximity_score"] == 70  # 10-25 miles
        assert result["onsite_score"] == 70
        assert result["employee_score"] == 70  # 100-500

    def test_far_small_company(self):
        """Test scoring for far, small company."""
        lead = {
            "distance": 60.0,
            "sicCode": "3999",  # Manufacturing NEC - low on-site
            "employees": 75,
        }

        result = calculate_geography_score(lead)

        assert result["score"] <= 50
        assert result["proximity_score"] == 30  # 50-100 miles
        assert result["onsite_score"] == 40
        assert result["employee_score"] == 40  # 50-100

    def test_missing_distance(self):
        """Test handling of missing distance."""
        lead = {
            "sicCode": "7011",
            "employees": 100,
        }

        result = calculate_geography_score(lead)

        # Should use default proximity score
        assert result["proximity_score"] == 70
        assert result["distance_miles"] is None

    def test_employee_count_variations(self):
        """Test different employee count field names."""
        lead1 = {"employees": 200, "sicCode": "7011", "distance": 5}
        lead2 = {"employeeCount": 200, "sicCode": "7011", "distance": 5}

        result1 = calculate_geography_score(lead1)
        result2 = calculate_geography_score(lead2)

        assert result1["employee_score"] == result2["employee_score"]


class TestScoreLeadsList:
    """Tests for batch scoring functions."""

    def test_score_intent_leads_filters_stale(self):
        """Test that stale leads are filtered out."""
        today = date.today().isoformat()
        stale = (date.today() - timedelta(days=20)).isoformat()

        leads = [
            {"intentStrength": "High", "intentDate": today, "sicCode": "7011"},
            {"intentStrength": "High", "intentDate": stale, "sicCode": "7011"},
            {"intentStrength": "Medium", "intentDate": today, "sicCode": "7011"},
        ]

        scored = score_intent_leads(leads)

        assert len(scored) == 2  # Stale lead filtered out

    def test_score_intent_leads_sorted_by_score(self):
        """Test that leads are sorted by score descending."""
        today = date.today().isoformat()
        warm = (date.today() - timedelta(days=5)).isoformat()

        leads = [
            {"intentStrength": "Low", "intentDate": warm, "sicCode": "7389"},
            {"intentStrength": "High", "intentDate": today, "sicCode": "7011"},
            {"intentStrength": "Medium", "intentDate": today, "sicCode": "4213"},
        ]

        scored = score_intent_leads(leads)

        assert scored[0]["_score"] >= scored[1]["_score"]
        assert scored[1]["_score"] >= scored[2]["_score"]

    def test_score_intent_leads_adds_fields(self):
        """Test that scoring adds expected fields."""
        today = date.today().isoformat()
        leads = [{"intentStrength": "High", "intentDate": today, "sicCode": "7011"}]

        scored = score_intent_leads(leads)

        assert "_score" in scored[0]
        assert "_signal_score" in scored[0]
        assert "_onsite_score" in scored[0]
        assert "_freshness_score" in scored[0]
        assert "_freshness_label" in scored[0]
        assert "_age_days" in scored[0]

    def test_score_geography_leads_sorted(self):
        """Test that geography leads are sorted by score."""
        leads = [
            {"distance": 50, "sicCode": "7389", "employees": 60},
            {"distance": 2, "sicCode": "7011", "employees": 600},
            {"distance": 20, "sicCode": "4213", "employees": 200},
        ]

        scored = score_geography_leads(leads)

        assert scored[0]["_score"] >= scored[1]["_score"]
        assert scored[1]["_score"] >= scored[2]["_score"]

    def test_score_geography_leads_adds_fields(self):
        """Test that geography scoring adds expected fields."""
        leads = [{"distance": 5, "sicCode": "7011", "employees": 100}]

        scored = score_geography_leads(leads)

        assert "_score" in scored[0]
        assert "_proximity_score" in scored[0]
        assert "_onsite_score" in scored[0]
        assert "_employee_score" in scored[0]
        assert "_distance_miles" in scored[0]


class TestAgeCalculation:
    """Tests for date age calculation."""

    def test_today(self):
        """Test age of today's date."""
        today = date.today().isoformat()
        assert _calculate_age_days(today) == 0

    def test_yesterday(self):
        """Test age of yesterday."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert _calculate_age_days(yesterday) == 1

    def test_week_ago(self):
        """Test age of a week ago."""
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        assert _calculate_age_days(week_ago) == 7

    def test_iso_with_time(self):
        """Test ISO format with time component."""
        today = date.today().isoformat() + "T12:00:00Z"
        assert _calculate_age_days(today) == 0

    def test_none_returns_max(self):
        """Test None returns max age."""
        assert _calculate_age_days(None) == 999

    def test_invalid_returns_max(self):
        """Test invalid date returns max age."""
        assert _calculate_age_days("not-a-date") == 999


class TestPriorityLabel:
    """Tests for priority label function."""

    def test_high_priority(self):
        """Test high priority label."""
        assert get_priority_label(80) == "High"
        assert get_priority_label(100) == "High"

    def test_medium_priority(self):
        """Test medium priority label."""
        assert get_priority_label(60) == "Medium"
        assert get_priority_label(79) == "Medium"

    def test_low_priority(self):
        """Test low priority label."""
        assert get_priority_label(40) == "Low"
        assert get_priority_label(59) == "Low"

    def test_very_low_priority(self):
        """Test very low priority label."""
        assert get_priority_label(39) == "Very Low"
        assert get_priority_label(0) == "Very Low"
