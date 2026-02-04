"""
Credit usage tracking and budget controls for ZoomInfo API queries.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from utils import get_budget_config


class BudgetExceededError(Exception):
    """Raised when a query would exceed the budget cap."""

    def __init__(self, workflow_type: str, current_usage: int, cap: int, requested: int):
        self.workflow_type = workflow_type
        self.current_usage = current_usage
        self.cap = cap
        self.requested = requested
        self.remaining = cap - current_usage

        super().__init__(
            f"{workflow_type} budget would be exceeded. "
            f"Current: {current_usage}, Cap: {cap}, Requested: {requested}, "
            f"Remaining: {self.remaining}"
        )


@dataclass
class BudgetStatus:
    """Current budget status for a workflow."""

    workflow_type: str
    weekly_cap: int | None
    current_usage: int
    remaining: int | None
    usage_percent: float | None
    alert_level: str | None  # "warning", "critical", "exceeded", or None
    alert_message: str | None


@dataclass
class UsageSummary:
    """Summary of credit usage."""

    total_credits: int
    total_leads: int
    total_queries: int
    by_workflow: dict[str, dict]


class CostTracker:
    """
    Tracks credit usage and enforces budget caps.
    """

    def __init__(self, db):
        """
        Initialize cost tracker.

        Args:
            db: TursoDatabase instance
        """
        self.db = db

    def estimate_cost(self, estimated_results: int) -> int:
        """
        Estimate credit cost for a query.

        Args:
            estimated_results: Estimated number of results

        Returns:
            Estimated credits (1 credit per result)
        """
        return estimated_results

    def check_budget(self, workflow_type: str, estimated_credits: int) -> BudgetStatus:
        """
        Check if a query would exceed the budget.

        Args:
            workflow_type: "intent" or "geography"
            estimated_credits: Estimated credits for the query

        Returns:
            BudgetStatus with current state and any warnings
        """
        budget_config = get_budget_config(workflow_type)
        weekly_cap = budget_config.get("weekly_cap")
        current_usage = self.db.get_weekly_usage(workflow_type)

        # No cap for this workflow
        if weekly_cap is None:
            return BudgetStatus(
                workflow_type=workflow_type,
                weekly_cap=None,
                current_usage=current_usage,
                remaining=None,
                usage_percent=None,
                alert_level=None,
                alert_message=None,
            )

        remaining = weekly_cap - current_usage
        usage_percent = (current_usage / weekly_cap) * 100 if weekly_cap > 0 else 0

        # Check if query would exceed cap
        if estimated_credits > remaining:
            return BudgetStatus(
                workflow_type=workflow_type,
                weekly_cap=weekly_cap,
                current_usage=current_usage,
                remaining=remaining,
                usage_percent=usage_percent,
                alert_level="exceeded",
                alert_message=f"Query would exceed weekly cap. "
                f"Remaining: {remaining} credits, Requested: {estimated_credits} credits.",
            )

        # Check alert thresholds
        alert_thresholds = budget_config.get("alerts", [])
        projected_usage = current_usage + estimated_credits
        projected_percent = (projected_usage / weekly_cap) * 100 if weekly_cap > 0 else 0

        alert_level = None
        alert_message = None

        for threshold in sorted(alert_thresholds, reverse=True):
            threshold_percent = threshold * 100
            if projected_percent >= threshold_percent:
                if threshold >= 0.95:
                    alert_level = "critical"
                    alert_message = f"This query will use {projected_percent:.0f}% of weekly budget."
                elif threshold >= 0.80:
                    alert_level = "warning"
                    alert_message = f"This query will use {projected_percent:.0f}% of weekly budget."
                else:
                    alert_level = "info"
                    alert_message = f"This query will use {projected_percent:.0f}% of weekly budget."
                break

        return BudgetStatus(
            workflow_type=workflow_type,
            weekly_cap=weekly_cap,
            current_usage=current_usage,
            remaining=remaining,
            usage_percent=usage_percent,
            alert_level=alert_level,
            alert_message=alert_message,
        )

    def can_execute_query(self, workflow_type: str, estimated_credits: int) -> bool:
        """
        Check if a query can be executed within budget.

        Args:
            workflow_type: "intent" or "geography"
            estimated_credits: Estimated credits for the query

        Returns:
            True if query can proceed, False if it would exceed cap
        """
        status = self.check_budget(workflow_type, estimated_credits)
        return status.alert_level != "exceeded"

    def enforce_budget(self, workflow_type: str, estimated_credits: int) -> None:
        """
        Enforce budget cap, raising exception if exceeded.

        Args:
            workflow_type: "intent" or "geography"
            estimated_credits: Estimated credits for the query

        Raises:
            BudgetExceededError: If query would exceed cap
        """
        budget_config = get_budget_config(workflow_type)
        weekly_cap = budget_config.get("weekly_cap")

        if weekly_cap is None:
            return  # No cap to enforce

        current_usage = self.db.get_weekly_usage(workflow_type)
        remaining = weekly_cap - current_usage

        if estimated_credits > remaining:
            raise BudgetExceededError(
                workflow_type=workflow_type,
                current_usage=current_usage,
                cap=weekly_cap,
                requested=estimated_credits,
            )

    def log_usage(
        self,
        workflow_type: str,
        query_params: dict,
        credits_used: int,
        leads_returned: int,
    ) -> None:
        """
        Log credit usage for a completed query.

        Args:
            workflow_type: "intent" or "geography"
            query_params: Query parameters (for audit trail)
            credits_used: Actual credits consumed
            leads_returned: Number of leads returned
        """
        self.db.log_credit_usage(
            workflow_type=workflow_type,
            query_params=query_params,
            credits_used=credits_used,
            leads_returned=leads_returned,
        )

    def get_budget_status(self, workflow_type: str) -> BudgetStatus:
        """
        Get current budget status without checking a specific query.

        Args:
            workflow_type: "intent" or "geography"

        Returns:
            BudgetStatus with current state
        """
        return self.check_budget(workflow_type, estimated_credits=0)

    def get_usage_summary(self, days: int = 7) -> UsageSummary:
        """
        Get usage summary for the specified period.

        Args:
            days: Number of days to look back

        Returns:
            UsageSummary with totals and breakdown by workflow
        """
        summary_data = self.db.get_usage_summary(days)

        total_credits = 0
        total_leads = 0
        total_queries = 0
        by_workflow = {}

        for row in summary_data:
            workflow = row["workflow_type"]
            credits = row["credits"]
            leads = row["leads"]
            queries = row["queries"]

            total_credits += credits
            total_leads += leads
            total_queries += queries

            by_workflow[workflow] = {
                "credits": credits,
                "leads": leads,
                "queries": queries,
            }

        return UsageSummary(
            total_credits=total_credits,
            total_leads=total_leads,
            total_queries=total_queries,
            by_workflow=by_workflow,
        )

    def get_weekly_usage_by_workflow(self) -> dict[str, int]:
        """
        Get current week's usage broken down by workflow.

        Returns:
            Dict mapping workflow_type to credits used
        """
        return {
            "intent": self.db.get_weekly_usage("intent"),
            "geography": self.db.get_weekly_usage("geography"),
        }

    def format_budget_display(self, workflow_type: str) -> dict:
        """
        Get formatted budget info for UI display.

        Args:
            workflow_type: "intent" or "geography"

        Returns:
            Dict with display-ready budget information
        """
        status = self.get_budget_status(workflow_type)

        if status.weekly_cap is None:
            return {
                "has_cap": False,
                "display": "Unlimited",
                "current": status.current_usage,
                "cap": None,
                "remaining": None,
                "percent": None,
                "color": "normal",
            }

        # Determine color based on usage
        if status.usage_percent >= 95:
            color = "red"
        elif status.usage_percent >= 80:
            color = "orange"
        elif status.usage_percent >= 50:
            color = "yellow"
        else:
            color = "green"

        return {
            "has_cap": True,
            "display": f"{status.current_usage} / {status.weekly_cap} credits",
            "current": status.current_usage,
            "cap": status.weekly_cap,
            "remaining": status.remaining,
            "percent": status.usage_percent,
            "color": color,
        }
