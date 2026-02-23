"""Sync metadata key-value operations."""


class MetadataMixin:
    """Read/write sync_metadata key-value pairs."""

    def get_sync_value(self, key: str) -> str | None:
        """Get a sync metadata value by key, or None if not found."""
        rows = self.execute(
            "SELECT value FROM sync_metadata WHERE key = ?", (key,)
        )
        if rows and rows[0][0] is not None:
            return rows[0][0]
        return None

    def set_sync_value(self, key: str, value: str) -> None:
        """Set a sync metadata value (upsert)."""
        self.execute_write(
            """INSERT INTO sync_metadata (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                   updated_at = CURRENT_TIMESTAMP""",
            (key, value),
        )
