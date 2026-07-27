"""Regression tests for review-2 N2-03 (Sentry) and N2-08/09/10/12 (DB layer)."""

import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("libsql_experimental", MagicMock())

import observability
from turso_db import TursoDatabase


def _db():
    db = TursoDatabase.__new__(TursoDatabase)
    db._conn = sqlite3.connect(":memory:")
    db.url = ":memory:"
    db._in_transaction = False
    db.init_schema()
    return db


@pytest.fixture(autouse=True)
def _reset():
    observability.reset_for_tests()
    yield
    observability.reset_for_tests()


# ---------------------------------------------------------------------------
# N2-03 — the scrubber must cover the paths that actually carry data
# ---------------------------------------------------------------------------

class TestScrubberCoversLiveePaths:
    """The original scrub_event only touched event['extra'], and nothing in
    the codebase calls set_extra — so it was dead code, while the ACTIVE
    LoggingIntegration path shipped log/exception text unscrubbed."""

    def test_exception_message_is_scrubbed(self):
        event = {"exception": {"values": [
            {"type": "ValueError",
             "value": "failed on {'firstName': 'Jane', 'phone': '2145550100'}"}
        ]}}
        out = observability.scrub_event(event, {})
        text = out["exception"]["values"][0]["value"]
        assert "2145550100" not in text
        assert "Jane" not in text

    def test_log_message_is_scrubbed(self):
        event = {"logentry": {"message": "export failed for jane@acme.com"}}
        out = observability.scrub_event(event, {})
        assert "jane@acme.com" not in out["logentry"]["message"]

    def test_breadcrumb_hook_scrubs(self):
        crumb = observability.scrub_breadcrumb(
            {"message": "pushing lead 214-555-0100 for jane@acme.com"}, {})
        assert "555" not in crumb["message"]
        assert "jane@acme.com" not in crumb["message"]

    def test_ordinary_diagnostics_survive(self):
        """Scrubbing must not destroy the debugging value of an event."""
        event = {"logentry": {"message": "Scoring 42 intent leads for batch HADES-20260726-001"}}
        out = observability.scrub_event(event, {})
        assert "42" in out["logentry"]["message"]
        assert "HADES-20260726-001" in out["logentry"]["message"]

    def test_extra_credentials_still_redacted(self):
        event = {"extra": {"ZOOMINFO_CLIENT_SECRET": "shh", "batch": "B1"}}
        out = observability.scrub_event(event, {})
        assert out["extra"]["ZOOMINFO_CLIENT_SECRET"] == "[redacted]"
        assert out["extra"]["batch"] == "B1"

    def test_breadcrumb_hook_is_registered(self):
        with patch.object(observability, "_get_dsn", return_value="https://k@o.ingest.sentry.io/1"), \
             patch.object(observability, "sentry_sdk") as sdk:
            observability.init_sentry()
            kwargs = sdk.init.call_args[1]
            assert kwargs["before_breadcrumb"] is observability.scrub_breadcrumb
            assert kwargs["before_send"] is observability.scrub_event

    def test_malformed_event_shapes_do_not_crash(self):
        for bad in (None, {}, {"exception": None}, {"exception": {"values": "x"}},
                    {"logentry": {"message": None}}, {"extra": "notadict"}):
            observability.scrub_event(bad, {})
        assert observability.scrub_breadcrumb(None, {}) is None


# ---------------------------------------------------------------------------
# N2-08 — claim_pipeline_run must commit under the connection lock
# ---------------------------------------------------------------------------

class TestClaimCommitsUnderLock:
    def test_commit_happens_while_lock_held(self):
        """sqlite3.Connection.commit is a read-only C attribute, so the probe
        wraps the connection rather than patching the method."""
        db = _db()
        held = []

        class LockProbe:
            def __init__(self, inner):
                self.inner = inner
                self.depth = 0

            def __enter__(self):
                self.depth += 1
                return self.inner.__enter__()

            def __exit__(self, *a):
                self.depth -= 1
                return self.inner.__exit__(*a)

        probe = LockProbe(db._lock)
        db._lock = probe

        class ConnProxy:
            def __init__(self, inner): self._inner = inner
            def commit(self):
                held.append(probe.depth)
                return self._inner.commit()
            def __getattr__(self, name):
                return getattr(self._inner, name)

        db._conn = ConnProxy(db._conn)
        db.claim_pipeline_run("intent", "scheduled", {})
        assert held, "commit never ran"
        assert all(d > 0 for d in held), (
            "claim_pipeline_run committed with the connection lock released")


# ---------------------------------------------------------------------------
# N2-09 — purging an operator must not orphan export attribution
# ---------------------------------------------------------------------------

class TestPurgeKeepsAttribution:
    def test_staged_export_keeps_operator_name_after_purge(self):
        db = _db()
        op = db.create_operator(operator_name="Acme Vending", team="A")
        exp = db.save_staged_export("geography", [{"c": 1}], operator_id=op)
        db.delete_operator(op)
        db.execute_write("UPDATE operators SET deleted_at = datetime('now','-120 days')")
        db.purge_soft_deleted(days=90)
        row = db.get_staged_export(exp)
        assert row["operator_name"] == "Acme Vending", (
            "attribution lost when the operator row was purged")


# ---------------------------------------------------------------------------
# N2-10 — zoho_id needs the same deleted-row recovery as operator_name
# ---------------------------------------------------------------------------

class TestZohoIdRecovery:
    def test_find_deleted_operator_by_zoho_id(self):
        db = _db()
        op = db.create_operator(operator_name="Acme Vending", team="A")
        db.execute_write("UPDATE operators SET zoho_id = 'z-123' WHERE id = ?", (op,))
        db.delete_operator(op)
        found = db.find_deleted_operator_by_zoho_id("z-123")
        assert found and found["id"] == op

    def test_ignores_live_operators(self):
        db = _db()
        op = db.create_operator(operator_name="Live Co", team="A")
        db.execute_write("UPDATE operators SET zoho_id = 'z-live' WHERE id = ?", (op,))
        assert db.find_deleted_operator_by_zoho_id("z-live") is None


# ---------------------------------------------------------------------------
# N2-12 — the outcome audit must record a real before-state
# ---------------------------------------------------------------------------

class TestOutcomeAuditBeforeState:
    def _seed(self, db, batch="B1", company="Acme"):
        db.record_lead_outcomes_batch([
            (batch, company, "100", "p1", None, None, None, None, None, 0,
             "geography", "2026-07-01 10:00:00", None)])

    def test_before_state_captured(self):
        db = _db()
        self._seed(db)
        db.update_lead_outcome("B1", "Acme", "delivery", "2026-07-20")
        row = db.get_recent_mutations(table_name="lead_outcomes")[0]
        assert row["before"] is not None
        assert row["before"].get("outcome") in (None, "")
        assert row["after"]["outcome"] == "delivery"

    def test_multi_row_match_is_recorded(self):
        """The match is on (batch_id, company_name) and can touch several
        rows — the audit must say how many."""
        db = _db()
        self._seed(db)
        db.record_lead_outcomes_batch([
            ("B1", "Acme", "100", "p2", None, None, None, None, None, 0,
             "geography", "2026-07-01 10:00:00", None)])
        db.update_lead_outcome("B1", "Acme", "delivery", "2026-07-20")
        row = db.get_recent_mutations(table_name="lead_outcomes")[0]
        assert row["before"].get("matched_rows") == 2
