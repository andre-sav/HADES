"""Credit usage tracking."""

import json


class UsageMixin:
    """ZoomInfo credit usage tracking."""

    def log_credit_usage(
        self, workflow_type: str, query_params: dict, credits_used: int, leads_returned: int
    ) -> None:
        """Log credit usage for a query."""
        self.execute_write(
            "INSERT INTO credit_usage (workflow_type, query_params, credits_used, leads_returned) "
            "VALUES (?, ?, ?, ?)",
            (workflow_type, json.dumps(query_params), credits_used, leads_returned),
        )

    def get_weekly_usage(self, workflow_type: str | None = None) -> int:
        """Get total credits used this week."""
        if workflow_type:
            rows = self.execute(
                "SELECT COALESCE(SUM(credits_used), 0) FROM credit_usage "
                "WHERE workflow_type = ? AND created_at >= date('now', '-7 days')",
                (workflow_type,),
            )
        else:
            rows = self.execute(
                "SELECT COALESCE(SUM(credits_used), 0) FROM credit_usage "
                "WHERE created_at >= date('now', '-7 days')"
            )
        return rows[0][0] if rows else 0

    def get_usage_summary(self, days: int = 30) -> list[dict]:
        """Get usage summary for dashboard."""
        rows = self.execute(
            "SELECT workflow_type, SUM(credits_used) as credits, "
            "SUM(leads_returned) as leads, COUNT(*) as queries "
            "FROM credit_usage WHERE created_at >= date('now', ?) "
            "GROUP BY workflow_type",
            (f"-{days} days",),
        )
        return [
            {"workflow_type": r[0], "credits": r[1], "leads": r[2], "queries": r[3]}
            for r in rows
        ]
