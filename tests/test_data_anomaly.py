"""Tests for the data-anomaly evaluators (HADES-e7j).

Early warning for slow-drift failure modes the other defenses can't catch:
a mass delete, a silently-degrading Zoho sync, a yield collapse after a
filter change. Pure logic — the scheduled script wires DB reads into these.
"""

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("libsql_experimental", MagicMock())

from monitoring import (
    evaluate_row_count_drop,
    evaluate_linkage_drop,
    evaluate_export_volume,
    evaluate_mutation_burst,
)


class TestRowCountDrop:
    def test_stable_count_is_ok(self):
        v = evaluate_row_count_drop("operators", current=100, baseline=100)
        assert v["severity"] == "ok"

    def test_growth_is_ok(self):
        assert evaluate_row_count_drop("operators", 120, 100)["severity"] == "ok"

    def test_small_drop_within_threshold_is_ok(self):
        # 98/100 = 2% drop, under the 5% threshold
        assert evaluate_row_count_drop("operators", 98, 100)["severity"] == "ok"

    def test_drop_past_threshold_warns(self):
        v = evaluate_row_count_drop("operators", 90, 100)  # 10%
        assert v["severity"] == "warning"
        assert "10" in v["message"] or "10.0" in v["message"]

    def test_total_wipe_is_critical(self):
        v = evaluate_row_count_drop("operators", 0, 100)
        assert v["severity"] == "critical"

    def test_no_baseline_yet_is_ok_not_alarming(self):
        """First run has nothing to compare against — must not cry wolf."""
        assert evaluate_row_count_drop("operators", 100, None)["severity"] == "ok"

    def test_zero_baseline_does_not_divide_by_zero(self):
        assert evaluate_row_count_drop("operators", 0, 0)["severity"] == "ok"

    def test_small_table_single_row_loss_still_flags(self):
        """With 3 operators, losing 1 is a 33% drop — the percentage
        threshold catches it without needing an absolute-count floor (a
        floor of 1 would make every routine single-row delete an alert)."""
        v = evaluate_row_count_drop("operators", 2, 3)
        assert v["severity"] in ("warning", "critical")


class TestLinkageDrop:
    def test_stable_linkage_ok(self):
        assert evaluate_linkage_drop(0.80, 0.80)["severity"] == "ok"

    def test_improved_linkage_ok(self):
        assert evaluate_linkage_drop(0.95, 0.80)["severity"] == "ok"

    def test_drop_past_threshold_warns(self):
        v = evaluate_linkage_drop(0.60, 0.80)  # 20 points
        assert v["severity"] == "warning"

    def test_no_baseline_is_ok(self):
        assert evaluate_linkage_drop(0.80, None)["severity"] == "ok"


class TestExportVolume:
    def test_normal_volume_ok(self):
        history = [20, 22, 19, 21, 20, 23, 18] * 4
        assert evaluate_export_volume(20, history)["severity"] == "ok"

    def test_collapse_below_two_sigma_warns(self):
        history = [20, 22, 19, 21, 20, 23, 18] * 4
        v = evaluate_export_volume(2, history)
        assert v["severity"] == "warning"

    def test_zero_exports_against_healthy_history_is_critical(self):
        history = [20, 22, 19, 21, 20, 23, 18] * 4
        assert evaluate_export_volume(0, history)["severity"] == "critical"

    def test_insufficient_history_is_ok(self):
        """A handful of samples can't support a 2σ claim."""
        assert evaluate_export_volume(0, [5, 5])["severity"] == "ok"

    def test_flat_history_does_not_divide_by_zero(self):
        """Zero variance — stdev 0 must not blow up or fire on equality."""
        assert evaluate_export_volume(20, [20] * 30)["severity"] == "ok"

    def test_flat_history_with_real_drop_still_flags(self):
        v = evaluate_export_volume(0, [20] * 30)
        assert v["severity"] in ("warning", "critical")

    def test_high_volume_never_alerts(self):
        history = [20] * 30
        assert evaluate_export_volume(200, history)["severity"] == "ok"


class TestMutationBurst:
    def _muts(self, op, n, ts="2026-07-26 09:00:00"):
        return [{"op": op, "ts": ts, "table_name": "operators"} for _ in range(n)]

    def test_quiet_log_is_ok(self):
        assert evaluate_mutation_burst(self._muts("update", 3))["severity"] == "ok"

    def test_mass_delete_in_one_minute_is_critical(self):
        v = evaluate_mutation_burst(self._muts("delete", 120))
        assert v["severity"] == "critical"
        assert "delete" in v["message"].lower()

    def test_deletes_spread_over_time_are_ok(self):
        muts = []
        for i in range(120):
            muts.append({"op": "delete", "table_name": "operators",
                         "ts": f"2026-07-26 {i // 60:02d}:{i % 60:02d}:00"})
        assert evaluate_mutation_burst(muts)["severity"] == "ok"

    def test_bulk_inserts_are_not_alarming(self):
        """A VanillaSoft import legitimately writes many rows at once."""
        assert evaluate_mutation_burst(self._muts("insert", 500))["severity"] == "ok"

    def test_empty_log_is_ok(self):
        assert evaluate_mutation_burst([])["severity"] == "ok"

    def test_unparseable_timestamps_do_not_crash(self):
        muts = [{"op": "delete", "ts": "not-a-date", "table_name": "operators"}] * 120
        assert evaluate_mutation_burst(muts)["severity"] in ("ok", "warning", "critical")


class TestCollectVerdicts:
    """The script wiring: DB reads → evaluators, with each check guarded."""

    def _db(self):
        import sqlite3
        from turso_db import TursoDatabase
        db = TursoDatabase.__new__(TursoDatabase)
        db._conn = sqlite3.connect(":memory:")
        db.url = ":memory:"
        db._in_transaction = False
        db.init_schema()
        return db

    def test_healthy_db_produces_no_alerts(self):
        from scripts.data_anomaly_check import collect_verdicts
        db = self._db()
        db.create_operator(operator_name="Acme", team="A")
        verdicts, _ = collect_verdicts(db)
        assert all(v["severity"] == "ok" for v in verdicts), verdicts

    def test_operator_drop_is_detected_against_stored_baseline(self):
        from scripts.data_anomaly_check import collect_verdicts, BASELINE_OPERATORS
        db = self._db()
        for i in range(10):
            db.create_operator(operator_name=f"Op {i}", team="A")
        collect_verdicts(db)                       # establishes the baseline
        db.set_sync_value(BASELINE_OPERATORS, "10")
        for i in range(5):                         # half the table disappears
            db.delete_operator(i + 1)
        verdicts, _ = collect_verdicts(db)
        assert any(v["severity"] in ("warning", "critical")
                   and "operators" in v["message"] for v in verdicts), verdicts

    def test_baselines_returned_for_storage(self):
        from scripts.data_anomaly_check import collect_verdicts, BASELINE_OPERATORS
        db = self._db()
        db.create_operator(operator_name="Acme", team="A")
        _, baselines = collect_verdicts(db)
        assert baselines[BASELINE_OPERATORS] == "1"

    def test_first_run_without_baseline_is_quiet(self):
        """Day one must not alert — nothing to compare against."""
        from scripts.data_anomaly_check import collect_verdicts
        db = self._db()
        db.create_operator(operator_name="Acme", team="A")
        verdicts, _ = collect_verdicts(db)
        assert all(v["severity"] == "ok" for v in verdicts)

    def test_a_failing_check_does_not_suppress_the_others(self):
        from unittest.mock import MagicMock
        from scripts.data_anomaly_check import collect_verdicts
        db = self._db()
        db.create_operator(operator_name="Acme", team="A")
        db.get_recent_mutations = MagicMock(side_effect=RuntimeError("boom"))
        verdicts, _ = collect_verdicts(db)
        assert len(verdicts) == 4  # operators, linkage, exports, mutations
        assert any(v["severity"] == "unknown" for v in verdicts)
        # the other three still produced real answers
        assert sum(1 for v in verdicts if v["severity"] == "ok") == 3

    def test_linkage_check_skipped_when_no_operators(self):
        """Linkage is undefined with an empty table — and the row-count
        check already covers the alarming part of that state."""
        from scripts.data_anomaly_check import collect_verdicts
        db = self._db()
        verdicts, _ = collect_verdicts(db)
        assert len(verdicts) == 3


class TestSummariseVerdicts:
    def test_worst_severity_wins(self):
        from monitoring import summarise_verdicts
        v = summarise_verdicts([
            {"severity": "ok", "message": "a"},
            {"severity": "critical", "message": "b"},
            {"severity": "warning", "message": "c"},
        ])
        assert v["severity"] == "critical"
        assert "b" in v["message"] and "c" in v["message"]

    def test_all_ok_summarises_ok(self):
        from monitoring import summarise_verdicts
        v = summarise_verdicts([{"severity": "ok", "message": "fine"}])
        assert v["severity"] == "ok"

    def test_empty_is_ok(self):
        from monitoring import summarise_verdicts
        assert summarise_verdicts([])["severity"] == "ok"
