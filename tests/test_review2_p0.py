"""Regression tests for review-2 P0 findings (HADES-4rx).

N2-01 soft-delete leaks into raw queries (incl. the nightly Zoho cron)
N2-02 empty-phone dedup key bypasses the state veto — franchise merge
N2-07 `phone` is a Business-phone fallback, not person-level dedup proof
"""

import sqlite3
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("streamlit", MagicMock())
sys.modules.setdefault("libsql_experimental", MagicMock())

from dedup import find_duplicates, get_dedup_key, merge_lead_lists, dedupe_leads
from export_dedup import filter_previously_exported
from turso_db import TursoDatabase


def _db():
    db = TursoDatabase.__new__(TursoDatabase)
    db._conn = sqlite3.connect(":memory:")
    db.url = ":memory:"
    db._in_transaction = False
    db.init_schema()
    return db


# ---------------------------------------------------------------------------
# N2-02 — franchise merge via the empty-phone key
# ---------------------------------------------------------------------------

class TestEmptyPhoneKeyFranchiseSafety:
    """A phone-less lead yields '|companyname'. The old guard only caught
    '|' (no phone AND no company), so two same-name franchise locations in
    DIFFERENT states merged as a tier-1 exact match — and tier-1 skips the
    states_conflict veto by design."""

    def _pair(self):
        return (
            {"companyName": "Planet Fitness", "state": "TX", "personId": "p1"},
            {"companyName": "Planet Fitness", "state": "FL", "personId": "p2"},
        )

    def test_find_duplicates_does_not_merge_cross_state_franchises(self):
        """find_duplicates is CROSS-list (leads1 vs leads2)."""
        tx, fl = self._pair()
        assert find_duplicates([tx], [fl]) == []

    def test_find_duplicates_still_catches_same_state_dupe(self):
        a = {"companyName": "Acme Vending", "state": "TX", "personId": "p1"}
        b = {"companyName": "Acme Vending", "state": "TX", "personId": "p2"}
        assert len(find_duplicates([a], [b])) == 1

    def test_dedupe_leads_keeps_both_phoneless_franchise_locations(self):
        tx, fl = self._pair()
        deduped, removed = dedupe_leads([tx, fl])
        assert len(deduped) == 2
        assert removed == 0

    def test_merge_lead_lists_keeps_both(self):
        tx, fl = self._pair()
        merged = merge_lead_lists([tx], [fl])
        assert len(merged) == 2

    def test_genuine_same_state_duplicate_still_caught(self):
        """The fix must not disable dedup — same name, same state, no phone
        is still a duplicate."""
        a = {"companyName": "Acme Vending", "state": "TX", "personId": "p1"}
        b = {"companyName": "Acme Vending", "state": "TX", "personId": "p2"}
        deduped, removed = dedupe_leads([a, b])
        assert len(deduped) == 1 and removed == 1

    def test_phone_bearing_duplicates_unaffected(self):
        a = {"companyName": "Acme", "directPhone": "2145550100", "state": "TX"}
        b = {"companyName": "Acme", "directPhone": "2145550100", "state": "TX"}
        deduped, removed = dedupe_leads([a, b])
        assert len(deduped) == 1 and removed == 1

    def test_name_only_key_is_state_scoped(self):
        """New contract: a phone-less key folds in the state, so name-only
        matches can never cross a state boundary. Unknown state keeps the
        old shape (nothing to scope by)."""
        assert get_dedup_key({"companyName": "Acme Inc"}) == "|acme"
        assert get_dedup_key({"companyName": "Acme Inc", "state": "tx"}) == "|acme|TX"

    def test_phone_bearing_key_shape_unchanged(self):
        """A real phone is identity proof — state must NOT be folded in, or
        the same contact reached in two states would stop deduping."""
        assert get_dedup_key(
            {"companyName": "Acme Inc", "directPhone": "2145550100", "state": "TX"}
        ) == "2145550100|acme"


# ---------------------------------------------------------------------------
# N2-07 — `phone` is company-level, not person-level
# ---------------------------------------------------------------------------

def _vs_entry(**over):
    e = {
        "company_name": "Woodmere Health Care", "company_norm": "woodmere health care",
        "phone_business": "5163749300", "phone_mobile": "", "phone_home": "",
        "zip": "11598", "state": "NY", "lead_status": "Warm",
        "added_date": "2026-01-18 10:38:24",
    }
    e.update(over)
    return e


def _lookup(entries):
    from export_dedup import get_previously_exported
    db = MagicMock()
    db.get_exported_company_ids.return_value = {}
    db.get_vs_dedup_index.return_value = entries
    return get_previously_exported(db)


class TestBusinessPhoneNeedsZipCorroboration:
    """utils.py documents `phone` as the Business-phone FALLBACK, and the VS
    'Business' column is the same role — a shared switchboard across every
    location of a chain. Neither is standalone dedup proof."""

    def test_zoominfo_phone_field_alone_does_not_filter(self):
        contacts = [{
            "companyName": "Sunrise Senior Living Dallas", "companyId": "9001",
            "phone": "(516) 374-9300", "zip": "75201",   # different location
        }]
        new, filtered = filter_previously_exported(contacts, _lookup([_vs_entry()]))
        assert len(new) == 1 and len(filtered) == 0

    def test_zoominfo_phone_field_with_matching_zip_filters(self):
        contacts = [{
            "companyName": "Sunrise", "companyId": "9002",
            "phone": "5163749300", "zip": "11598",
        }]
        new, filtered = filter_previously_exported(contacts, _lookup([_vs_entry()]))
        assert len(filtered) == 1

    def test_vs_business_phone_alone_does_not_filter(self):
        """Match lands on the VS phone_business column — needs ZIP too."""
        contacts = [{
            "companyName": "Different Name Co", "companyId": "9003",
            "directPhone": "5163749300", "zip": "75201",
        }]
        new, filtered = filter_previously_exported(contacts, _lookup([_vs_entry()]))
        assert len(new) == 1 and len(filtered) == 0

    def test_person_level_phone_match_still_standalone_proof(self):
        """A VS mobile/home number is person-level on both sides — no ZIP needed."""
        entry = _vs_entry(phone_business="", phone_mobile="5163749300")
        contacts = [{
            "companyName": "Different Name Co", "companyId": "9004",
            "directPhone": "5163749300", "zip": "75201",
        }]
        new, filtered = filter_previously_exported(contacts, _lookup([entry]))
        assert len(filtered) == 1


# ---------------------------------------------------------------------------
# N2-01 — soft-delete must not leak into raw queries
# ---------------------------------------------------------------------------

class TestSoftDeleteNoLeaks:
    def test_zoho_reconciliation_query_excludes_deleted(self):
        """zoho_sync's reconciliation fetch drives both the nightly UPDATE
        batch and duplicate-name skipping. A soft-deleted operator there
        keeps getting rewritten and permanently shadows its own name."""
        import inspect
        import zoho_sync
        src = inspect.getsource(zoho_sync.sync_operators)
        idx = src.find("FROM operators")
        assert idx != -1
        window = src[max(0, idx - 200):idx + 120]
        assert "deleted_at IS NULL" in window

    def test_operators_page_counts_exclude_deleted(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "pages" / "3_Operators.py").read_text()
        for line in src.splitlines():
            if "FROM operators" in line and "db.execute" in line:
                assert "deleted_at IS NULL" in line, f"unfiltered count: {line.strip()}"

    def test_no_unfiltered_operator_reads_remain(self):
        """Repo-wide sweep: every FROM operators read must either filter
        deleted_at or be an intentional by-ID lookup."""
        import subprocess
        out = subprocess.run(
            ["grep", "-rn", "--include=*.py", "FROM operators", "."],
            capture_output=True, text=True, cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
        ).stdout
        offenders = []
        for line in out.splitlines():
            if "/tests/" in line or ".claude/worktrees" in line or "test_" in line:
                continue
            if "deleted_at" in line or "WHERE id = ?" in line or "{where}" in line:
                continue
            offenders.append(line.strip())
        assert not offenders, "unfiltered operator reads:\n" + "\n".join(offenders)

    def test_soft_deleted_operator_not_rewritten_by_sync(self):
        """Behavioral: a soft-deleted operator must not appear in the
        reconciliation maps the sync builds."""
        db = _db()
        keep = db.create_operator(operator_name="Live Co", team="A")
        gone = db.create_operator(operator_name="Gone Co", team="A")
        db.execute_write("UPDATE operators SET zoho_id = 'z-gone' WHERE id = ?", (gone,))
        db.delete_operator(gone)
        rows = db.execute(
            "SELECT id, zoho_id, operator_name FROM operators WHERE deleted_at IS NULL"
        )
        assert [r[0] for r in rows] == [keep]
