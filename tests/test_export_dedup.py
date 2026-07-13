"""Tests for export_dedup.py — cross-session export deduplication."""

import sys
from unittest.mock import MagicMock

# Mock external dependencies before importing
sys.modules["streamlit"] = MagicMock()
sys.modules["libsql_experimental"] = MagicMock()

from export_dedup import (
    get_previously_exported,
    filter_previously_exported,
    apply_export_dedup,
)


class TestFilterByCompanyId:
    """Test filtering by exact company_id match."""

    def test_filter_by_company_id(self):
        contacts = [
            {"companyName": "Acme Corp", "companyId": "123"},
            {"companyName": "Beta Inc", "companyId": "456"},
            {"companyName": "Gamma LLC", "companyId": "789"},
        ]
        lookup = {
            "by_id": {
                "123": {"company_name": "Acme Corp", "exported_at": "2026-01-15", "workflow_type": "geography"},
            },
            "by_name": {
                "acme": {"company_name": "Acme Corp", "exported_at": "2026-01-15", "workflow_type": "geography"},
            },
        }

        new, filtered = filter_previously_exported(contacts, lookup)

        assert len(new) == 2
        assert len(filtered) == 1
        assert filtered[0]["companyName"] == "Acme Corp"
        assert filtered[0]["_previously_exported"] is True
        assert filtered[0]["_last_exported_at"] == "2026-01-15"

    def test_multiple_id_matches(self):
        contacts = [
            {"companyName": "Acme Corp", "companyId": "123"},
            {"companyName": "Beta Inc", "companyId": "456"},
        ]
        lookup = {
            "by_id": {
                "123": {"company_name": "Acme Corp", "exported_at": "2026-01-01", "workflow_type": "geography"},
                "456": {"company_name": "Beta Inc", "exported_at": "2026-01-02", "workflow_type": "intent"},
            },
            "by_name": {},
        }

        new, filtered = filter_previously_exported(contacts, lookup)

        assert len(new) == 0
        assert len(filtered) == 2


class TestFilterByCompanyNameFallback:
    """Test filtering by normalized company name when no company_id."""

    def test_filter_by_company_name_fallback(self):
        contacts = [
            {"companyName": "Acme Corp", "companyId": ""},
            {"companyName": "Beta Inc", "companyId": ""},
        ]
        lookup = {
            "by_id": {},
            "by_name": {
                "acme": {"company_name": "ACME CORP", "exported_at": "2026-01-10", "workflow_type": "geography"},
            },
        }

        new, filtered = filter_previously_exported(contacts, lookup)

        assert len(new) == 1
        assert len(filtered) == 1
        assert filtered[0]["companyName"] == "Acme Corp"

    def test_present_but_unknown_id_is_not_filtered_by_name(self):
        """R-03 (HADES-u1x): a contact with a valid companyId that is NOT in
        the exported set is PROOF the company was never exported — the name
        fallback must not fire. Same-name franchises (Planet Fitness Dallas
        vs Fort Worth) are different companies per ZoomInfo's own IDs."""
        contacts = [
            {"companyName": "Acme Corp", "companyId": "999"},  # never exported
        ]
        lookup = {
            "by_id": {"111": {"company_name": "Acme Corp", "exported_at": "2026-01-10", "workflow_type": "geography"}},
            "by_name": {
                "acme": {"company_name": "Acme Corp", "exported_at": "2026-01-10", "workflow_type": "geography"},
            },
        }

        new, filtered = filter_previously_exported(contacts, lookup)

        # The ID proves this is a different company — keep the lead.
        assert len(filtered) == 0
        assert len(new) == 1

    def test_name_fallback_still_fires_without_id(self):
        """Contacts with NO companyId still dedup by normalized name."""
        contacts = [{"companyName": "Acme Corp", "companyId": ""}]
        lookup = {
            "by_id": {},
            "by_name": {
                "acme": {"company_name": "Acme Corp", "exported_at": "2026-01-10", "workflow_type": "geography"},
            },
        }
        new, filtered = filter_previously_exported(contacts, lookup)
        assert len(filtered) == 1


class TestNoExportsReturnsAll:
    """Test that empty DB returns all contacts unchanged."""

    def test_no_exports_returns_all(self):
        contacts = [
            {"companyName": "Alpha", "companyId": "1"},
            {"companyName": "Beta", "companyId": "2"},
            {"companyName": "Gamma", "companyId": "3"},
        ]
        lookup = {"by_id": {}, "by_name": {}}

        new, filtered = filter_previously_exported(contacts, lookup)

        assert len(new) == 3
        assert len(filtered) == 0


class TestIncludeExportedFlag:
    """Test override that returns all contacts with metadata."""

    def test_include_exported_flag(self):
        mock_db = MagicMock()
        mock_db.get_vs_dedup_index.return_value = []
        mock_db.get_exported_company_ids.return_value = {
            "123": {"company_name": "Acme Corp", "exported_at": "2026-01-15", "workflow_type": "geography"},
        }

        contacts = [
            {"companyName": "Acme Corp", "companyId": "123"},
            {"companyName": "Beta Inc", "companyId": "456"},
        ]

        result = apply_export_dedup(contacts, mock_db, include_exported=True)

        assert len(result["contacts"]) == 2
        assert result["filtered_count"] == 1
        assert result["total_before_filter"] == 2

        # The exported contact should still be tagged
        exported_contact = [c for c in result["contacts"] if c.get("_previously_exported")]
        assert len(exported_contact) == 1
        assert exported_contact[0]["companyName"] == "Acme Corp"


class TestMixedMatches:
    """Test mix of ID match, name match, and new contacts."""

    def test_mixed_matches(self):
        contacts = [
            {"companyName": "Acme Corp", "companyId": "123"},   # ID match
            {"companyName": "BETA INCORPORATED", "companyId": ""},  # Name match
            {"companyName": "Gamma LLC", "companyId": "789"},   # New
        ]
        lookup = {
            "by_id": {
                "123": {"company_name": "Acme Corp", "exported_at": "2026-01-15", "workflow_type": "geography"},
            },
            "by_name": {
                "beta": {"company_name": "Beta Inc", "exported_at": "2026-01-10", "workflow_type": "intent"},
            },
        }

        new, filtered = filter_previously_exported(contacts, lookup)

        assert len(new) == 1
        assert new[0]["companyName"] == "Gamma LLC"
        assert len(filtered) == 2

        filtered_names = {c["companyName"] for c in filtered}
        assert "Acme Corp" in filtered_names
        assert "BETA INCORPORATED" in filtered_names


class TestEmptyContacts:
    """Test edge case with empty contacts list."""

    def test_empty_contacts(self):
        lookup = {
            "by_id": {"123": {"company_name": "X", "exported_at": "2026-01-01", "workflow_type": "geography"}},
            "by_name": {},
        }

        new, filtered = filter_previously_exported([], lookup)

        assert new == []
        assert filtered == []


class TestCompanyNameNormalization:
    """Test that normalization matches across variations."""

    def test_company_name_normalization(self):
        contacts = [
            {"companyName": "Acme Inc.", "companyId": ""},
            {"companyName": "ACME INCORPORATED", "companyId": ""},
            {"companyName": "acme", "companyId": ""},
        ]
        lookup = {
            "by_id": {},
            "by_name": {
                "acme": {"company_name": "Acme", "exported_at": "2026-01-01", "workflow_type": "geography"},
            },
        }

        new, filtered = filter_previously_exported(contacts, lookup)

        # All three should match "acme" after normalization
        assert len(filtered) == 3
        assert len(new) == 0


class TestGetPreviouslyExported:
    """Test the DB query wrapper."""

    def test_builds_lookup_dicts(self):
        mock_db = MagicMock()
        mock_db.get_vs_dedup_index.return_value = []
        mock_db.get_exported_company_ids.return_value = {
            "123": {"company_name": "Acme Corp", "exported_at": "2026-01-15", "workflow_type": "geography"},
            "456": {"company_name": "Beta Inc", "exported_at": "2026-01-10", "workflow_type": "intent"},
        }

        result = get_previously_exported(mock_db, days_back=180)

        assert "123" in result["by_id"]
        assert "456" in result["by_id"]
        assert "acme" in result["by_name"]
        assert "beta" in result["by_name"]

    def test_empty_db(self):
        mock_db = MagicMock()
        mock_db.get_vs_dedup_index.return_value = []
        mock_db.get_exported_company_ids.return_value = {}

        result = get_previously_exported(mock_db)

        assert result["by_id"] == {}
        assert result["by_name"] == {}


class TestApplyExportDedup:
    """Test the convenience wrapper."""

    def test_basic_filtering(self):
        mock_db = MagicMock()
        mock_db.get_vs_dedup_index.return_value = []
        mock_db.get_exported_company_ids.return_value = {
            "123": {"company_name": "Acme Corp", "exported_at": "2026-01-15", "workflow_type": "geography"},
        }

        contacts = [
            {"companyName": "Acme Corp", "companyId": "123"},
            {"companyName": "New Co", "companyId": "999"},
        ]

        result = apply_export_dedup(contacts, mock_db)

        assert len(result["contacts"]) == 1
        assert result["contacts"][0]["companyName"] == "New Co"
        assert result["filtered_count"] == 1
        assert result["total_before_filter"] == 2
        assert result["days_back"] == 365

    def test_custom_days_back(self):
        mock_db = MagicMock()
        mock_db.get_vs_dedup_index.return_value = []
        mock_db.get_exported_company_ids.return_value = {}

        apply_export_dedup([], mock_db, days_back=90)

        mock_db.get_exported_company_ids.assert_called_once_with(days_back=90, exclude_batch_id=None)

    def test_contacts_without_company_id(self):
        """Contacts with no companyId should use name fallback."""
        mock_db = MagicMock()
        mock_db.get_vs_dedup_index.return_value = []
        mock_db.get_exported_company_ids.return_value = {
            "123": {"company_name": "Acme Corp", "exported_at": "2026-01-15", "workflow_type": "geography"},
        }

        contacts = [
            {"companyName": "Acme Corp"},  # No companyId at all
        ]

        result = apply_export_dedup(contacts, mock_db)

        assert result["filtered_count"] == 1
        assert len(result["contacts"]) == 0


class TestNumericCompanyIdOverride:
    """R-15 (HADES-oq9): intent leads carry HASHED companyIds while lead_outcomes
    stores NUMERIC ones — the pipeline translates via the id-mapping cache and
    stamps _numeric_company_id, which must take precedence for ID matching."""

    def test_numeric_override_matches_by_id(self):
        """Hashed companyId misses, but the translated numeric id must match."""
        contacts = [{
            "companyName": "Acme Corp",
            "companyId": "hashed-abc123",
            "_numeric_company_id": "100",
        }]
        lookup = {
            "by_id": {"100": {"company_name": "Totally Different Stored Name",
                              "exported_at": "2026-06-01", "workflow_type": "intent"}},
            "by_name": {},  # name fallback intentionally cannot rescue this
        }
        new, filtered = filter_previously_exported(contacts, lookup)
        assert len(filtered) == 1
        assert filtered[0]["_previously_exported"] is True

    def test_without_override_falls_back_to_company_id(self):
        """No _numeric_company_id → existing companyId behavior unchanged."""
        contacts = [{"companyName": "Beta Inc", "companyId": "123"}]
        lookup = {
            "by_id": {"123": {"company_name": "Beta Inc",
                              "exported_at": "2026-06-01", "workflow_type": "geography"}},
            "by_name": {},
        }
        new, filtered = filter_previously_exported(contacts, lookup)
        assert len(filtered) == 1


class TestExcludeBatchIdPassThrough:
    """HADES-guz: apply_export_dedup forwards exclude_batch_id to the DB layer."""

    def test_pass_through(self):
        mock_db = MagicMock()
        mock_db.get_vs_dedup_index.return_value = []
        mock_db.get_exported_company_ids.return_value = {}
        apply_export_dedup([], mock_db, exclude_batch_id="B-123")
        _, kwargs = mock_db.get_exported_company_ids.call_args
        assert kwargs.get("exclude_batch_id") == "B-123"


class TestHashedIdNameFallback:
    """R-03 × R-15 interplay: an untranslated HASHED intent id lives in a
    different id-space than lead_outcomes' numeric ids, so it cannot prove
    'never exported' — the name fallback must still fire for those."""

    def test_untranslated_hashed_id_still_dedups_by_name(self):
        contacts = [{"companyName": "Acme Corp", "companyId": "a1b2c3hashed"}]
        lookup = {
            "by_id": {"100": {"company_name": "Acme Corp", "exported_at": "2026-06-01", "workflow_type": "geography"}},
            "by_name": {
                "acme": {"company_name": "Acme Corp", "exported_at": "2026-06-01", "workflow_type": "geography"},
            },
        }
        new, filtered = filter_previously_exported(contacts, lookup)
        assert len(filtered) == 1


def _vs_entry(**overrides):
    entry = {
        "company_name": "Woodmere Health Care Center",
        "company_norm": "woodmere health care center",
        "phone_business": "5163749300",
        "phone_mobile": "",
        "phone_home": "",
        "zip": "11598",
        "state": "NY",
        "lead_status": "Warm",
        "added_date": "2026-01-18 10:38:24",
    }
    entry.update(overrides)
    return entry


class TestVanillaSoftDedup:
    """HADES-dio: leads that exist in VanillaSoft from NON-HADES sources
    (other reps, pre-HADES records, VTI direct) must be visible to dedup.
    VS rows have no ZoomInfo companyId, so matching is name+ZIP or phone —
    never name alone (franchise safety, HADES-u1x)."""

    def _lookup(self, entries):
        vs_by_name, vs_by_phone = {}, {}
        for e in entries:
            if e["company_norm"]:
                vs_by_name.setdefault(e["company_norm"], []).append(e)
            for ph in (e["phone_business"], e["phone_mobile"], e["phone_home"]):
                if ph:
                    vs_by_phone.setdefault(ph, e)
        return {"by_id": {}, "by_name": {},
                "vs_by_name": vs_by_name, "vs_by_phone": vs_by_phone}

    def test_non_hades_vs_lead_filtered_by_name_and_zip(self):
        """Acceptance: a company that is an active VS lead created by another
        rep is filtered even though lead_outcomes has never seen it."""
        contacts = [{
            "companyName": "Woodmere Health Care Center, Inc.",
            "companyId": "555001",  # known-numeric, NOT in lead_outcomes
            "zip": "11598",
        }]
        new, filtered = filter_previously_exported(contacts, self._lookup([_vs_entry()]))
        assert len(filtered) == 1
        assert filtered[0]["_previously_exported"] is True
        assert filtered[0]["_dedup_source"] == "vanillasoft"
        assert filtered[0]["_vs_lead_status"] == "Warm"
        assert filtered[0]["_vs_added_date"] == "2026-01-18 10:38:24"
        assert filtered[0]["_last_exported_at"] == "2026-01-18 10:38:24"

    def test_same_name_different_zip_not_filtered(self):
        """Franchise safety: Planet Fitness Dallas must not be dropped
        because Planet Fitness Fort Worth is a VS lead."""
        contacts = [{
            "companyName": "Planet Fitness",
            "companyId": "555002",
            "zip": "75201",
        }]
        entry = _vs_entry(company_norm="planet fitness", zip="76102",
                          phone_business="8175550100")
        new, filtered = filter_previously_exported(contacts, self._lookup([entry]))
        assert len(new) == 1
        assert len(filtered) == 0

    def test_name_match_without_contact_zip_not_filtered(self):
        """No ZIP on the contact -> no corroboration -> keep it."""
        contacts = [{"companyName": "Woodmere Health Care Center", "companyId": "555003"}]
        new, filtered = filter_previously_exported(contacts, self._lookup([_vs_entry()]))
        assert len(new) == 1

    def test_phone_match_filters_regardless_of_name(self):
        """A shared phone is company-level proof even when names drifted."""
        contacts = [{
            "companyName": "Woodmere HCC",  # normalized name differs
            "companyId": "555004",
            "directPhone": "(516) 374-9300",
            "zip": "11550",
        }]
        new, filtered = filter_previously_exported(contacts, self._lookup([_vs_entry()]))
        assert len(filtered) == 1
        assert filtered[0]["_dedup_source"] == "vanillasoft"

    def test_lead_outcomes_id_match_wins_over_vs(self):
        """Existing HADES dedup fires first; VS is the third source."""
        lookup = self._lookup([_vs_entry()])
        lookup["by_id"] = {"123": {"company_name": "Woodmere Health Care Center",
                                   "exported_at": "2026-06-01",
                                   "workflow_type": "geography"}}
        contacts = [{"companyName": "Woodmere Health Care Center",
                     "companyId": "123", "zip": "11598"}]
        new, filtered = filter_previously_exported(contacts, lookup)
        assert len(filtered) == 1
        assert filtered[0]["_dedup_source"] == "lead_outcomes"
        assert filtered[0]["_last_exported_at"] == "2026-06-01"

    def test_zip_plus_four_contact_zip_still_matches(self):
        contacts = [{
            "companyName": "Woodmere Health Care Center",
            "companyId": "555005",
            "zipCode": "11598-1234",
        }]
        new, filtered = filter_previously_exported(contacts, self._lookup([_vs_entry()]))
        assert len(filtered) == 1

    def test_lookup_without_vs_keys_still_works(self):
        """Old-shape lookups (e.g. cached in session state) must not crash."""
        contacts = [{"companyName": "Anyone", "companyId": "1"}]
        new, filtered = filter_previously_exported(
            contacts, {"by_id": {}, "by_name": {}})
        assert len(new) == 1


class TestGetPreviouslyExportedVsSource:
    """get_previously_exported builds VS lookup indexes from the DB."""

    def test_vs_indexes_built(self):
        mock_db = MagicMock()
        mock_db.get_exported_company_ids.return_value = {}
        mock_db.get_vs_dedup_index.return_value = [
            _vs_entry(),
            _vs_entry(company_norm="beta", phone_business="",
                      phone_mobile="2145550199", zip="75201"),
        ]
        result = get_previously_exported(mock_db, days_back=180)
        assert "woodmere health care center" in result["vs_by_name"]
        assert "5163749300" in result["vs_by_phone"]
        assert "2145550199" in result["vs_by_phone"]
        mock_db.get_vs_dedup_index.assert_called_once_with(days_back=180)

    def test_db_without_vs_table_yields_empty_indexes(self):
        mock_db = MagicMock()
        mock_db.get_exported_company_ids.return_value = {}
        mock_db.get_vs_dedup_index.return_value = []
        result = get_previously_exported(mock_db)
        assert result["vs_by_name"] == {}
        assert result["vs_by_phone"] == {}

    def test_numeric_id_not_in_history_blocks_name_fallback(self):
        """Numeric id-space: present-but-unknown = proof of never-exported."""
        contacts = [{"companyName": "Acme Corp", "companyId": "222"}]
        lookup = {
            "by_id": {"111": {"company_name": "Acme Corp", "exported_at": "2026-06-01", "workflow_type": "geography"}},
            "by_name": {
                "acme": {"company_name": "Acme Corp", "exported_at": "2026-06-01", "workflow_type": "geography"},
            },
        }
        new, filtered = filter_previously_exported(contacts, lookup)
        assert len(filtered) == 0
