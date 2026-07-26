"""Mutation audit trail for critical tables (HADES-6if).

Defends against the dominant threat in this codebase: our own code
corrupting our own data. The ZIP-centroid corruption, the Company Enrich
silent failure and the Home/Business phone inversion all had that shape —
and backups are no help, because we back up the bad data right after
writing it. This append-only log answers "what changed on operators this
morning, and what was it before?".

Append-only and best-effort by design: a logging failure must NEVER break
the write it is auditing.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Bulky columns are recorded as metadata, never verbatim — the log is for
# diagnosis, not a second copy of the payload.
_SKIP_FIELDS = {"leads_json", "push_results_json", "query_params"}


def _safe_json(payload: dict | None) -> str | None:
    """JSON-encode a state snapshot, falling back to repr for odd values."""
    if payload is None:
        return None
    try:
        return json.dumps(payload, default=repr)
    except Exception:  # pragma: no cover — default=repr makes this rare
        return json.dumps({"_unserializable": repr(payload)})


def _prune(payload: dict | None) -> dict | None:
    """Drop bulky blobs from a state snapshot."""
    if not isinstance(payload, dict):
        return payload
    return {k: v for k, v in payload.items() if k not in _SKIP_FIELDS}


class MutationLogMixin:
    """Append-only record of writes to operator/export/outcome tables."""

    def safe_snapshot(self, reader, *args):
        """Read a row's state for the audit log, returning None on failure.

        The read-back sits on the write path, so a DB hiccup here must not
        fail a write that already succeeded — auditing is never allowed to
        break the thing it audits.
        """
        try:
            return reader(*args)
        except Exception:
            logger.warning("Mutation snapshot read failed", exc_info=True)
            return None

    def log_mutation(self, table_name: str, row_id, op: str,
                     before: dict | None = None, after: dict | None = None,
                     actor: str = "app") -> None:
        """Record one mutation. Never raises.

        Args:
            table_name: table mutated (e.g. ``operators``)
            row_id: primary key of the affected row (coerced to str)
            op: ``insert`` | ``update`` | ``delete``
            before/after: state snapshots; ``None`` for insert's before and
                delete's after. Bulky blob columns are pruned.
            actor: who/what performed it (``ui``, ``script``, ``app``)
        """
        try:
            self.execute_write(
                """INSERT INTO mutation_log
                   (table_name, row_id, op, before_json, after_json, actor)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (table_name, str(row_id) if row_id is not None else None, op,
                 _safe_json(_prune(before)), _safe_json(_prune(after)), actor),
            )
        except Exception:
            # Auditing must never break the write it audits.
            logger.warning("Mutation log write failed (%s %s %s)",
                           op, table_name, row_id, exc_info=True)

    def get_recent_mutations(self, limit: int = 20,
                             table_name: str | None = None) -> list[dict]:
        """Recent mutations, newest first, optionally scoped to one table."""
        query = ("SELECT id, ts, actor, table_name, row_id, op, before_json, after_json "
                 "FROM mutation_log")
        params: tuple = ()
        if table_name:
            query += " WHERE table_name = ?"
            params = (table_name,)
        query += " ORDER BY id DESC LIMIT ?"
        params = params + (limit,)
        rows = self.execute(query, params)

        def _load(raw):
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return {"_unparseable": raw}

        return [
            {
                "id": r[0], "ts": r[1], "actor": r[2], "table_name": r[3],
                "row_id": r[4], "op": r[5],
                "before": _load(r[6]), "after": _load(r[7]),
            }
            for r in rows
        ]

    def purge_old_mutations(self, days: int = 90) -> int:
        """Delete log entries older than *days*. Returns count deleted."""
        rows = self.execute(
            "SELECT COUNT(*) FROM mutation_log WHERE ts < datetime('now', ?)",
            (f"-{days} days",),
        )
        count = rows[0][0] if rows else 0
        if count > 0:
            self.execute_write(
                "DELETE FROM mutation_log WHERE ts < datetime('now', ?)",
                (f"-{days} days",),
            )
        return count
