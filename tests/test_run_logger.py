"""Tests for RunLogger event collection."""
import json
import time

from db._pipeline import RunLogger


class TestRunLogger:
    def test_info_event(self):
        rl = RunLogger()
        rl.info("Contact Search: 45 contacts")
        assert len(rl.events) == 1
        assert rl.events[0]["level"] == "info"
        assert rl.events[0]["msg"] == "Contact Search: 45 contacts"
        assert "ts" in rl.events[0]

    def test_warn_event(self):
        rl = RunLogger()
        rl.warn("2 companies not found")
        assert rl.events[0]["level"] == "warn"

    def test_error_event_with_detail(self):
        rl = RunLogger()
        rl.error("Push failed", detail="HTTP 500: Internal Server Error")
        assert rl.events[0]["level"] == "error"
        assert rl.events[0]["detail"] == "HTTP 500: Internal Server Error"

    def test_error_event_without_detail(self):
        rl = RunLogger()
        rl.error("Something broke")
        assert "detail" not in rl.events[0]

    def test_set_metric(self):
        rl = RunLogger()
        rl.set_metric("contacts_searched", 45)
        rl.set_metric("companies_enriched", 28)
        assert rl.metrics == {"contacts_searched": 45, "companies_enriched": 28}

    def test_to_summary_combines_events_and_metrics(self):
        rl = RunLogger()
        rl.info("Step 1 done")
        rl.set_metric("contacts_searched", 10)
        summary = rl.to_summary()
        assert "log_events" in summary
        assert len(summary["log_events"]) == 1
        assert summary["contacts_searched"] == 10

    def test_to_summary_includes_duration(self):
        rl = RunLogger()
        time.sleep(0.05)
        summary = rl.to_summary()
        assert "duration_seconds" in summary
        assert summary["duration_seconds"] >= 0

    def test_has_errors(self):
        rl = RunLogger()
        assert rl.has_errors is False
        rl.error("broke")
        assert rl.has_errors is True

    def test_summary_is_json_serializable(self):
        rl = RunLogger()
        rl.info("Intent search: 15 results")
        rl.set_metric("intent_results", 15)
        rl.warn("2 stale signals")
        summary = rl.to_summary()
        serialized = json.dumps(summary)
        parsed = json.loads(serialized)
        assert parsed["intent_results"] == 15
        assert len(parsed["log_events"]) == 2
