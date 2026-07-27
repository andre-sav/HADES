"""Tests for monitoring.py — proactive ZoomInfo health detection (HADES-1d3).

These guard the "operator should not be the detector" goal from the 2026-06-15
blank-enrichment incident: the system must flag credit/entitlement exhaustion and
degraded (fieldless) enrichment batches before a human notices blank rows.
"""

import sys
from unittest.mock import MagicMock

sys.modules["libsql_experimental"] = MagicMock()

from monitoring import evaluate_usage, evaluate_enrichment_batch


def _usage(used, limit, limit_type="recordLimit"):
    return {"usage": [{
        "limitType": limit_type,
        "currentUsage": used,
        "totalLimit": limit,
        "usageRemaining": limit - used,
        "description": limit_type,
    }]}


class TestEvaluateUsage:
    def test_ok_well_under_limit(self):
        v = evaluate_usage(_usage(100, 1000))
        assert v["severity"] == "ok"

    def test_warning_near_limit(self):
        v = evaluate_usage(_usage(850, 1000), warn_pct=80, crit_pct=95)
        assert v["severity"] == "warning"
        assert any(b["limit_type"] == "recordLimit" for b in v["breaches"])

    def test_critical_at_limit(self):
        v = evaluate_usage(_usage(990, 1000), warn_pct=80, crit_pct=95)
        assert v["severity"] == "critical"

    def test_most_severe_limit_wins(self):
        # One limit fine, one critical → overall critical.
        usage = {"usage": [
            {"limitType": "requestLimit", "currentUsage": 10, "totalLimit": 1000, "usageRemaining": 990},
            {"limitType": "recordLimit", "currentUsage": 999, "totalLimit": 1000, "usageRemaining": 1},
        ]}
        v = evaluate_usage(usage, warn_pct=80, crit_pct=95)
        assert v["severity"] == "critical"

    def test_error_response_is_unknown_not_ok(self):
        # An API error must NOT be reported as healthy.
        v = evaluate_usage({"error": "401 unauthorized"})
        assert v["severity"] == "unknown"

    def test_empty_usage_is_unknown_not_ok(self):
        v = evaluate_usage({"usage": []})
        assert v["severity"] == "unknown"

    def test_zero_limit_ignored(self):
        # totalLimit 0 means "no limit / unknown" — must not divide-by-zero or false-alarm.
        v = evaluate_usage(_usage(50, 0))
        assert v["severity"] in ("ok", "unknown")


class TestEvaluateEnrichmentBatch:
    def test_all_fieldless_is_critical(self):
        v = evaluate_enrichment_batch([{}, {}, {"personId": "1", "id": "1"}])
        assert v["severity"] == "critical"
        assert v["empty"] == 3
        assert v["fraction"] == 1.0

    def test_majority_fieldless_is_warning(self):
        records = [{}, {}, {"firstName": "Real", "lastName": "Lead"}]
        v = evaluate_enrichment_batch(records, empty_fraction_threshold=0.5)
        assert v["severity"] == "warning"

    def test_healthy_batch_is_ok(self):
        records = [{"firstName": "A", "lastName": "B"}, {"phone": "(555) 123-4567"}]
        v = evaluate_enrichment_batch(records)
        assert v["severity"] == "ok"
        assert v["empty"] == 0

    def test_empty_input_is_ok(self):
        v = evaluate_enrichment_batch([])
        assert v["severity"] == "ok"
        assert v["fraction"] == 0.0
