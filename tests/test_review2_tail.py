"""Regression tests for the review-2 P2/P3 tail (HADES-ays).

- tests must never open a real network/SMTP connection
- blank ContactID must not collapse VS rows via INSERT OR REPLACE
- an unparseable Added Date must not drop a row out of the dedup window
- one canonical normalize_phone
- purge_soft_deleted must leave an audit trail
- burst detector must see deletes, not just the newest N mutations
- headless scripts must all initialize Sentry
"""

import io
import sqlite3
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("libsql_experimental", MagicMock())

from turso_db import TursoDatabase
from vs_leads import parse_vs_export


def _db():
    db = TursoDatabase.__new__(TursoDatabase)
    db._conn = sqlite3.connect(":memory:")
    db.url = ":memory:"
    db._in_transaction = False
    db.init_schema()
    return db


HEADER = ('"ContactID","Company","State","Zip Code","Lead Status","Added Date",'
          '"Business","Mobile","Home","List Source","Import Notes","Call History"')


def _csv(*rows):
    return io.StringIO(HEADER + "\n" + "\n".join(rows) + "\n")


class TestNoLiveNetworkInTests:
    """The suite opened real TCP to smtp.gmail.com on every run; the broad
    `except Exception: email_failed=True` swallowed the failure so it passed
    silently. An autouse conftest fixture must make that impossible."""

    def test_smtp_class_is_patched_during_tests(self):
        import smtplib
        assert isinstance(smtplib.SMTP, MagicMock), (
            "smtplib.SMTP is the real class — a test can still dial Gmail")

    def test_constructing_smtp_performs_no_io(self):
        """A bogus host would raise/hang for the real class; the patched one
        returns a mock immediately."""
        import smtplib
        client = smtplib.SMTP("smtp.invalid.example", 587, timeout=1)
        client.starttls()
        client.login("u", "p")
        client.send_message(object())
        client.quit()   # no exception, no socket


class TestBlankContactIdDoesNotCollapse:
    """contact_id is TEXT PRIMARY KEY with INSERT OR REPLACE — blank ids all
    key to '' and each row silently overwrites the last."""

    def test_blank_ids_are_skipped_and_counted(self):
        rows = (
            '"","Acme Co","TX","75201","","01/01/2026 01:00:00 PM","2145550100","","","","",""',
            '"","Beta Co","TX","75202","","01/01/2026 01:00:00 PM","2145550101","","","","",""',
            '"3","Gamma Co","TX","75203","","01/01/2026 01:00:00 PM","2145550102","","","","",""',
        )
        result = parse_vs_export(_csv(*rows))
        assert result.skipped_no_id == 2
        assert [r["company_name"] for r in result.rows] == ["Gamma Co"]

    def test_import_does_not_silently_shrink(self):
        db = _db()
        rows = (
            '"","Acme Co","TX","75201","","01/01/2026 01:00:00 PM","2145550100","","","","",""',
            '"","Beta Co","TX","75202","","01/01/2026 01:00:00 PM","2145550101","","","","",""',
        )
        parsed = parse_vs_export(_csv(*rows))
        db.upsert_vs_leads_batch(parsed.rows)
        assert db.get_vs_leads_stats()["total"] == len(parsed.rows)


class TestBadAddedDateStaysInWindow:
    """added_date='' loses the lexicographic >= comparison, so a row with an
    unparseable date became invisible to dedup forever."""

    def test_unparseable_date_row_is_still_dedup_visible(self):
        db = _db()
        row = '"7","Gamma LLC","TX","75201","","not a date","2145550100","","","","",""'
        parsed = parse_vs_export(_csv(row))
        assert parsed.bad_dates == 1
        db.upsert_vs_leads_batch(parsed.rows)
        index = db.get_vs_dedup_index(days_back=365)
        assert [r["company_name"] for r in index] == ["Gamma LLC"]

    def test_genuinely_old_rows_still_expire(self):
        db = _db()
        row = '"8","Ancient Co","TX","75201","","01/01/2015 01:00:00 PM","2145550100","","","","",""'
        db.upsert_vs_leads_batch(parse_vs_export(_csv(row)).rows)
        assert db.get_vs_dedup_index(days_back=365) == []


class TestOneCanonicalNormalizePhone:
    """Both dedup paths must agree on what counts as a valid MATCH key.
    utils.normalize_phone stays loose (format_phone depends on raw digits);
    normalize_phone_key is the strict, canonical matcher."""

    def test_key_function_is_shared(self):
        from utils import normalize_phone_key
        from vs_leads import normalize_phone as vs_np
        for raw in ("911", "12345", "(214) 555-0100", "1-214-555-0100",
                    "call the front desk", "", None):
            assert normalize_phone_key(raw or "") == vs_np(raw), f"divergent on {raw!r}"

    def test_short_fragments_never_become_dedup_keys(self):
        """A 3-digit fragment as a key would collide by coincidence."""
        from dedup import get_dedup_key
        assert get_dedup_key({"companyName": "Acme", "directPhone": "911"}) == "|acme"

    def test_valid_phone_still_keys(self):
        from dedup import get_dedup_key
        assert get_dedup_key(
            {"companyName": "Acme", "directPhone": "(214) 555-0100"}
        ) == "2145550100|acme"


class TestPurgeIsAudited:
    def test_purge_writes_a_mutation_entry(self):
        db = _db()
        op = db.create_operator(operator_name="Doomed Co", team="A")
        db.delete_operator(op)
        db.execute_write("UPDATE operators SET deleted_at = datetime('now','-120 days')")
        db.purge_soft_deleted(days=90)
        purges = [m for m in db.get_recent_mutations(limit=50)
                  if m["actor"] == "purge-job"]
        assert purges, "the most destructive operation left no audit trail"
        assert purges[0]["table_name"] == "operators"


class TestBurstDetectorSeesDeletes:
    def test_deletes_are_not_pushed_out_by_other_ops(self):
        """The detector was fed the newest N mutations of ANY op, so a real
        delete burst could fall outside the window behind ordinary writes."""
        db = _db()
        for i in range(150):
            db.log_mutation("operators", i, "delete", before={"n": i}, after=None)
        for i in range(400):
            db.log_mutation("staged_exports", i, "insert", before=None, after={"n": i})
        deletes = db.get_recent_mutations(limit=500, op="delete")
        assert len(deletes) == 150
        assert all(m["op"] == "delete" for m in deletes)


class TestAllHeadlessScriptsInitSentry:
    def test_every_script_main_initializes_sentry(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        for name in ("run_intent_pipeline.py", "check_zoominfo_health.py",
                     "run_zoho_operator_sync.py", "data_anomaly_check.py",
                     "purge_soft_deleted.py", "import_vs_leads.py",
                     "backfill_exports.py"):
            src = (root / "scripts" / name).read_text()
            assert "init_sentry" in src, f"{name} never initializes Sentry"
