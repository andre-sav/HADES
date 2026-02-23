"""Query history operations."""

import json


class QueryHistoryMixin:
    """Search query audit log."""

    def log_query(
        self, workflow_type: str, query_params: dict, leads_returned: int, leads_exported: int = 0
    ) -> None:
        """Log a query execution."""
        self.execute_write(
            "INSERT INTO query_history (workflow_type, query_params, leads_returned, leads_exported) "
            "VALUES (?, ?, ?, ?)",
            (workflow_type, json.dumps(query_params), leads_returned, leads_exported),
        )

    def get_recent_queries(self, limit: int = 10) -> list[dict]:
        """Get recent query history."""
        rows = self.execute(
            "SELECT id, workflow_type, query_params, leads_returned, leads_exported, created_at "
            "FROM query_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "workflow_type": r[1],
                "query_params": json.loads(r[2]) if r[2] else {},
                "leads_returned": r[3],
                "leads_exported": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def get_queries_by_date_range(
        self, start_date: str, end_date: str, workflow_type: str | None = None
    ) -> list[dict]:
        """Get query history within a date range.

        Args:
            start_date: ISO date string (YYYY-MM-DD)
            end_date: ISO date string (YYYY-MM-DD), inclusive
            workflow_type: Optional filter by workflow type
        """
        if workflow_type:
            rows = self.execute(
                "SELECT id, workflow_type, query_params, leads_returned, leads_exported, created_at "
                "FROM query_history WHERE created_at >= ? AND created_at < date(?, '+1 day') "
                "AND workflow_type = ? ORDER BY created_at DESC",
                (start_date, end_date, workflow_type),
            )
        else:
            rows = self.execute(
                "SELECT id, workflow_type, query_params, leads_returned, leads_exported, created_at "
                "FROM query_history WHERE created_at >= ? AND created_at < date(?, '+1 day') "
                "ORDER BY created_at DESC",
                (start_date, end_date),
            )
        return [
            {
                "id": r[0],
                "workflow_type": r[1],
                "query_params": json.loads(r[2]) if r[2] else {},
                "leads_returned": r[3],
                "leads_exported": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def get_last_query(self, workflow_type: str) -> dict | None:
        """Get the most recent query for a specific workflow type."""
        rows = self.execute(
            "SELECT id, workflow_type, query_params, leads_returned, leads_exported, created_at "
            "FROM query_history WHERE workflow_type = ? ORDER BY created_at DESC LIMIT 1",
            (workflow_type,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0],
            "workflow_type": r[1],
            "query_params": json.loads(r[2]) if r[2] else {},
            "leads_returned": r[3],
            "leads_exported": r[4],
            "created_at": r[5],
        }

    def update_query_exported(self, query_id: int, leads_exported: int) -> None:
        """Update the leads_exported count for a query."""
        self.execute_write(
            "UPDATE query_history SET leads_exported = ? WHERE id = ?",
            (leads_exported, query_id),
        )
