"""Error log operations."""

import json


class ErrorLogMixin:
    """Persistent error logging for pipeline workflows."""

    def log_error(
        self,
        workflow_type: str,
        error_type: str,
        user_message: str,
        technical_message: str = "",
        recoverable: bool = True,
        context: dict | None = None,
    ) -> None:
        """Log a pipeline error to the error_log table."""
        self.execute_write(
            """INSERT INTO error_log
               (workflow_type, error_type, user_message, technical_message,
                recoverable, context_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                workflow_type,
                error_type,
                user_message,
                technical_message,
                1 if recoverable else 0,
                json.dumps(context) if context else None,
            ),
        )

    def get_recent_errors(self, limit: int = 20) -> list[dict]:
        """Get most recent errors across all workflows."""
        rows = self.execute(
            """SELECT id, workflow_type, error_type, user_message,
                      technical_message, recoverable, context_json, created_at
               FROM error_log ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        return [self._row_to_error(r) for r in rows]

    def get_errors_by_workflow(self, workflow_type: str, limit: int = 20) -> list[dict]:
        """Get recent errors for a specific workflow."""
        rows = self.execute(
            """SELECT id, workflow_type, error_type, user_message,
                      technical_message, recoverable, context_json, created_at
               FROM error_log WHERE workflow_type = ?
               ORDER BY created_at DESC LIMIT ?""",
            (workflow_type, limit),
        )
        return [self._row_to_error(r) for r in rows]

    def purge_old_error_logs(self, days: int = 90) -> int:
        """Delete error log entries older than *days*. Returns count deleted."""
        rows = self.execute(
            "SELECT COUNT(*) FROM error_log WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        count = rows[0][0] if rows else 0
        if count > 0:
            self.execute_write(
                "DELETE FROM error_log WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
        return count

    @staticmethod
    def _row_to_error(row: tuple) -> dict:
        return {
            "id": row[0],
            "workflow_type": row[1],
            "error_type": row[2],
            "user_message": row[3],
            "technical_message": row[4],
            "recoverable": bool(row[5]),
            "context_json": row[6],
            "created_at": row[7],
        }
