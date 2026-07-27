"""Regression tests for review-2 P1 findings.

HADES-13h  N2-04 anomaly export-volume compares an in-progress day
           N2-14 the 2-sigma floor can go negative, disabling detection
HADES-lzv  N2-05 intent staged load nulls the Geography operator
           N2-06 one malformed ID aborts the whole resolution batch
           N2-13 geo_run_id cleared even when the run failed to close
"""

import sqlite3
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("streamlit", MagicMock())
sys.modules.setdefault("libsql_experimental", MagicMock())

from monitoring import evaluate_export_volume
from turso_db import TursoDatabase


def _db():
    db = TursoDatabase.__new__(TursoDatabase)
    db._conn = sqlite3.connect(":memory:")
    db.url = ":memory:"
    db._in_transaction = False
    db.init_schema()
    return db


# ---------------------------------------------------------------------------
# N2-04 — measure a COMPLETED day, never the in-progress one
# ---------------------------------------------------------------------------

class TestExportVolumeMeasuresCompletedDay:
    """The workflow runs 07:00 UTC (~2-3 AM ET), before any export happens
    that UTC day. Comparing the still-forming day against a mean of complete
    days yields 0 vs a healthy mean => 'critical' EVERY morning, which trains
    the operator to ignore the channel."""

    def _seed(self, db, day_offset, count):
        rows = [(f"B{day_offset}-{i}", "Co", str(i), None, None, None, None,
                 None, None, 0, "geography",
                 f"(datetime('now','-{day_offset} days'))", None)
                for i in range(count)]
        for r in rows:
            db.execute_write(
                "INSERT INTO lead_outcomes (batch_id, company_name, company_id, "
                "workflow_type, exported_at) VALUES (?, ?, ?, ?, "
                f"datetime('now','-{day_offset} days'))",
                (r[0], r[1], r[2], "geography"),
            )

    def test_todays_zero_does_not_alarm_when_yesterday_was_healthy(self):
        """The core bug: today is empty at 07:00 UTC by construction."""
        from scripts.data_anomaly_check import collect_verdicts
        db = _db()
        for day in range(1, 21):          # 20 healthy completed days
            self._seed(db, day, 20)
        # today deliberately has zero rows
        verdicts, _ = collect_verdicts(db)
        vol = [v for v in verdicts if "xport" in v["message"]]
        assert vol, "no export-volume verdict produced"
        assert vol[0]["severity"] == "ok", vol[0]["message"]

    def test_a_real_collapse_yesterday_still_alarms(self):
        """The fix must not blind the check — a genuinely empty YESTERDAY
        against a healthy history must still fire."""
        from scripts.data_anomaly_check import collect_verdicts
        db = _db()
        for day in range(2, 22):          # healthy days 2..21, yesterday empty
            self._seed(db, day, 20)
        verdicts, _ = collect_verdicts(db)
        vol = [v for v in verdicts if "xport" in v["message"]]
        assert vol and vol[0]["severity"] in ("warning", "critical"), vol


# ---------------------------------------------------------------------------
# N2-14 — the floor must never go negative
# ---------------------------------------------------------------------------

class TestExportVolumeFloorClamped:
    def test_high_variance_history_still_detects_zero(self):
        """With genuine zero-days mixed in, stdev can exceed mean/2, driving
        floor negative — every value then passes and detection is silently off."""
        history = [0, 0, 0, 40, 40, 40, 0, 45, 0, 38, 42, 0, 41, 39, 0]
        v = evaluate_export_volume(0, history)
        assert v["severity"] in ("warning", "critical"), v

    def test_healthy_value_against_high_variance_is_ok(self):
        history = [0, 0, 0, 40, 40, 40, 0, 45, 0, 38, 42, 0, 41, 39, 0]
        assert evaluate_export_volume(40, history)["severity"] == "ok"


# ---------------------------------------------------------------------------
# N2-05 — an intent staged load must not touch the Geography operator
# ---------------------------------------------------------------------------

class TestStagedLoadOperatorScoping:
    def test_export_page_scopes_operator_write_to_geography(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "pages" / "4_CSV_Export.py").read_text()
        idx = src.find('st.session_state["geo_operator"] = op')
        assert idx != -1, "operator restore line not found"
        window = src[max(0, idx - 500):idx]
        assert 'workflow_type' in window and 'geography' in window, (
            "geo_operator is written without scoping to the geography workflow — "
            "loading an INTENT batch would null the Geography page's operator"
        )


# ---------------------------------------------------------------------------
# N2-06 — one malformed ID must not abort the batch
# ---------------------------------------------------------------------------

class TestResolutionBatchIsolatesBadIds:
    def test_malformed_id_does_not_abort_remaining_companies(self):
        """Mirrors the page's parse loop: a bad numeric_id must skip that
        contact only. The page wraps the whole loop in one try, so an
        unguarded int() kills every remaining resolution."""
        enriched = [
            {"id": "p1", "company": {"id": 100, "name": "Acme"}},
            {"id": "p2", "company": {"id": "not-a-number", "name": "Bad"}},
            {"id": "p3", "company": {"id": 300, "name": "Gamma"}},
        ]
        pid_to_hid = {"p1": "h1", "p2": "h2", "p3": "h3"}
        numeric_map = {}
        for contact in enriched:
            hid = pid_to_hid.get(str(contact.get("id", "")))
            if not hid:
                continue
            company = contact.get("company") or {}
            numeric_id = company.get("id") or contact.get("companyId")
            if not numeric_id:
                continue
            try:
                numeric_map[hid] = int(numeric_id)
            except (TypeError, ValueError):
                continue
        assert numeric_map == {"h1": 100, "h3": 300}

    def test_page_guards_int_conversion_per_contact(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "pages" / "1_Intent_Workflow.py").read_text()
        idx = src.find("_resolution_responses = len(enriched)")
        assert idx != -1
        block = src[idx:idx + 1800]
        assert "except (TypeError, ValueError)" in block, (
            "int(numeric_id) is not guarded per-contact — one malformed id "
            "aborts the whole resolution batch"
        )


# ---------------------------------------------------------------------------
# N2-13 — do not drop the run reference when closing it failed
# ---------------------------------------------------------------------------

class TestRunReferenceRetainedOnCloseFailure:
    def test_geo_keeps_run_id_when_completion_fails(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "pages" / "2_Geography_Workflow.py").read_text()
        idx = src.find("Enrichment returned no contact data (credit/entitlement?)")
        assert idx != -1
        block = src[max(0, idx - 900):idx + 900]
        assert "_run_closed" in block, (
            "session run reference is cleared unconditionally — a failed "
            "complete_pipeline_run leaves the row 'running' with no way to retry"
        )
