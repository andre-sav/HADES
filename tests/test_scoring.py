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
    score_intent_contacts,
    get_score_breakdown_intent_contact,
    get_priority_label,
    _calculate_age_days,
    _calculate_authority_score,
)


class TestIntentScoring:
    """Tests for intent lead scoring."""

    def test_high_signal_fresh_lead(self):
        """Test scoring for high signal, fresh lead."""
        today = date.today().isoformat()
        lead = {
            "intentStrength": "High",
            "intentDate": today,
            "sicCode": "7011",  # Hotels - 6.8% delivery rate
        }

        result = calculate_intent_score(lead)

        # 100*0.50 + 40*0.25 + 100*0.25 = 85
        assert result["score"] == 85
        assert result["signal_score"] == 100
        assert result["onsite_score"] == 40
        assert result["freshness_score"] == 100
        assert result["freshness_label"] == "Hot"
        assert result["excluded"] is False

    def test_medium_signal_warm_lead(self):
        """Test scoring for medium signal, warm lead."""
        warm_date = (date.today() - timedelta(days=5)).isoformat()
        lead = {
            "intentStrength": "Medium",
            "intentDate": warm_date,
            "sicCode": "5511",  # Auto Dealers - 7.9% delivery rate
        }

        result = calculate_intent_score(lead)

        # 70*0.50 + 43*0.25 + 70*0.25 = 63.25 -> 63
        assert result["score"] == 63
        assert result["signal_score"] == 70
        assert result["onsite_score"] == 43
        assert result["freshness_score"] == 70
        assert result["freshness_label"] == "Warm"
        assert result["excluded"] is False

    def test_low_signal_cooling_lead(self):
        """Test scoring for low signal, cooling lead."""
        cooling_date = (date.today() - timedelta(days=10)).isoformat()
        lead = {
            "intentStrength": "Low",
            "intentDate": cooling_date,
            "sicCode": "3999",  # Manufacturing NEC - 5.3% delivery rate
        }

        result = calculate_intent_score(lead)

        # 40*0.50 + 35*0.25 + 40*0.25 = 38.75 -> 39
        assert result["score"] == 39
        assert result["signal_score"] == 40
        assert result["onsite_score"] == 35
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
            "sicCode": "4581",          # 100 * 0.25 = 25 (best SIC)
        }

        result = calculate_intent_score(lead)

        # All maxed out: 50 + 25 + 25 = 100
        assert result["score"] == 100


    def test_intent_score_uses_numeric_signal_score(self):
        """Lead with numeric signalScore should use it instead of categorical bucket."""
        today = date.today().isoformat()
        lead_high = {
            "intentStrength": "High",
            "signalScore": 95,
            "intentDate": today,
            "sicCode": "7011",
        }
        lead_lower = {
            "intentStrength": "High",
            "signalScore": 80,
            "intentDate": today,
            "sicCode": "7011",
        }

        result_high = calculate_intent_score(lead_high)
        result_lower = calculate_intent_score(lead_lower)

        assert result_high["signal_score"] == 95
        assert result_lower["signal_score"] == 80
        assert result_high["score"] > result_lower["score"]

    def test_intent_score_falls_back_to_categorical(self):
        """Lead without signalScore should use intentStrength bucket."""
        today = date.today().isoformat()
        lead = {
            "intentStrength": "High",
            "intentDate": today,
            "sicCode": "7011",
        }

        result = calculate_intent_score(lead)

        assert result["signal_score"] == 100  # High maps to 100

    def test_intent_score_audience_bonus(self):
        """audienceStrength A should score higher than D."""
        today = date.today().isoformat()
        lead_a = {
            "intentStrength": "Medium",
            "intentDate": today,
            "sicCode": "7011",
            "audienceStrength": "A",
        }
        lead_d = {
            "intentStrength": "Medium",
            "intentDate": today,
            "sicCode": "7011",
            "audienceStrength": "D",
        }

        result_a = calculate_intent_score(lead_a)
        result_d = calculate_intent_score(lead_d)

        assert result_a["score"] > result_d["score"]

    def test_intent_score_employee_bonus(self):
        """Company with 1000 employees gets higher bonus than 50."""
        today = date.today().isoformat()
        lead_large = {
            "intentStrength": "Medium",
            "intentDate": today,
            "sicCode": "7011",
            "employees": 1000,
        }
        lead_small = {
            "intentStrength": "Medium",
            "intentDate": today,
            "sicCode": "7011",
            "employees": 50,
        }

        result_large = calculate_intent_score(lead_large)
        result_small = calculate_intent_score(lead_small)

        assert result_large["score"] > result_small["score"]


class TestGeographyScoring:
    """Tests for geography lead scoring."""

    def test_close_large_company(self):
        """Test scoring for close, large company."""
        lead = {
            "distance": 3.0,
            "sicCode": "7011",  # Hotels - 6.8% delivery rate
            "employees": 600,
        }

        result = calculate_geography_score(lead)

        # proximity=100*0.40 + onsite=40*0.25 + authority=40*0.15 + employee=20*0.20 = 60
        assert result["score"] == 60
        assert result["proximity_score"] == 100  # Within 5 miles
        assert result["onsite_score"] == 40
        assert result["authority_score"] == 40  # Default (no management level)
        assert result["employee_score"] == 20   # 500+ (worst bucket)

    def test_medium_distance_medium_company(self):
        """Test scoring for medium distance, medium company."""
        lead = {
            "distance": 15.0,
            "sicCode": "5511",  # Auto Dealers - 7.9% delivery rate
            "employees": 200,
        }

        result = calculate_geography_score(lead)

        # proximity=70*0.40 + onsite=43*0.25 + authority=40*0.15 + employee=80*0.20 = 60.75 -> 61
        assert result["score"] == 61
        assert result["proximity_score"] == 70  # 10-25 miles
        assert result["onsite_score"] == 43
        assert result["authority_score"] == 40  # Default (no management level)
        assert result["employee_score"] == 80  # 100-500

    def test_far_small_company(self):
        """Test scoring for far, small company."""
        lead = {
            "distance": 60.0,
            "sicCode": "3999",  # Manufacturing NEC - 5.3% delivery rate
            "employees": 75,
        }

        result = calculate_geography_score(lead)

        # proximity=30*0.40 + onsite=35*0.25 + authority=40*0.15 + employee=100*0.20 = 46.75 -> 47
        assert result["score"] == 47
        assert result["proximity_score"] == 30  # 50-100 miles
        assert result["onsite_score"] == 35
        assert result["authority_score"] == 40  # Default (no management level)
        assert result["employee_score"] == 100  # 50-100 (best bucket)

    def test_missing_distance(self):
        """Test handling of missing distance defaults to 15mi."""
        lead = {
            "sicCode": "7011",
            "employees": 100,
        }

        result = calculate_geography_score(lead)

        # Should use default proximity score (15mi → 70)
        assert result["proximity_score"] == 70
        # distance_miles should default to 15.0, not None (avoids "Distance: Nonemi" in export)
        assert result["distance_miles"] == 15.0

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
        assert "_authority_score" in scored[0]
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

    def test_us_format_with_time(self):
        """Test US format M/D/YYYY h:mm AM from legacy intent API."""
        today_str = date.today().strftime("%m/%d/%Y") + " 12:00 AM"
        assert _calculate_age_days(today_str) == 0

    def test_us_format_without_time(self):
        """Test US format M/D/YYYY without time."""
        yesterday = date.today() - timedelta(days=1)
        assert _calculate_age_days(yesterday.strftime("%m/%d/%Y")) == 1

    def test_us_format_single_digit_month(self):
        """Test US format with single-digit month/day."""
        today_str = date.today().strftime("%-m/%-d/%Y") + " 3:45 PM"
        assert _calculate_age_days(today_str) == 0


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


class TestIntentContactScoring:
    """Tests for intent contact scoring (contacts found at intent companies)."""

    def _make_contact(self, company_id="C1", accuracy=95, mobile=True, direct=False, phone=True):
        """Helper to create a test contact."""
        c = {
            "personId": f"P_{company_id}_{accuracy}",
            "companyId": company_id,
            "companyName": f"Company {company_id}",
            "firstName": "Test",
            "lastName": "Contact",
            "contactAccuracyScore": accuracy,
        }
        if mobile:
            c["mobilePhone"] = "(555) 111-2222"
        if direct:
            c["directPhone"] = "(555) 333-4444"
        if phone:
            c["phone"] = "(555) 555-6666"
        return c

    def _make_company_scores(self, company_ids_and_scores):
        """Helper: dict mapping company_id -> {"_score": x, "intentTopic": "Vending"}."""
        return {
            cid: {"_score": score, "intentTopic": "Vending"}
            for cid, score in company_ids_and_scores
        }

    def test_score_inherits_company_score(self):
        """Test that company intent score contributes 60% of final score."""
        contacts = [self._make_contact("C1", accuracy=95, mobile=True)]
        company_scores = self._make_company_scores([("C1", 100)])

        scored = score_intent_contacts(contacts, company_scores)

        assert len(scored) == 1
        # Company: 100 * 0.60 = 60
        # Authority: 40 * 0.15 = 6 (default, no management level)
        # Accuracy (95+): 100 * 0.15 = 15
        # Phone (mobile): 100 * 0.10 = 10
        # Total: 91
        assert scored[0]["_score"] == 91
        assert scored[0]["_company_intent_score"] == 100

    def test_score_accuracy_tiers(self):
        """Test accuracy score tiers: 95+=100, 85-94=70, <85=40."""
        company_scores = self._make_company_scores([("C1", 80)])

        # Accuracy 95+ -> 100
        contacts_high = [self._make_contact("C1", accuracy=97)]
        scored_high = score_intent_contacts(contacts_high, company_scores)
        assert scored_high[0]["_accuracy_score"] == 100

        # Accuracy 85-94 -> 70
        contacts_mid = [self._make_contact("C1", accuracy=90)]
        scored_mid = score_intent_contacts(contacts_mid, company_scores)
        assert scored_mid[0]["_accuracy_score"] == 70

        # Accuracy <85 -> 40
        contacts_low = [self._make_contact("C1", accuracy=75)]
        scored_low = score_intent_contacts(contacts_low, company_scores)
        assert scored_low[0]["_accuracy_score"] == 40

    def test_score_phone_bonus(self):
        """Test phone score: mobile=100, any phone=70, no phone=0."""
        company_scores = self._make_company_scores([("C1", 80)])

        # Has mobile -> 100
        contacts_mobile = [self._make_contact("C1", mobile=True, direct=False, phone=False)]
        scored_mobile = score_intent_contacts(contacts_mobile, company_scores)
        assert scored_mobile[0]["_phone_score"] == 100

        # Has only direct phone -> 70
        contacts_direct = [self._make_contact("C1", mobile=False, direct=True, phone=False)]
        scored_direct = score_intent_contacts(contacts_direct, company_scores)
        assert scored_direct[0]["_phone_score"] == 70

        # No phone at all -> 0
        contacts_none = [self._make_contact("C1", mobile=False, direct=False, phone=False)]
        scored_none = score_intent_contacts(contacts_none, company_scores)
        assert scored_none[0]["_phone_score"] == 0

    def test_score_sorting(self):
        """Test contacts are sorted by score descending."""
        company_scores = self._make_company_scores([("C1", 100), ("C2", 50), ("C3", 80)])

        contacts = [
            self._make_contact("C2", accuracy=95, mobile=True),  # Low company score
            self._make_contact("C1", accuracy=95, mobile=True),  # High company score
            self._make_contact("C3", accuracy=85, mobile=False, phone=True),  # Mid
        ]

        scored = score_intent_contacts(contacts, company_scores)

        assert scored[0]["companyId"] == "C1"  # Highest
        assert scored[-1]["companyId"] == "C2"  # Lowest
        assert scored[0]["_score"] >= scored[1]["_score"] >= scored[2]["_score"]

    def test_score_missing_company(self):
        """Test scoring when company not in company_scores dict."""
        contacts = [self._make_contact("UNKNOWN", accuracy=95, mobile=True)]
        company_scores = {}  # Empty

        scored = score_intent_contacts(contacts, company_scores)

        # Should use default company score of 50
        # 50*0.60 + 40*0.15 + 100*0.15 + 100*0.10 = 30+6+15+10 = 61
        assert scored[0]["_company_intent_score"] == 50
        assert scored[0]["_score"] == 61

    def test_score_breakdown_format(self):
        """Test human-readable score breakdown."""
        lead = {
            "_score": 85,
            "_company_intent_score": 90,
            "_authority_score": 75,
            "_accuracy_score": 100,
            "_phone_score": 70,
        }
        breakdown = get_score_breakdown_intent_contact(lead)
        assert "85" in breakdown
        assert "90" in breakdown
        assert "75" in breakdown
        assert "100" in breakdown
        assert "70" in breakdown

    def test_intent_topic_inherited(self):
        """Test that intent topic is carried from company scores to contacts."""
        contacts = [self._make_contact("C1")]
        company_scores = {"C1": {"_score": 80, "intentTopic": "Vending"}}

        scored = score_intent_contacts(contacts, company_scores)

        assert scored[0]["_intent_topic"] == "Vending"

    def test_authority_score_differentiates_contacts(self):
        """Test that contacts at same company score differently by title/level."""
        company_scores = self._make_company_scores([("C1", 80)])

        director = self._make_contact("C1", accuracy=95, mobile=True)
        director["managementLevel"] = "Director"
        director["jobTitle"] = "Director of Facilities"

        manager = self._make_contact("C1", accuracy=95, mobile=True)
        manager["managementLevel"] = "Manager"
        manager["jobTitle"] = "IT Manager"

        scored_d = score_intent_contacts([director], company_scores)
        scored_m = score_intent_contacts([manager], company_scores)

        # Director + "facilities" keyword should score higher than Manager
        assert scored_d[0]["_authority_score"] > scored_m[0]["_authority_score"]
        assert scored_d[0]["_score"] > scored_m[0]["_score"]


class TestAuthorityScore:
    """Tests for authority score calculation."""

    def test_c_level(self):
        """Test C-Level exec gets highest score."""
        contact = {"managementLevel": "C Level Exec", "jobTitle": "CEO"}
        assert _calculate_authority_score(contact) == 100

    def test_vp_level(self):
        """Test VP gets 85."""
        contact = {"managementLevel": "VP Level Exec", "jobTitle": "VP Operations"}
        # VP (85) + "operations" keyword (+10) = 95
        assert _calculate_authority_score(contact) == 95

    def test_director(self):
        """Test Director gets 75."""
        contact = {"managementLevel": "Director", "jobTitle": "Director of Marketing"}
        assert _calculate_authority_score(contact) == 75

    def test_manager(self):
        """Test Manager gets 60."""
        contact = {"managementLevel": "Manager", "jobTitle": "Project Manager"}
        assert _calculate_authority_score(contact) == 60

    def test_non_manager(self):
        """Test Non Manager gets 30."""
        contact = {"managementLevel": "Non Manager", "jobTitle": "Analyst"}
        assert _calculate_authority_score(contact) == 30

    def test_title_keyword_bonus(self):
        """Test title keyword adds +10 bonus."""
        contact = {"managementLevel": "Manager", "jobTitle": "Facilities Manager"}
        # Manager (60) + "facilities" keyword (+10) = 70
        assert _calculate_authority_score(contact) == 70

    def test_title_keyword_caps_at_100(self):
        """Test title keyword bonus caps at 100."""
        contact = {"managementLevel": "C Level Exec", "jobTitle": "Chief Facilities Officer"}
        # C-Level (100) + keyword bonus = still 100 (capped)
        assert _calculate_authority_score(contact) == 100

    def test_no_management_level(self):
        """Test missing management level uses default."""
        contact = {"jobTitle": "Office Worker"}
        assert _calculate_authority_score(contact) == 40  # default

    def test_vending_keyword(self):
        """Test 'vending' keyword in title gives bonus."""
        contact = {"managementLevel": "Manager", "jobTitle": "Vending Services Manager"}
        # Manager (60) + "vending" (+10) = 70
        assert _calculate_authority_score(contact) == 70

    def test_empty_contact(self):
        """Test empty contact gets default score."""
        assert _calculate_authority_score({}) == 40

    def test_geography_authority_in_score(self):
        """Test authority is included in geography scoring output."""
        lead = {
            "distance": 5.0,
            "sicCode": "7011",
            "employees": 100,
            "managementLevel": "Director",
            "jobTitle": "Director of Operations",
        }
        result = calculate_geography_score(lead)
        # Director (75) + "operations" (+10) = 85
        assert result["authority_score"] == 85
        assert "authority_score" in result


class TestMessyDataEdgeCases:
    """Edge case tests for messy real-world API data."""

    # --- Distance field edge cases ---

    def test_distance_as_string_with_units(self):
        """Distance like '5.0 miles' should not crash."""
        lead = {"distance": "5.0 miles", "sicCode": "7011", "employees": 100}
        result = calculate_geography_score(lead)
        assert result["distance_miles"] == 5.0
        assert result["proximity_score"] > 0

    def test_distance_as_string_number(self):
        """Distance as string '12.5' should parse correctly."""
        lead = {"distance": "12.5", "sicCode": "7011", "employees": 100}
        result = calculate_geography_score(lead)
        assert result["distance_miles"] == 12.5

    def test_distance_as_empty_string(self):
        """Empty string distance should use default."""
        lead = {"distance": "", "sicCode": "7011", "employees": 100}
        result = calculate_geography_score(lead)
        # Empty string is falsy, so distance is None path
        assert result["distance_miles"] == 15.0

    def test_distance_as_non_numeric_string(self):
        """Non-numeric distance like 'N/A' should use default."""
        lead = {"distance": "N/A", "sicCode": "7011", "employees": 100}
        result = calculate_geography_score(lead)
        assert result["distance_miles"] == 15.0

    def test_distance_negative(self):
        """Negative distance should still calculate (proximity handles it)."""
        lead = {"distance": -5.0, "sicCode": "7011", "employees": 100}
        result = calculate_geography_score(lead)
        assert "proximity_score" in result

    # --- Employee count edge cases ---

    def test_employee_count_with_plus(self):
        """Employee count '500+' should fall back to default."""
        lead = {"distance": 5.0, "sicCode": "7011", "employees": "500+"}
        result = calculate_geography_score(lead)
        # try/except catches ValueError, defaults to 50
        assert "employee_score" in result

    def test_employee_count_range_string(self):
        """Employee count '100-200' should fall back to default."""
        lead = {"distance": 5.0, "sicCode": "7011", "employees": "100-200"}
        result = calculate_geography_score(lead)
        assert "employee_score" in result

    def test_employee_count_html_entity(self):
        """Employee count with HTML entities should fall back."""
        lead = {"distance": 5.0, "sicCode": "7011", "employees": "&lt;50"}
        result = calculate_geography_score(lead)
        assert "employee_score" in result

    # --- Accuracy score edge cases ---

    def test_accuracy_as_percent_string(self):
        """Accuracy '95%' should parse to 95."""
        contact = {"contactAccuracyScore": "95%", "companyId": "1"}
        company_scores = {"1": {"_score": 80}}
        results = score_intent_contacts([contact], company_scores)
        assert len(results) == 1
        # 95% → 95 → high tier (100)
        assert results[0]["_accuracy_score"] == 100

    def test_accuracy_as_na_string(self):
        """Accuracy 'N/A' should default to 0 → low tier."""
        contact = {"contactAccuracyScore": "N/A", "companyId": "1"}
        company_scores = {"1": {"_score": 80}}
        results = score_intent_contacts([contact], company_scores)
        assert len(results) == 1
        assert results[0]["_accuracy_score"] == 40  # low tier

    def test_accuracy_none(self):
        """Accuracy None should default to 0."""
        contact = {"contactAccuracyScore": None, "companyId": "1"}
        company_scores = {"1": {"_score": 80}}
        results = score_intent_contacts([contact], company_scores)
        assert len(results) == 1

    # --- Date parsing edge cases ---

    def test_truncated_iso_date(self):
        """Truncated ISO date '2025-02-' should return 999."""
        assert _calculate_age_days("2025-02-") == 999

    def test_date_with_milliseconds(self):
        """ISO date with milliseconds should parse."""
        result = _calculate_age_days("2026-01-15T10:30:00.123Z")
        assert result >= 0

    def test_date_empty_string(self):
        """Empty string date returns 999."""
        assert _calculate_age_days("") == 999

    def test_date_whitespace_only(self):
        """Whitespace-only date returns 999."""
        assert _calculate_age_days("   ") == 999

    def test_future_date_clamped(self):
        """Future date returns 0 (not negative)."""
        assert _calculate_age_days("2099-01-01") == 0
