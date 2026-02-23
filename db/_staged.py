"""Staged export operations."""

import json
import logging

logger = logging.getLogger(__name__)


class StagedExportsMixin:
    """Persisted leads for CSV re-export and VanillaSoft push tracking."""

    def save_staged_export(
        self, workflow_type: str, leads: list[dict],
        query_params: dict | None = None, operator_id: int | None = None,
    ) -> int:
        """Persist leads for later CSV re-export. Returns the row id."""
        return self.execute_write(
            "INSERT INTO staged_exports (workflow_type, leads_json, lead_count, query_params, operator_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                workflow_type,
                json.dumps(leads),
                len(leads),
                json.dumps(query_params) if query_params else None,
                operator_id,
            ),
        )

    def get_staged_exports(self, limit: int = 10) -> list[dict]:
        """Get recent staged exports (newest first)."""
        rows = self.execute(
            "SELECT id, workflow_type, lead_count, query_params, operator_id, "
            "batch_id, exported_at, created_at, push_status "
            "FROM staged_exports ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "workflow_type": r[1],
                "lead_count": r[2],
                "query_params": json.loads(r[3]) if r[3] else {},
                "operator_id": r[4],
                "batch_id": r[5],
                "exported_at": r[6],
                "created_at": r[7],
                "push_status": r[8],
            }
            for r in rows
        ]

    def get_staged_export(self, export_id: int) -> dict | None:
        """Get a single staged export with parsed leads."""
        rows = self.execute(
            "SELECT id, workflow_type, leads_json, lead_count, query_params, "
            "operator_id, batch_id, exported_at, created_at, "
            "push_status, pushed_at, push_results_json "
            "FROM staged_exports WHERE id = ?",
            (export_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0],
            "workflow_type": r[1],
            "leads": json.loads(r[2]),
            "lead_count": r[3],
            "query_params": json.loads(r[4]) if r[4] else {},
            "operator_id": r[5],
            "batch_id": r[6],
            "exported_at": r[7],
            "created_at": r[8],
            "push_status": r[9],
            "pushed_at": r[10],
            "push_results_json": r[11],
        }

    def get_recent_operator_ids(self, limit: int = 5) -> list[int]:
        """Get operator IDs recently used in exports (most recent first, deduplicated)."""
        rows = self.execute(
            "SELECT DISTINCT operator_id FROM staged_exports "
            "WHERE operator_id IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [r[0] for r in rows]

    def mark_staged_exported(self, export_id: int, batch_id: str) -> None:
        """Mark a staged export as exported with batch ID and timestamp."""
        self.execute_write(
            "UPDATE staged_exports SET batch_id = ?, exported_at = CURRENT_TIMESTAMP WHERE id = ?",
            (batch_id, export_id),
        )

    def mark_staged_pushed(self, export_id: int, push_status: str, push_results_json: str) -> None:
        """Record push results on a staged export."""
        self.execute_write(
            "UPDATE staged_exports SET push_status = ?, pushed_at = CURRENT_TIMESTAMP, push_results_json = ? WHERE id = ?",
            (push_status, push_results_json, export_id),
        )

    def purge_old_staged_exports(self, days: int = 90) -> int:
        """Remove staged exports older than N days (PII retention). Returns count purged."""
        rows = self.execute(
            "SELECT COUNT(*) FROM staged_exports WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        count = rows[0][0] if rows else 0

        if count > 0:
            self.execute_write(
                "DELETE FROM staged_exports WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            logger.info(f"Purged {count} staged exports older than {days} days")

        return count
