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
        """Persist leads for later CSV re-export. Returns the row id.

        Audited (HADES-6if) — the lead payload itself is NOT copied into
        the log, only its shape (see _mutation_log._SKIP_FIELDS).
        """
        new_id = self.execute_write(
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
        self.log_mutation(
            "staged_exports", new_id, "insert", before=None,
            after={"workflow_type": workflow_type, "lead_count": len(leads),
                   "operator_id": operator_id},
        )
        return new_id

    def get_staged_exports(self, limit: int = 10) -> list[dict]:
        """Get recent staged exports (newest first)."""
        rows = self.execute(
            "SELECT id, workflow_type, lead_count, query_params, operator_id, "
            "batch_id, exported_at, created_at, push_status "
            "FROM staged_exports WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT ?",
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
        # GROUP BY + MAX: DISTINCT + ORDER BY created_at sorts each operator
        # by an ARBITRARY retained row (observed: the oldest), pushing recently
        # re-used operators out of the list (HADES-7qi).
        rows = self.execute(
            # Excludes soft-deleted operators AND exports (HADES-l3n) —
            # a deleted operator must not resurface in the recent picker.
            "SELECT s.operator_id FROM staged_exports s "
            "JOIN operators o ON o.id = s.operator_id "
            "WHERE s.operator_id IS NOT NULL "
            "AND s.deleted_at IS NULL AND o.deleted_at IS NULL "
            "GROUP BY s.operator_id "
            "ORDER BY MAX(s.created_at) DESC LIMIT ?",
            (limit,),
        )
        return [r[0] for r in rows]

    def mark_staged_exported(self, export_id: int, batch_id: str) -> None:
        """Mark a staged export as exported with batch ID and timestamp."""
        self.execute_write(
            "UPDATE staged_exports SET batch_id = ?, exported_at = CURRENT_TIMESTAMP WHERE id = ?",
            (batch_id, export_id),
        )
        self.log_mutation("staged_exports", export_id, "update",
                          before=None, after={"batch_id": batch_id, "exported": True})

    def mark_staged_pushed(self, export_id: int, push_status: str, push_results_json: str) -> None:
        """Record push results on a staged export."""
        self.execute_write(
            "UPDATE staged_exports SET push_status = ?, pushed_at = CURRENT_TIMESTAMP, push_results_json = ? WHERE id = ?",
            (push_status, push_results_json, export_id),
        )
        self.log_mutation("staged_exports", export_id, "update",
                          before=None, after={"push_status": push_status})

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

    def delete_staged_export(self, export_id: int) -> None:
        """Soft-delete a staged export — recoverable for 90 days (HADES-l3n)."""
        self.execute_write(
            "UPDATE staged_exports SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (export_id,),
        )
        self.log_mutation("staged_exports", export_id, "delete",
                          before=None, after=None)

    def purge_soft_deleted(self, days: int = 90) -> dict:
        """Hard-delete rows soft-deleted more than *days* ago.

        The end of the recovery window. Only ever touches rows with a
        non-NULL deleted_at, so live data can never be caught by it —
        including when days=0.
        """
        result = {}
        for table in ("operators", "staged_exports"):
            rows = self.execute(
                f"SELECT COUNT(*) FROM {table} "
                "WHERE deleted_at IS NOT NULL AND deleted_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            count = rows[0][0] if rows else 0
            if count:
                self.execute_write(
                    f"DELETE FROM {table} "
                    "WHERE deleted_at IS NOT NULL AND deleted_at < datetime('now', ?)",
                    (f"-{days} days",),
                )
            result[table] = count
        return result
