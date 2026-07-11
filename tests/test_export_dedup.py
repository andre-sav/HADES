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

    def test_no_fallback_when_id_matches(self):
        """company_id match takes priority; name fallback only when no ID."""
        contacts = [
            {"companyName": "Acme Corp", "companyId": "999"},  # ID not in lookup
        ]
        lookup = {
            "by_id": {},
            "by_name": {
                "acme": {"company_name": "Acme Corp", "exported_at": "2026-01-10", "workflow_type": "geography"},
            },
        }

        new, filtered = filter_previously_exported(contacts, lookup)

        # Falls through to name match since ID "999" not found
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
        mock_db.get_exported_company_ids.return_value = {}

        result = get_previously_exported(mock_db)

        assert result["by_id"] == {}
        assert result["by_name"] == {}


class TestApplyExportDedup:
    """Test the convenience wrapper."""

    def test_basic_filtering(self):
        mock_db = MagicMock()
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
        mock_db.get_exported_company_ids.return_value = {}

        apply_export_dedup([], mock_db, days_back=90)

        mock_db.get_exported_company_ids.assert_called_once_with(days_back=90, exclude_batch_id=None)

    def test_contacts_without_company_id(self):
        """Contacts with no companyId should use name fallback."""
        mock_db = MagicMock()
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
        mock_db.get_exported_company_ids.return_value = {}
        apply_export_dedup([], mock_db, exclude_batch_id="B-123")
        _, kwargs = mock_db.get_exported_company_ids.call_args
        assert kwargs.get("exclude_batch_id") == "B-123"
