"""Operator CRUD operations."""


class OperatorsMixin:
    """Vending operator management."""

    def get_operators(self) -> list[dict]:
        """Get all operators."""
        rows = self.execute(
            "SELECT id, operator_name, vending_business_name, operator_phone, "
            "operator_email, operator_zip, operator_website, team, zoho_id, synced_at, created_at "
            "FROM operators ORDER BY operator_name"
        )
        return [
            {
                "id": r[0],
                "operator_name": r[1],
                "vending_business_name": r[2],
                "operator_phone": r[3],
                "operator_email": r[4],
                "operator_zip": r[5],
                "operator_website": r[6],
                "team": r[7],
                "zoho_id": r[8],
                "synced_at": r[9],
                "created_at": r[10],
            }
            for r in rows
        ]

    def search_operators(self, query: str = "", limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        """Search operators with SQL-level filtering and pagination.

        Returns (operators, total_count) tuple.
        """
        _cols = ("id, operator_name, vending_business_name, operator_phone, "
                 "operator_email, operator_zip, operator_website, team, zoho_id, synced_at, created_at")
        if query:
            like = f"%{query}%"
            where = ("WHERE operator_name LIKE ? OR vending_business_name LIKE ? "
                     "OR operator_phone LIKE ? OR operator_email LIKE ? "
                     "OR operator_zip LIKE ? OR operator_website LIKE ?")
            params = (like, like, like, like, like, like)
            count_rows = self.execute(f"SELECT COUNT(*) FROM operators {where}", params)
            total = count_rows[0][0] if count_rows else 0
            rows = self.execute(
                f"SELECT {_cols} FROM operators {where} ORDER BY operator_name LIMIT ? OFFSET ?",
                (*params, limit, offset),
            )
        else:
            count_rows = self.execute("SELECT COUNT(*) FROM operators")
            total = count_rows[0][0] if count_rows else 0
            rows = self.execute(
                f"SELECT {_cols} FROM operators ORDER BY operator_name LIMIT ? OFFSET ?",
                (limit, offset),
            )
        operators = [
            {
                "id": r[0], "operator_name": r[1], "vending_business_name": r[2],
                "operator_phone": r[3], "operator_email": r[4], "operator_zip": r[5],
                "operator_website": r[6], "team": r[7], "zoho_id": r[8],
                "synced_at": r[9], "created_at": r[10],
            }
            for r in rows
        ]
        return operators, total

    def get_operator(self, operator_id: int) -> dict | None:
        """Get operator by ID."""
        rows = self.execute(
            "SELECT id, operator_name, vending_business_name, operator_phone, "
            "operator_email, operator_zip, operator_website, team, zoho_id, synced_at "
            "FROM operators WHERE id = ?",
            (operator_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0],
            "operator_name": r[1],
            "vending_business_name": r[2],
            "operator_phone": r[3],
            "operator_email": r[4],
            "operator_zip": r[5],
            "operator_website": r[6],
            "team": r[7],
            "zoho_id": r[8],
            "synced_at": r[9],
        }

    def create_operator(self, **kwargs) -> int:
        """Create new operator."""
        return self.execute_write(
            "INSERT INTO operators (operator_name, vending_business_name, operator_phone, "
            "operator_email, operator_zip, operator_website, team) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                kwargs.get("operator_name"),
                kwargs.get("vending_business_name"),
                kwargs.get("operator_phone"),
                kwargs.get("operator_email"),
                kwargs.get("operator_zip"),
                kwargs.get("operator_website"),
                kwargs.get("team"),
            ),
        )

    def update_operator(self, operator_id: int, **kwargs) -> None:
        """Update operator."""
        self.execute_write(
            "UPDATE operators SET operator_name = ?, vending_business_name = ?, "
            "operator_phone = ?, operator_email = ?, operator_zip = ?, "
            "operator_website = ?, team = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (
                kwargs.get("operator_name"),
                kwargs.get("vending_business_name"),
                kwargs.get("operator_phone"),
                kwargs.get("operator_email"),
                kwargs.get("operator_zip"),
                kwargs.get("operator_website"),
                kwargs.get("team"),
                operator_id,
            ),
        )

    def delete_operator(self, operator_id: int) -> None:
        """Delete operator."""
        self.execute_write("DELETE FROM operators WHERE id = ?", (operator_id,))
