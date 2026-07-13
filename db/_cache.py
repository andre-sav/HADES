"""ZoomInfo cache operations."""

import json
from datetime import datetime, timedelta, timezone


class CacheMixin:
    """Query result caching with TTL."""

    def get_cached_results(self, cache_id: str) -> list[dict] | None:
        """Get cached query results if not expired."""
        # datetime() normalizes both the SQLite-native format written now and
        # legacy local 'T'-ISO rows — a raw string compare kept expired rows
        # "fresh" through their whole expiry date ('T' > ' ', HADES-8s5).
        rows = self.execute(
            "SELECT lead_data FROM zoominfo_cache "
            "WHERE id = ? AND datetime(expires_at) > datetime('now')",
            (cache_id,),
        )
        if not rows:
            return None
        return json.loads(rows[0][0])

    def cache_results(
        self, cache_id: str, workflow_type: str, query_params: dict, leads: list[dict], ttl_days: int = 7
    ) -> None:
        """Cache query results."""
        # SQLite-native format (UTC, space separator, seconds precision) so
        # comparisons against datetime('now') are exact (HADES-8s5).
        expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).strftime("%Y-%m-%d %H:%M:%S")
        self.execute_write(
            "INSERT OR REPLACE INTO zoominfo_cache "
            "(id, workflow_type, query_params, lead_data, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                cache_id,
                workflow_type,
                json.dumps(query_params),
                json.dumps(leads),
                expires_at,
            ),
        )

    def clear_expired_cache(self) -> int:
        """Remove expired cache entries. Returns count deleted."""
        # Count before delete
        rows = self.execute(
            "SELECT COUNT(*) FROM zoominfo_cache WHERE datetime(expires_at) <= datetime('now')"
        )
        count = rows[0][0] if rows else 0

        if count > 0:
            self.execute_write("DELETE FROM zoominfo_cache WHERE datetime(expires_at) <= datetime('now')")

        return count

    def get_cache_stats(self) -> dict:
        """Get cache health statistics."""
        rows = self.execute(
            "SELECT COUNT(*) as total, "
            "MIN(created_at) as oldest, "
            "MAX(created_at) as newest, "
            "SUM(CASE WHEN datetime(expires_at) > datetime('now') THEN 1 ELSE 0 END) as active "
            "FROM zoominfo_cache"
        )
        if rows and rows[0][0]:
            return {
                "total": rows[0][0],
                "oldest": rows[0][1],
                "newest": rows[0][2],
                "active": rows[0][3] or 0,
            }
        return {"total": 0, "oldest": None, "newest": None, "active": 0}
