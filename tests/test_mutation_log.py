"""Tests for db/_mutation_log.py — mutation audit trail (HADES-6if).

Defends against the dominant threat in this codebase: our own code
corrupting our own data. The centroid corruption, the Company Enrich
silent failure and the phone-column inversion all had that shape, and
backups don't help because we back up the bad data right after writing it.

This is the append-only record of "what changed, when, from what to what".
"""

import sqlite3
import sys
from unittest.mock import MagicMock


sys.modules.setdefault("streamlit", MagicMock())
sys.modules.setdefault("libsql_experimental", MagicMock())

from turso_db import TursoDatabase


def _db():
    db = TursoDatabase.__new__(TursoDatabase)
    db._conn = sqlite3.connect(":memory:")
    db.url = ":memory:"
    db._in_transaction = False
    db.init_schema()
    return db


class TestLogMutation:
    def test_records_a_row(self):
        db = _db()
        db.log_mutation("operators", 7, "update",
                        before={"team": "A"}, after={"team": "B"}, actor="ui")
        rows = db.get_recent_mutations(limit=10)
        assert len(rows) == 1
        r = rows[0]
        assert r["table_name"] == "operators"
        assert r["row_id"] == "7"
        assert r["op"] == "update"
        assert r["actor"] == "ui"
        assert r["before"] == {"team": "A"}
        assert r["after"] == {"team": "B"}
        assert r["ts"]

    def test_insert_has_no_before_state(self):
        db = _db()
        db.log_mutation("operators", 1, "insert", before=None, after={"operator_name": "Jane"})
        r = db.get_recent_mutations()[0]
        assert r["before"] is None
        assert r["after"]["operator_name"] == "Jane"

    def test_delete_captures_the_lost_row(self):
        """The whole point of a delete entry: the row is gone from its table,
        so the log is the only remaining copy."""
        db = _db()
        db.log_mutation("operators", 3, "delete",
                        before={"operator_name": "Gone Co", "team": "B"}, after=None)
        r = db.get_recent_mutations()[0]
        assert r["after"] is None
        assert r["before"]["operator_name"] == "Gone Co"

    def test_row_id_coerced_to_string(self):
        """Mixed int/str ids across call sites must query consistently."""
        db = _db()
        db.log_mutation("operators", 42, "update", before={}, after={})
        db.log_mutation("operators", "42", "update", before={}, after={})
        assert {r["row_id"] for r in db.get_recent_mutations()} == {"42"}

    def test_unserializable_payload_does_not_raise(self):
        """A logging failure must never break the write it is auditing."""
        db = _db()
        db.log_mutation("operators", 1, "update",
                        before={"when": object()}, after={"ok": 1})
        rows = db.get_recent_mutations()
        assert len(rows) == 1  # recorded, with a fallback repr

    def test_logging_failure_is_swallowed(self):
        db = _db()
        db.execute_write = MagicMock(side_effect=RuntimeError("db down"))
        db.log_mutation("operators", 1, "update", before={}, after={})  # must not raise


class TestGetRecentMutations:
    def test_newest_first_and_limited(self):
        db = _db()
        for i in range(5):
            db.log_mutation("operators", i, "update", before={"n": i}, after={"n": i + 1})
        rows = db.get_recent_mutations(limit=3)
        assert len(rows) == 3
        assert [r["row_id"] for r in rows] == ["4", "3", "2"]

    def test_filter_by_table(self):
        db = _db()
        db.log_mutation("operators", 1, "update", before={}, after={})
        db.log_mutation("staged_exports", 2, "insert", before=None, after={})
        rows = db.get_recent_mutations(table_name="staged_exports")
        assert len(rows) == 1
        assert rows[0]["table_name"] == "staged_exports"

    def test_empty_log(self):
        assert _db().get_recent_mutations() == []


class TestRetention:
    def test_purge_old_mutations(self):
        db = _db()
        db.log_mutation("operators", 1, "update", before={}, after={})
        db.execute_write("UPDATE mutation_log SET ts = datetime('now', '-120 days')")
        assert db.purge_old_mutations(days=90) == 1
        assert db.get_recent_mutations() == []

    def test_purge_keeps_recent(self):
        db = _db()
        db.log_mutation("operators", 1, "update", before={}, after={})
        assert db.purge_old_mutations(days=90) == 0
        assert len(db.get_recent_mutations()) == 1

    def test_init_schema_wires_the_purge(self):
        import inspect
        from db._schema import SchemaMixin
        assert "purge_old_mutations" in inspect.getsource(SchemaMixin.init_schema)


class TestInstrumentedSites:
    """The high-value sites: operator CRUD (a wrong edit mislabels every
    export under that operator) and staged_exports/lead_outcomes writes."""

    def _seed_operator(self, db):
        return db.create_operator(operator_name="Acme Vending", team="A",
                                  operator_phone="2145550100")

    def test_create_operator_logged(self):
        db = _db()
        op_id = self._seed_operator(db)
        rows = db.get_recent_mutations(table_name="operators")
        assert len(rows) == 1
        assert rows[0]["op"] == "insert"
        assert rows[0]["row_id"] == str(op_id)
        assert rows[0]["after"]["operator_name"] == "Acme Vending"

    def test_update_operator_logs_before_and_after(self):
        db = _db()
        op_id = self._seed_operator(db)
        db.update_operator(op_id, operator_name="Acme Vending", team="B",
                           operator_phone="2145550100")
        row = db.get_recent_mutations(table_name="operators")[0]
        assert row["op"] == "update"
        assert row["before"]["team"] == "A"
        assert row["after"]["team"] == "B"

    def test_delete_operator_preserves_the_row(self):
        db = _db()
        op_id = self._seed_operator(db)
        db.delete_operator(op_id)
        row = db.get_recent_mutations(table_name="operators")[0]
        assert row["op"] == "delete"
        assert row["before"]["operator_name"] == "Acme Vending"
        assert db.get_operator(op_id) is None

    def test_staged_export_insert_logged(self):
        db = _db()
        export_id = db.save_staged_export("geography", [{"companyName": "X"}])
        rows = db.get_recent_mutations(table_name="staged_exports")
        assert len(rows) == 1
        assert rows[0]["op"] == "insert"
        assert rows[0]["row_id"] == str(export_id)
        # leads_json is bulky — the log stores counts, not the payload
        assert rows[0]["after"].get("lead_count") == 1
        assert "leads_json" not in rows[0]["after"]

    def test_mark_staged_exported_logged(self):
        db = _db()
        export_id = db.save_staged_export("geography", [{"companyName": "X"}])
        db.mark_staged_exported(export_id, "HADES-B1")
        row = db.get_recent_mutations(table_name="staged_exports")[0]
        assert row["op"] == "update"
        assert row["after"]["batch_id"] == "HADES-B1"

    def test_audit_insert_failure_does_not_block_the_write(self):
        """The audit INSERT failing must not fail the operator write."""
        db = _db()
        real_write = db.execute_write

        def fail_on_mutation_log(sql, params=()):
            if "mutation_log" in sql:
                raise RuntimeError("log table gone")
            return real_write(sql, params)

        db.execute_write = fail_on_mutation_log
        op_id = db.create_operator(operator_name="Still Saved", team="A")
        db.execute_write = real_write
        assert db.get_operator(op_id)["operator_name"] == "Still Saved"

    def test_snapshot_read_failure_does_not_block_the_write(self):
        """The before/after read-back sits ON the write path — a DB hiccup
        there must not fail a write that already succeeded."""
        db = _db()
        op_id = db.create_operator(operator_name="Original", team="A")
        db.get_operator = MagicMock(side_effect=RuntimeError("read failed"))
        db.update_operator(op_id, operator_name="Renamed", team="B")  # must not raise
        del db.get_operator
        assert db.get_operator(op_id)["operator_name"] == "Renamed"
