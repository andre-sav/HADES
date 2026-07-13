"""VanillaSoft lead-history operations (HADES-dio).

The vanillasoft_leads table mirrors the VS contact export so export
dedup can see leads created outside HADES. Keyed on VS ContactID
(verified unique across the full 294k-row export) so re-imports are
idempotent.
"""

from datetime import datetime, timezone


class VsLeadsMixin:
    """VanillaSoft lead-history storage and dedup index."""

    def upsert_vs_leads_batch(self, rows: list[dict]) -> None:
        """Idempotent batch upsert of parsed VS export rows (vs_leads.parse_vs_export)."""
        if not rows:
            return
        # Bound param, not inline CURRENT_TIMESTAMP: execute_many's multi-row
        # INSERT rebuilds the VALUES clause from the tuple length and would
        # drop any inline SQL default.
        imported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        params = [
            (
                r["contact_id"],
                r["company_name"],
                r["company_norm"],
                r["phone_business"],
                r["phone_mobile"],
                r["phone_home"],
                r["zip"],
                r["state"],
                r["lead_status"],
                r["added_date"],
                1 if r["is_hades"] else 0,
                r["list_source"],
                imported_at,
            )
            for r in rows
        ]
        self.execute_many(
            """INSERT OR REPLACE INTO vanillasoft_leads
               (contact_id, company_name, company_norm, phone_business,
                phone_mobile, phone_home, zip, state, lead_status,
                added_date, is_hades, list_source, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            params,
        )

    def get_vs_dedup_index(self, days_back: int = 365) -> list[dict]:
        """VS leads added within the last N days, for export dedup.

        Excludes HADES-pushed rows (is_hades = 1) — those already exist in
        lead_outcomes and counting them here would double-report the source.
        The age cutoff IS the re-contact rule: leads older than days_back
        are callable again (rep-calibrated: age dominates status).
        """
        rows = self.execute(
            """SELECT company_name, company_norm, phone_business, phone_mobile,
                      phone_home, zip, state, lead_status, added_date
               FROM vanillasoft_leads
               WHERE is_hades = 0
                 AND added_date >= datetime('now', ?)""",
            (f"-{days_back} days",),
        )
        return [
            {
                "company_name": r[0],
                "company_norm": r[1],
                "phone_business": r[2],
                "phone_mobile": r[3],
                "phone_home": r[4],
                "zip": r[5],
                "state": r[6],
                "lead_status": r[7],
                "added_date": r[8],
            }
            for r in rows
        ]

    def get_vs_leads_stats(self) -> dict:
        """Totals for the health/upload UI."""
        rows = self.execute(
            """SELECT COUNT(*),
                      SUM(CASE WHEN is_hades = 1 THEN 1 ELSE 0 END),
                      MAX(added_date)
               FROM vanillasoft_leads"""
        )
        total, hades, latest = rows[0] if rows else (0, 0, None)
        return {
            "total": total or 0,
            "hades": hades or 0,
            "latest_added": latest,
        }
