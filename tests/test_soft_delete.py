"""Tests for soft-delete on operators + staged_exports (HADES-l3n).

Data-loss defense step 2: an accidental UI delete or a buggy mass-delete
should be recoverable for 90 days without reaching for PITR.

Design note — by-ID lookups still resolve a soft-deleted row (historical
exports keep their operator attribution), while LIST/PICKER queries hide
it. delete_operator therefore no longer nullifies staged_exports links:
severing them would make an undelete only partially recoverable.
"""

import sqlite3
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("libsql_experimental", MagicMock())

from turso_db import TursoDatabase


def _db():
    db = TursoDatabase.__new__(TursoDatabase)
    db._conn = sqlite3.connect(":memory:")
    db.url = ":memory:"
    db._in_transaction = False
    db.init_schema()
    return db


def _op(db, name="Acme Vending", **kw):
    return db.create_operator(operator_name=name, team=kw.pop("team", "A"), **kw)


class TestSoftDeleteOperators:
    def test_delete_preserves_the_row(self):
        db = _db()
        op_id = _op(db)
        db.delete_operator(op_id)
        rows = db.execute("SELECT deleted_at FROM operators WHERE id = ?", (op_id,))
        assert rows, "row was hard-deleted — soft delete did not take effect"
        assert rows[0][0] is not None

    def test_deleted_operator_hidden_from_list(self):
        db = _db()
        keep, gone = _op(db, "Keep Co"), _op(db, "Gone Co")
        db.delete_operator(gone)
        names = [o["operator_name"] for o in db.get_operators()]
        assert names == ["Keep Co"]

    def test_deleted_operator_hidden_from_search(self):
        db = _db()
        _op(db, "Keep Co")
        db.delete_operator(_op(db, "Gone Co"))
        operators, total = db.search_operators()
        assert total == 1
        assert [o["operator_name"] for o in operators] == ["Keep Co"]

    def test_search_by_query_excludes_deleted(self):
        db = _db()
        db.delete_operator(_op(db, "Gone Co"))
        operators, total = db.search_operators(query="Gone")
        assert total == 0
        assert operators == []

    def test_by_id_lookup_still_resolves(self):
        """Historical exports must keep their operator attribution."""
        db = _db()
        op_id = _op(db, "Gone Co")
        db.delete_operator(op_id)
        assert db.get_operator(op_id)["operator_name"] == "Gone Co"

    def test_staged_export_links_are_preserved(self):
        """Nullifying the FK would make an undelete only partly recoverable."""
        db = _db()
        op_id = _op(db)
        export_id = db.save_staged_export("geography", [{"c": 1}], operator_id=op_id)
        db.delete_operator(op_id)
        row = db.get_staged_export(export_id)
        assert row["operator_id"] == op_id

    def test_recent_operator_ids_excludes_deleted(self):
        db = _db()
        keep, gone = _op(db, "Keep Co"), _op(db, "Gone Co")
        db.save_staged_export("geography", [{"c": 1}], operator_id=keep)
        db.save_staged_export("geography", [{"c": 1}], operator_id=gone)
        db.delete_operator(gone)
        assert db.get_recent_operator_ids() == [keep]

    def test_restore_operator(self):
        db = _db()
        op_id = _op(db, "Oops Co")
        db.delete_operator(op_id)
        assert db.get_operators() == []
        db.restore_operator(op_id)
        assert [o["operator_name"] for o in db.get_operators()] == ["Oops Co"]

    def test_delete_is_still_audited(self):
        """Soft-delete and the mutation log are complementary, not either/or."""
        db = _db()
        op_id = _op(db, "Gone Co")
        db.delete_operator(op_id)
        row = db.get_recent_mutations(table_name="operators")[0]
        assert row["op"] == "delete"
        assert row["before"]["operator_name"] == "Gone Co"

    def test_deleted_name_collision_is_detectable(self):
        """operator_name carries a column-level UNIQUE constraint, so a
        soft-deleted row still reserves its name (dropping that constraint
        would need a full table rebuild on live data — not worth the risk).
        The trade-off is made safe by making the collision DETECTABLE, so
        the UI can offer 'restore' instead of failing with a raw
        IntegrityError."""
        db = _db()
        op_id = _op(db, "Acme Vending")
        db.delete_operator(op_id)
        found = db.find_deleted_operator_by_name("Acme Vending")
        assert found is not None and found["id"] == op_id
        # ...and restoring genuinely frees the workflow
        db.restore_operator(op_id)
        assert db.find_deleted_operator_by_name("Acme Vending") is None

    def test_find_deleted_by_name_ignores_live_operators(self):
        db = _db()
        _op(db, "Live Co")
        assert db.find_deleted_operator_by_name("Live Co") is None


class TestSoftDeleteStagedExports:
    def test_delete_staged_export_is_soft(self):
        db = _db()
        export_id = db.save_staged_export("geography", [{"c": 1}])
        db.delete_staged_export(export_id)
        rows = db.execute("SELECT deleted_at FROM staged_exports WHERE id = ?", (export_id,))
        assert rows and rows[0][0] is not None

    def test_deleted_export_hidden_from_list(self):
        db = _db()
        keep = db.save_staged_export("geography", [{"c": 1}])
        gone = db.save_staged_export("intent", [{"c": 2}])
        db.delete_staged_export(gone)
        ids = [e["id"] for e in db.get_staged_exports()]
        assert ids == [keep]


class TestPurgeSweeper:
    def test_purges_operators_past_the_window(self):
        db = _db()
        op_id = _op(db, "Ancient Co")
        db.delete_operator(op_id)
        db.execute_write("UPDATE operators SET deleted_at = datetime('now', '-120 days')")
        assert db.purge_soft_deleted(days=90)["operators"] == 1
        assert db.execute("SELECT id FROM operators WHERE id = ?", (op_id,)) == []

    def test_keeps_recently_deleted_within_window(self):
        db = _db()
        db.delete_operator(_op(db, "Recent Co"))
        assert db.purge_soft_deleted(days=90)["operators"] == 0
        assert db.execute("SELECT COUNT(*) FROM operators")[0][0] == 1

    def test_purges_staged_exports_past_the_window(self):
        db = _db()
        export_id = db.save_staged_export("geography", [{"c": 1}])
        db.delete_staged_export(export_id)
        db.execute_write("UPDATE staged_exports SET deleted_at = datetime('now', '-120 days')")
        assert db.purge_soft_deleted(days=90)["staged_exports"] == 1

    def test_never_touches_live_rows(self):
        db = _db()
        _op(db, "Live Co")
        db.save_staged_export("geography", [{"c": 1}])
        result = db.purge_soft_deleted(days=0)
        assert result == {"operators": 0, "staged_exports": 0}
        assert db.execute("SELECT COUNT(*) FROM operators")[0][0] == 1


class TestMigration:
    def test_deleted_at_columns_declared_as_migrations(self):
        """Existing production tables need the ALTER path, not just CREATE."""
        import inspect
        from db._schema import SchemaMixin
        src = inspect.getsource(SchemaMixin._run_migrations)
        assert '"operators", "deleted_at"' in src
        assert '"staged_exports", "deleted_at"' in src
