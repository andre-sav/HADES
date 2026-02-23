"""Pipeline automation run operations."""

import json


class PipelineRunsMixin:
    """Automated pipeline run tracking."""

    def start_pipeline_run(
        self, workflow_type: str, trigger: str, config: dict,
    ) -> int:
        """Record start of an automated pipeline run. Returns the row id."""
        return self.execute_write(
            "INSERT INTO pipeline_runs (workflow_type, trigger, status, config_json, started_at) "
            "VALUES (?, ?, 'running', ?, CURRENT_TIMESTAMP)",
            (workflow_type, trigger, json.dumps(config)),
        )

    def complete_pipeline_run(
        self, run_id: int, status: str, summary: dict,
        batch_id: str | None, credits_used: int, leads_exported: int,
        error: str | None,
    ) -> None:
        """Update a pipeline run with completion details."""
        self.execute_write(
            """UPDATE pipeline_runs
               SET status = ?, summary_json = ?, batch_id = ?,
                   credits_used = ?, leads_exported = ?,
                   error_message = ?, completed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (status, json.dumps(summary), batch_id, credits_used,
             leads_exported, error, run_id),
        )

    def get_pipeline_runs(self, workflow_type: str, limit: int = 20) -> list[dict]:
        """Get recent pipeline runs (newest first)."""
        rows = self.execute(
            "SELECT id, workflow_type, trigger, status, config_json, summary_json, "
            "batch_id, credits_used, leads_exported, error_message, "
            "started_at, completed_at, created_at "
            "FROM pipeline_runs WHERE workflow_type = ? "
            "ORDER BY id DESC LIMIT ?",
            (workflow_type, limit),
        )
        return [
            {
                "id": r[0],
                "workflow_type": r[1],
                "trigger": r[2],
                "status": r[3],
                "config": json.loads(r[4]) if r[4] else {},
                "summary": json.loads(r[5]) if r[5] else {},
                "batch_id": r[6],
                "credits_used": r[7],
                "leads_exported": r[8],
                "error_message": r[9],
                "started_at": r[10],
                "completed_at": r[11],
                "created_at": r[12],
            }
            for r in rows
        ]

    def has_running_pipeline(self, workflow_type: str) -> bool:
        """Check if any pipeline run is currently in 'running' status."""
        rows = self.execute(
            "SELECT id FROM pipeline_runs WHERE workflow_type = ? AND status = 'running' LIMIT 1",
            (workflow_type,),
        )
        return len(rows) > 0
