"""Operator CRUD operations."""


class OperatorsMixin:
    """Vending operator management."""

    def get_operators(self) -> list[dict]:
        """Get all operators."""
        rows = self.execute(
            "SELECT id, operator_name, vending_business_name, operator_phone, "
            "operator_email, operator_zip, operator_website, team, zoho_id, synced_at, created_at "
            "FROM operators WHERE deleted_at IS NULL ORDER BY operator_name"
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
            where = ("WHERE deleted_at IS NULL AND (operator_name LIKE ? "
                     "OR vending_business_name LIKE ? "
                     "OR operator_phone LIKE ? OR operator_email LIKE ? "
                     "OR operator_zip LIKE ? OR operator_website LIKE ?)")
            params = (like, like, like, like, like, like)
            count_rows = self.execute(f"SELECT COUNT(*) FROM operators {where}", params)
            total = count_rows[0][0] if count_rows else 0
            rows = self.execute(
                f"SELECT {_cols} FROM operators {where} ORDER BY operator_name LIMIT ? OFFSET ?",
                (*params, limit, offset),
            )
        else:
            count_rows = self.execute("SELECT COUNT(*) FROM operators WHERE deleted_at IS NULL")
            total = count_rows[0][0] if count_rows else 0
            rows = self.execute(
                f"SELECT {_cols} FROM operators WHERE deleted_at IS NULL ORDER BY operator_name LIMIT ? OFFSET ?",
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
        """Create new operator. Audited (HADES-6if)."""
        new_id = self.execute_write(
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
        self.log_mutation("operators", new_id, "insert", before=None,
                          after=self.safe_snapshot(self.get_operator, new_id))
        return new_id

    def update_operator(self, operator_id: int, **kwargs) -> None:
        """Update operator. Audited with before/after state (HADES-6if) —
        a wrong edit here mislabels every export under that operator."""
        before = self.safe_snapshot(self.get_operator, operator_id)
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
        self.log_mutation("operators", operator_id, "update", before=before,
                          after=self.safe_snapshot(self.get_operator, operator_id))

    def delete_operator(self, operator_id: int) -> None:
        """Soft-delete an operator — recoverable for 90 days (HADES-l3n).

        Staged-export links are deliberately NOT nullified: the row still
        exists, so severing them would make ``restore_operator`` only
        partially recoverable. List/picker queries filter deleted rows;
        by-ID lookups still resolve so historical exports keep their
        operator attribution.

        Also audited (HADES-6if) — the two defenses are complementary.
        """
        before = self.safe_snapshot(self.get_operator, operator_id)
        self.execute_write(
            "UPDATE operators SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (operator_id,),
        )
        self.log_mutation("operators", operator_id, "delete",
                          before=before, after=None)

    def restore_operator(self, operator_id: int) -> None:
        """Undo a soft delete."""
        self.execute_write(
            "UPDATE operators SET deleted_at = NULL WHERE id = ?", (operator_id,)
        )
        self.log_mutation("operators", operator_id, "update", before=None,
                          after=self.safe_snapshot(self.get_operator, operator_id))

    def find_deleted_operator_by_name(self, operator_name: str) -> dict | None:
        """Look up a SOFT-DELETED operator by name.

        ``operator_name`` carries a column-level UNIQUE constraint, so a
        soft-deleted row still reserves its name. This lets the UI detect
        that case and offer "restore" instead of surfacing a raw
        IntegrityError when someone re-adds a deleted operator.
        """
        rows = self.execute(
            "SELECT id, operator_name, deleted_at FROM operators "
            "WHERE operator_name = ? AND deleted_at IS NOT NULL",
            (operator_name,),
        )
        if not rows:
            return None
        return {"id": rows[0][0], "operator_name": rows[0][1], "deleted_at": rows[0][2]}

    def find_deleted_operator_by_zoho_id(self, zoho_id: str) -> dict | None:
        """Look up a SOFT-DELETED operator by Zoho id.

        ``zoho_id`` is UNIQUE too, and the Zoho sync upserts on it — without
        this companion a soft-deleted row silently blocks re-creation from
        Zoho with no recovery path (review N2-10).
        """
        if not zoho_id:
            return None
        rows = self.execute(
            "SELECT id, operator_name, zoho_id, deleted_at FROM operators "
            "WHERE zoho_id = ? AND deleted_at IS NOT NULL",
            (zoho_id,),
        )
        if not rows:
            return None
        return {"id": rows[0][0], "operator_name": rows[0][1],
                "zoho_id": rows[0][2], "deleted_at": rows[0][3]}
