"""Location template operations."""

import json


class TemplatesMixin:
    """Saved ZIP radius search templates."""

    def get_location_templates(self) -> list[dict]:
        """Get all saved location templates."""
        rows = self.execute(
            "SELECT id, name, zip_codes, radius_miles FROM location_templates ORDER BY name"
        )
        return [
            {
                "id": r[0],
                "name": r[1],
                "zip_codes": json.loads(r[2]),
                "radius_miles": r[3],
            }
            for r in rows
        ]

    def save_location_template(self, name: str, zip_codes: list[str], radius_miles: int) -> int:
        """Save a location template."""
        return self.execute_write(
            "INSERT OR REPLACE INTO location_templates (name, zip_codes, radius_miles) "
            "VALUES (?, ?, ?)",
            (name, json.dumps(zip_codes), radius_miles),
        )

    def rename_location_template(self, template_id: int, new_name: str) -> None:
        """Rename a location template."""
        self.execute_write(
            "UPDATE location_templates SET name = ? WHERE id = ?",
            (new_name, template_id),
        )

    def delete_location_template(self, template_id: int) -> None:
        """Delete a location template."""
        self.execute_write("DELETE FROM location_templates WHERE id = ?", (template_id,))
