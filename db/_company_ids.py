"""Company ID mapping cache operations."""


class CompanyIdMixin:
    """Hashed intent ID to numeric company ID cache."""

    def get_company_id(self, hashed_id: str) -> dict | None:
        """Look up cached numeric company ID from hashed intent ID."""
        rows = self.execute(
            "SELECT numeric_id, company_name FROM company_id_mapping WHERE hashed_id = ?",
            (hashed_id,),
        )
        if not rows:
            return None
        return {"numeric_id": rows[0][0], "company_name": rows[0][1]}

    def save_company_id(self, hashed_id: str, numeric_id: int, company_name: str = "") -> None:
        """Cache a hashed→numeric company ID mapping."""
        self.execute_write(
            "INSERT OR REPLACE INTO company_id_mapping (hashed_id, numeric_id, company_name, resolved_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (hashed_id, numeric_id, company_name),
        )

    def get_company_ids_bulk(self, hashed_ids: list[str]) -> dict[str, dict]:
        """Look up multiple cached company ID mappings. Returns dict of hashed_id -> {numeric_id, company_name}."""
        if not hashed_ids:
            return {}
        result = {}
        # SQLite has a max of 999 parameters per query
        batch_size = 900
        for i in range(0, len(hashed_ids), batch_size):
            batch = hashed_ids[i : i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            rows = self.execute(
                f"SELECT hashed_id, numeric_id, company_name FROM company_id_mapping WHERE hashed_id IN ({placeholders})",
                tuple(batch),
            )
            result.update({r[0]: {"numeric_id": r[1], "company_name": r[2]} for r in rows})
        return result
