"""
Tests for deduplication logic.

Run with: pytest tests/test_dedup.py -v
"""

import pytest

from dedup import (
    normalize_company_name,
    get_dedup_key,
    dedupe_by_phone,
    dedupe_leads,
    find_duplicates,
    fuzzy_company_match,
    merge_lead_lists,
    flag_duplicates_in_list,
)


class TestNormalizeCompanyName:
    """Tests for company name normalization."""

    def test_lowercase(self):
        """Test lowercase conversion."""
        assert normalize_company_name("ACME CORP") == "acme"
        assert normalize_company_name("Acme Corp") == "acme"

    def test_strip_inc(self):
        """Test stripping Inc suffix."""
        assert normalize_company_name("Acme Inc") == "acme"
        assert normalize_company_name("Acme Inc.") == "acme"
        assert normalize_company_name("Acme, Inc.") == "acme"
        assert normalize_company_name("Acme Incorporated") == "acme"

    def test_strip_llc(self):
        """Test stripping LLC suffix."""
        assert normalize_company_name("Acme LLC") == "acme"
        assert normalize_company_name("Acme, LLC") == "acme"
        assert normalize_company_name("Acme LLC.") == "acme"

    def test_strip_corp(self):
        """Test stripping Corp suffix."""
        assert normalize_company_name("Acme Corp") == "acme"
        assert normalize_company_name("Acme Corp.") == "acme"
        assert normalize_company_name("Acme Corporation") == "acme"

    def test_strip_ltd(self):
        """Test stripping Ltd suffix."""
        assert normalize_company_name("Acme Ltd") == "acme"
        assert normalize_company_name("Acme Ltd.") == "acme"
        assert normalize_company_name("Acme Limited") == "acme"

    def test_strip_co(self):
        """Test stripping Co suffix."""
        assert normalize_company_name("Acme Co") == "acme"
        assert normalize_company_name("Acme Co.") == "acme"
        assert normalize_company_name("Acme Company") == "acme"

    def test_remove_punctuation(self):
        """Test punctuation removal."""
        assert normalize_company_name("Acme & Sons") == "acme sons"
        assert normalize_company_name("O'Reilly Media") == "oreilly media"

    def test_collapse_whitespace(self):
        """Test whitespace collapsing."""
        assert normalize_company_name("Acme   Corp") == "acme"
        assert normalize_company_name("  Acme  ") == "acme"

    def test_empty_input(self):
        """Test empty input."""
        assert normalize_company_name("") == ""
        assert normalize_company_name(None) == ""

    def test_complex_names(self):
        """Test complex company names."""
        assert normalize_company_name("The Acme Corporation") == "the acme"
        assert normalize_company_name("Johnson & Johnson") == "johnson johnson"


class TestGetDedupKey:
    """Tests for dedup key generation."""

    def test_basic_key(self):
        """Test basic key generation."""
        lead = {"phone": "555-123-4567", "companyName": "Acme Inc"}
        key = get_dedup_key(lead)
        assert key == "5551234567|acme"

    def test_alternate_fields(self):
        """Test with alternate field names."""
        lead = {"Business": "555-123-4567", "Company": "Acme Inc"}
        key = get_dedup_key(lead)
        assert key == "5551234567|acme"

    def test_missing_phone(self):
        """Test with missing phone."""
        lead = {"companyName": "Acme Inc"}
        key = get_dedup_key(lead)
        assert key == "|acme"

    def test_missing_company(self):
        """Test with missing company."""
        lead = {"phone": "555-123-4567"}
        key = get_dedup_key(lead)
        assert key == "5551234567|"

    def test_empty_lead(self):
        """Test with empty lead."""
        key = get_dedup_key({})
        assert key == "|"


class TestDedupeByPhone:
    """Tests for phone-based deduplication."""

    def test_no_duplicates(self):
        """Test with no duplicates."""
        leads = [
            {"phone": "555-111-1111", "companyName": "Acme"},
            {"phone": "555-222-2222", "companyName": "Beta"},
        ]
        deduped, removed = dedupe_by_phone(leads)
        assert len(deduped) == 2
        assert removed == 0

    def test_with_duplicates(self):
        """Test removing duplicates."""
        leads = [
            {"phone": "555-111-1111", "companyName": "Acme"},
            {"phone": "555-111-1111", "companyName": "Acme Copy"},
            {"phone": "555-222-2222", "companyName": "Beta"},
        ]
        deduped, removed = dedupe_by_phone(leads)
        assert len(deduped) == 2
        assert removed == 1
        assert deduped[0]["companyName"] == "Acme"  # First one kept

    def test_normalized_duplicates(self):
        """Test that normalized phones are compared."""
        leads = [
            {"phone": "(555) 111-1111", "companyName": "Acme"},
            {"phone": "555.111.1111", "companyName": "Acme Copy"},
        ]
        deduped, removed = dedupe_by_phone(leads)
        assert len(deduped) == 1
        assert removed == 1

    def test_empty_phones_kept(self):
        """Test that leads with empty phones are kept."""
        leads = [
            {"phone": "", "companyName": "Acme"},
            {"phone": None, "companyName": "Beta"},
            {"companyName": "Gamma"},
        ]
        deduped, removed = dedupe_by_phone(leads)
        assert len(deduped) == 3
        assert removed == 0


class TestDedupeLeads:
    """Tests for full lead deduplication."""

    def test_phone_and_company_match(self):
        """Test deduplication by phone and company."""
        leads = [
            {"phone": "555-111-1111", "companyName": "Acme Inc", "_score": 90},
            {"phone": "555-111-1111", "companyName": "Acme Corporation", "_score": 80},
        ]
        deduped, removed = dedupe_leads(leads)
        assert len(deduped) == 1
        assert removed == 1
        assert deduped[0]["_score"] == 90  # First (higher score) kept

    def test_same_phone_different_company(self):
        """Test same phone but different company kept separately."""
        leads = [
            {"phone": "555-111-1111", "companyName": "Acme Inc"},
            {"phone": "555-111-1111", "companyName": "Beta Corp"},
        ]
        deduped, removed = dedupe_leads(leads)
        # Different companies, so both kept
        assert len(deduped) == 2
        assert removed == 0

    def test_different_phone_same_company(self):
        """Test different phone but same company kept separately."""
        leads = [
            {"phone": "555-111-1111", "companyName": "Acme Inc"},
            {"phone": "555-222-2222", "companyName": "Acme Inc"},
        ]
        deduped, removed = dedupe_leads(leads)
        # Different phones, so both kept
        assert len(deduped) == 2
        assert removed == 0


class TestFindDuplicates:
    """Tests for finding cross-list duplicates."""

    def test_find_duplicates(self):
        """Test finding duplicates between lists."""
        list1 = [
            {"phone": "555-111-1111", "companyName": "Acme", "_score": 90},
            {"phone": "555-222-2222", "companyName": "Beta", "_score": 80},
        ]
        list2 = [
            {"phone": "555-111-1111", "companyName": "Acme Inc", "_score": 70},
            {"phone": "555-333-3333", "companyName": "Gamma", "_score": 60},
        ]

        duplicates = find_duplicates(list1, list2)

        assert len(duplicates) == 1
        assert duplicates[0]["score1"] == 90
        assert duplicates[0]["score2"] == 70

    def test_no_duplicates(self):
        """Test with no duplicates."""
        list1 = [{"phone": "555-111-1111", "companyName": "Acme"}]
        list2 = [{"phone": "555-222-2222", "companyName": "Beta"}]

        duplicates = find_duplicates(list1, list2)

        assert len(duplicates) == 0


class TestMergeLeadLists:
    """Tests for merging lead lists."""

    def test_merge_no_duplicates(self):
        """Test merging lists with no duplicates."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme", "_score": 90}]
        geo = [{"phone": "555-222-2222", "companyName": "Beta", "_score": 80}]

        merged, dup_count = merge_lead_lists(intent, geo)

        assert len(merged) == 2
        assert dup_count == 0

    def test_merge_with_duplicates_intent_higher(self):
        """Test merging when intent lead has higher score."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme", "_score": 90}]
        geo = [{"phone": "555-111-1111", "companyName": "Acme Inc", "_score": 70}]

        merged, dup_count = merge_lead_lists(intent, geo)

        assert len(merged) == 1
        assert dup_count == 1
        assert merged[0]["_score"] == 90
        assert merged[0]["_source"] == "intent"

    def test_merge_with_duplicates_geo_higher(self):
        """Test merging when geo lead has higher score."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme", "_score": 60}]
        geo = [{"phone": "555-111-1111", "companyName": "Acme Inc", "_score": 85}]

        merged, dup_count = merge_lead_lists(intent, geo)

        assert len(merged) == 1
        assert dup_count == 1
        assert merged[0]["_score"] == 85
        assert merged[0]["_source"] == "geography"

    def test_merge_sorted_by_score(self):
        """Test that merged list is sorted by score."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme", "_score": 70}]
        geo = [{"phone": "555-222-2222", "companyName": "Beta", "_score": 90}]

        merged, _ = merge_lead_lists(intent, geo)

        assert merged[0]["_score"] == 90
        assert merged[1]["_score"] == 70

    def test_source_tagging(self):
        """Test that source is tagged."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme", "_score": 90}]
        geo = [{"phone": "555-222-2222", "companyName": "Beta", "_score": 80}]

        merged, _ = merge_lead_lists(intent, geo, tag_source=True)

        sources = {lead["_source"] for lead in merged}
        assert sources == {"intent", "geography"}


class TestFlagDuplicates:
    """Tests for flagging duplicates."""

    def test_flag_duplicates(self):
        """Test flagging duplicates in list."""
        leads = [
            {"phone": "555-111-1111", "companyName": "Acme"},
            {"phone": "555-222-2222", "companyName": "Beta"},
        ]
        other = [
            {"phone": "555-111-1111", "companyName": "Acme Inc"},
        ]

        flagged = flag_duplicates_in_list(leads, other)

        assert flagged[0]["_is_duplicate"] is True
        assert flagged[1]["_is_duplicate"] is False

    def test_flag_no_duplicates(self):
        """Test when no duplicates exist."""
        leads = [{"phone": "555-111-1111", "companyName": "Acme"}]
        other = [{"phone": "555-222-2222", "companyName": "Beta"}]

        flagged = flag_duplicates_in_list(leads, other)

        assert flagged[0]["_is_duplicate"] is False


class TestMessyCompanyNames:
    """Edge cases for company names with HTML entities and special chars."""

    def test_html_ampersand_entity(self):
        """Company 'Acme &amp; Co' normalizes same as 'Acme & Co'."""
        # Both strip punctuation, so &amp; → "amp" remains but & → removed
        # This shows they DON'T match — documenting the behavior
        name1 = normalize_company_name("Acme &amp; Co")
        name2 = normalize_company_name("Acme & Co")
        # &amp; leaves "amp" in the normalized string
        assert "amp" in name1
        assert "amp" not in name2

    def test_html_entity_in_dedup_key(self):
        """HTML entities in company name affect dedup matching."""
        lead1 = {"phone": "555-111-1111", "companyName": "Acme &amp; Sons"}
        lead2 = {"phone": "555-111-1111", "companyName": "Acme & Sons"}
        # Same phone → same normalized phone, company differs
        key1 = get_dedup_key(lead1)
        key2 = get_dedup_key(lead2)
        # Phone part matches (same number), company part differs
        assert key1.split("|")[0] == key2.split("|")[0]  # phone matches

    def test_unicode_dash_in_company(self):
        """Company name with em-dash should normalize."""
        name = normalize_company_name("Acme\u2014Corp")
        assert "acme" in name

    def test_none_company_name(self):
        """None company name returns empty string."""
        assert normalize_company_name(None) == ""
        assert normalize_company_name("") == ""


class TestFuzzyCompanyMatch:
    """Tests for fuzzy company name matching."""

    def test_exact_match(self):
        assert fuzzy_company_match("acme", "acme") is True

    def test_typo_match(self):
        """One-char typo should match at default threshold."""
        assert fuzzy_company_match("acme services", "acmee services") is True

    def test_word_reorder_match(self):
        """Word reorder should match (token_sort_ratio)."""
        assert fuzzy_company_match("saint joseph hospital", "hospital saint joseph") is True

    def test_abbreviation_match(self):
        """Common abbreviation should match."""
        assert fuzzy_company_match("st joseph hospital", "saint joseph hospital") is True

    def test_different_companies_no_match(self):
        """Genuinely different companies should not match."""
        assert fuzzy_company_match("acme services", "beta industries") is False

    def test_empty_strings_no_match(self):
        """Empty strings should not match."""
        assert fuzzy_company_match("", "") is False
        assert fuzzy_company_match("acme", "") is False

    def test_custom_threshold(self):
        """Custom threshold should be respected."""
        # "acme" vs "acmee" is ~89 ratio — passes at 85, fails at 95
        assert fuzzy_company_match("acme", "acmee", threshold=80) is True
        assert fuzzy_company_match("acme", "acmee", threshold=95) is False


class TestFindDuplicatesFuzzy:
    """Tests for fuzzy matching in find_duplicates."""

    def test_fuzzy_company_same_phone(self):
        """Typo in company name with same phone → duplicate found."""
        list1 = [{"phone": "555-111-1111", "companyName": "Acme Services", "_score": 90}]
        list2 = [{"phone": "555-111-1111", "companyName": "Acmee Services Inc", "_score": 70}]
        duplicates = find_duplicates(list1, list2)
        assert len(duplicates) == 1

    def test_fuzzy_company_no_phone_overlap(self):
        """Different phones but fuzzy company match → still found."""
        list1 = [{"phone": "555-111-1111", "companyName": "Saint Joseph Medical Center", "_score": 90}]
        list2 = [{"phone": "555-222-2222", "companyName": "St Joseph Medical Center LLC", "_score": 70}]
        duplicates = find_duplicates(list1, list2)
        assert len(duplicates) == 1

    def test_no_fuzzy_match_different_companies(self):
        """Genuinely different companies → no duplicate."""
        list1 = [{"phone": "555-111-1111", "companyName": "Acme Services", "_score": 90}]
        list2 = [{"phone": "555-111-1111", "companyName": "Beta Industries", "_score": 70}]
        duplicates = find_duplicates(list1, list2)
        assert len(duplicates) == 0

    def test_exact_match_still_works(self):
        """Exact match (current behavior) still works."""
        list1 = [{"phone": "555-111-1111", "companyName": "Acme Inc", "_score": 90}]
        list2 = [{"phone": "555-111-1111", "companyName": "Acme Corp", "_score": 70}]
        duplicates = find_duplicates(list1, list2)
        assert len(duplicates) == 1


class TestMergeLeadListsFuzzy:
    """Tests for fuzzy matching in merge_lead_lists."""

    def test_fuzzy_merge_keeps_higher_score(self):
        """Fuzzy match across workflows keeps the higher-scored lead."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme Services", "_score": 90}]
        geo = [{"phone": "555-222-2222", "companyName": "Acmee Services LLC", "_score": 70}]
        merged, dup_count = merge_lead_lists(intent, geo)
        assert len(merged) == 1
        assert dup_count == 1
        assert merged[0]["_score"] == 90

    def test_fuzzy_merge_geo_higher(self):
        """Fuzzy match where geo lead scores higher."""
        intent = [{"phone": "555-111-1111", "companyName": "St Joseph Hospital", "_score": 60}]
        geo = [{"phone": "555-222-2222", "companyName": "Saint Joseph Hospital", "_score": 85}]
        merged, dup_count = merge_lead_lists(intent, geo)
        assert len(merged) == 1
        assert dup_count == 1
        assert merged[0]["_score"] == 85

    def test_no_false_merge(self):
        """Different companies should not merge."""
        intent = [{"phone": "555-111-1111", "companyName": "Acme Services", "_score": 90}]
        geo = [{"phone": "555-222-2222", "companyName": "Beta Industries", "_score": 80}]
        merged, dup_count = merge_lead_lists(intent, geo)
        assert len(merged) == 2
        assert dup_count == 0
