"""
Tests for cost tracking and budget controls.

Run with: pytest tests/test_cost_tracker.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from cost_tracker import (
    CostTracker,
    BudgetExceededError,
    BudgetStatus,
    UsageSummary,
)


class TestCostEstimation:
    """Tests for cost estimation."""

    def test_estimate_cost(self):
        """Test basic cost estimation (1 credit per result)."""
        tracker = CostTracker(db=MagicMock())

        assert tracker.estimate_cost(100) == 100
        assert tracker.estimate_cost(0) == 0
        assert tracker.estimate_cost(500) == 500


class TestBudgetChecking:
    """Tests for budget checking."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        return MagicMock()

    @pytest.fixture
    def tracker(self, mock_db):
        """Create tracker with mock db."""
        return CostTracker(db=mock_db)

    def test_check_budget_no_cap(self, tracker, mock_db):
        """Test budget check for workflow without cap."""
        mock_db.get_weekly_usage.return_value = 1000

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": None, "alerts": []}

            status = tracker.check_budget("geography", 500)

        assert status.weekly_cap is None
        assert status.remaining is None
        assert status.alert_level is None

    def test_check_budget_under_cap(self, tracker, mock_db):
        """Test budget check when under cap."""
        mock_db.get_weekly_usage.return_value = 100

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": [0.50, 0.80, 0.95]}

            status = tracker.check_budget("intent", 50)

        assert status.weekly_cap == 500
        assert status.current_usage == 100
        assert status.remaining == 400
        assert status.alert_level is None  # 150/500 = 30%, no alert

    def test_check_budget_at_50_percent(self, tracker, mock_db):
        """Test budget check at 50% threshold."""
        mock_db.get_weekly_usage.return_value = 200

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": [0.50, 0.80, 0.95]}

            status = tracker.check_budget("intent", 100)

        # 300/500 = 60%, should trigger 50% alert
        assert status.alert_level == "info"
        assert "60%" in status.alert_message

    def test_check_budget_at_80_percent(self, tracker, mock_db):
        """Test budget check at 80% threshold."""
        mock_db.get_weekly_usage.return_value = 350

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": [0.50, 0.80, 0.95]}

            status = tracker.check_budget("intent", 100)

        # 450/500 = 90%, should trigger 80% warning
        assert status.alert_level == "warning"

    def test_check_budget_at_95_percent(self, tracker, mock_db):
        """Test budget check at 95% threshold."""
        mock_db.get_weekly_usage.return_value = 450

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": [0.50, 0.80, 0.95]}

            status = tracker.check_budget("intent", 30)

        # 480/500 = 96%, should trigger 95% critical
        assert status.alert_level == "critical"

    def test_check_budget_exceeded(self, tracker, mock_db):
        """Test budget check when cap would be exceeded."""
        mock_db.get_weekly_usage.return_value = 450

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": [0.50, 0.80, 0.95]}

            status = tracker.check_budget("intent", 100)

        # 450 + 100 = 550 > 500
        assert status.alert_level == "exceeded"
        assert "exceed" in status.alert_message.lower()


class TestBudgetEnforcement:
    """Tests for budget enforcement."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        return MagicMock()

    @pytest.fixture
    def tracker(self, mock_db):
        """Create tracker with mock db."""
        return CostTracker(db=mock_db)

    def test_can_execute_under_budget(self, tracker, mock_db):
        """Test can_execute when under budget."""
        mock_db.get_weekly_usage.return_value = 100

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": []}

            result = tracker.can_execute_query("intent", 100)

        assert result is True

    def test_can_execute_over_budget(self, tracker, mock_db):
        """Test can_execute when over budget."""
        mock_db.get_weekly_usage.return_value = 450

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": []}

            result = tracker.can_execute_query("intent", 100)

        assert result is False

    def test_can_execute_no_cap(self, tracker, mock_db):
        """Test can_execute with no cap."""
        mock_db.get_weekly_usage.return_value = 10000

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": None, "alerts": []}

            result = tracker.can_execute_query("geography", 1000)

        assert result is True

    def test_enforce_budget_passes(self, tracker, mock_db):
        """Test enforce_budget when under cap."""
        mock_db.get_weekly_usage.return_value = 100

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": []}

            # Should not raise
            tracker.enforce_budget("intent", 100)

    def test_enforce_budget_raises(self, tracker, mock_db):
        """Test enforce_budget raises when over cap."""
        mock_db.get_weekly_usage.return_value = 450

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": []}

            with pytest.raises(BudgetExceededError) as exc_info:
                tracker.enforce_budget("intent", 100)

        assert exc_info.value.current_usage == 450
        assert exc_info.value.cap == 500
        assert exc_info.value.requested == 100
        assert exc_info.value.remaining == 50


class TestUsageLogging:
    """Tests for usage logging."""

    def test_log_usage(self):
        """Test logging credit usage."""
        mock_db = MagicMock()
        tracker = CostTracker(db=mock_db)

        tracker.log_usage(
            workflow_type="intent",
            query_params={"topic": "Vending"},
            credits_used=50,
            leads_returned=50,
        )

        mock_db.log_credit_usage.assert_called_once_with(
            workflow_type="intent",
            query_params={"topic": "Vending"},
            credits_used=50,
            leads_returned=50,
        )


class TestUsageSummary:
    """Tests for usage summary."""

    def test_get_usage_summary(self):
        """Test getting usage summary."""
        mock_db = MagicMock()
        mock_db.get_usage_summary.return_value = [
            {"workflow_type": "intent", "credits": 200, "leads": 200, "queries": 5},
            {"workflow_type": "geography", "credits": 500, "leads": 500, "queries": 10},
        ]

        tracker = CostTracker(db=mock_db)
        summary = tracker.get_usage_summary(days=7)

        assert summary.total_credits == 700
        assert summary.total_leads == 700
        assert summary.total_queries == 15
        assert summary.by_workflow["intent"]["credits"] == 200
        assert summary.by_workflow["geography"]["credits"] == 500

    def test_get_weekly_usage_by_workflow(self):
        """Test getting weekly usage by workflow."""
        mock_db = MagicMock()
        mock_db.get_weekly_usage.side_effect = lambda wf: {"intent": 150, "geography": 300}[wf]

        tracker = CostTracker(db=mock_db)
        usage = tracker.get_weekly_usage_by_workflow()

        assert usage["intent"] == 150
        assert usage["geography"] == 300


class TestBudgetDisplay:
    """Tests for budget display formatting."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        return MagicMock()

    @pytest.fixture
    def tracker(self, mock_db):
        """Create tracker with mock db."""
        return CostTracker(db=mock_db)

    def test_format_budget_no_cap(self, tracker, mock_db):
        """Test display formatting with no cap."""
        mock_db.get_weekly_usage.return_value = 500

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": None, "alerts": []}

            display = tracker.format_budget_display("geography")

        assert display["has_cap"] is False
        assert display["display"] == "Unlimited"

    def test_format_budget_green(self, tracker, mock_db):
        """Test display formatting when usage is low (green)."""
        mock_db.get_weekly_usage.return_value = 100

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": []}

            display = tracker.format_budget_display("intent")

        assert display["has_cap"] is True
        assert display["color"] == "green"
        assert display["current"] == 100
        assert display["cap"] == 500

    def test_format_budget_yellow(self, tracker, mock_db):
        """Test display formatting at 50%+ (yellow)."""
        mock_db.get_weekly_usage.return_value = 300

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": []}

            display = tracker.format_budget_display("intent")

        assert display["color"] == "yellow"

    def test_format_budget_orange(self, tracker, mock_db):
        """Test display formatting at 80%+ (orange)."""
        mock_db.get_weekly_usage.return_value = 420

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": []}

            display = tracker.format_budget_display("intent")

        assert display["color"] == "orange"

    def test_format_budget_red(self, tracker, mock_db):
        """Test display formatting at 95%+ (red)."""
        mock_db.get_weekly_usage.return_value = 480

        with patch("cost_tracker.get_budget_config") as mock_config:
            mock_config.return_value = {"weekly_cap": 500, "alerts": []}

            display = tracker.format_budget_display("intent")

        assert display["color"] == "red"
