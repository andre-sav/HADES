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
