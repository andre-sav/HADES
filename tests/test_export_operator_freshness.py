"""Tests for resolve_export_operator (HADES-fpd step 1).

The Geography page snapshots the whole operator dict into session_state
when it is picked (pages/2), and the Export page reads export metadata
straight off that snapshot (pages/4). If anyone edits the operator after
the pick — through the UI OR the nightly out-of-process Zoho sync — the
export carries stale name/phone/business into VanillaSoft, unbounded, for
the life of the browser session.

Re-reading by ID at the point of consequence closes that. Never blocks an
export: any failure falls back to the snapshot we already had.
"""

import sqlite3
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("libsql_experimental", MagicMock())

from export import resolve_export_operator
from turso_db import TursoDatabase


def _db():
    db = TursoDatabase.__new__(TursoDatabase)
    db._conn = sqlite3.connect(":memory:")
    db.url = ":memory:"
    db._in_transaction = False
    db.init_schema()
    return db


class TestResolveExportOperator:
    def test_no_operator_stays_none(self):
        assert resolve_export_operator(_db(), None) is None

    def test_stale_snapshot_is_refreshed(self):
        """The actual bug: operator edited after being picked."""
        db = _db()
        op_id = db.create_operator(operator_name="Acme Vending", team="A",
                                   operator_phone="2145550100")
        snapshot = db.get_operator(op_id)          # what session_state holds
        db.update_operator(op_id, operator_name="Acme Vending",
                           team="B", operator_phone="8175559999")

        fresh = resolve_export_operator(db, snapshot)
        assert fresh["operator_phone"] == "8175559999"
        assert fresh["team"] == "B"

    def test_unchanged_operator_round_trips(self):
        db = _db()
        op_id = db.create_operator(operator_name="Acme Vending", team="A")
        snapshot = db.get_operator(op_id)
        assert resolve_export_operator(db, snapshot)["operator_name"] == "Acme Vending"

    def test_manual_operator_without_id_is_passed_through(self):
        """Manually-entered operators have no DB row — nothing to re-read."""
        manual = {"operator_name": "One-off Co", "operator_phone": "2145550100"}
        assert resolve_export_operator(_db(), manual) == manual

    def test_db_failure_falls_back_to_snapshot(self):
        """A DB hiccup must never block an export that is ready to go."""
        db = _db()
        snapshot = {"id": 1, "operator_name": "Acme Vending"}
        db.get_operator = MagicMock(side_effect=RuntimeError("turso down"))
        assert resolve_export_operator(db, snapshot) == snapshot

    def test_purged_operator_falls_back_to_snapshot(self):
        """Hard-purged past the 90-day window — keep the attribution we have
        rather than silently dropping the operator from the export."""
        db = _db()
        snapshot = {"id": 9999, "operator_name": "Long Gone Co"}
        assert resolve_export_operator(db, snapshot) == snapshot

    def test_soft_deleted_operator_still_resolves(self):
        """Soft delete keeps by-ID lookups working (HADES-l3n), so a
        mid-session delete does not strip attribution from the export."""
        db = _db()
        op_id = db.create_operator(operator_name="Deleted Co", team="A")
        snapshot = db.get_operator(op_id)
        db.delete_operator(op_id)
        assert resolve_export_operator(db, snapshot)["operator_name"] == "Deleted Co"

    def test_id_as_string_still_resolves(self):
        db = _db()
        op_id = db.create_operator(operator_name="Acme Vending", team="A")
        assert resolve_export_operator(db, {"id": str(op_id)})["operator_name"] == "Acme Vending"


class TestWiring:
    def test_export_page_resolves_before_building_metadata(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "pages" / "4_CSV_Export.py").read_text()
        assert "resolve_export_operator" in src
