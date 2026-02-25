"""Lead outcome tracking operations."""

import json


class OutcomesMixin:
    """Lead outcome recording and calibration data."""

    @staticmethod
    def build_outcome_row(
        lead: dict,
        batch_id: str,
        workflow_type: str,
        exported_at: str,
        source_features: str | None = None,
    ) -> tuple:
        """Build a lead outcome tuple for record_lead_outcomes_batch.

        Handles field name variations across Contact Search, Intent, and Enrich APIs
        with a consistent superset of fallbacks.
        """
        co = lead.get("company") if isinstance(lead.get("company"), dict) else {}

        cid = lead.get("companyId") or co.get("id", "")
        pid = lead.get("personId") or lead.get("id", "")

        return (
            batch_id,
            lead.get("companyName", "") or co.get("name", ""),
            str(cid) if cid else None,
            str(pid) if pid else None,
            lead.get("sicCode") or lead.get("_sic_code") or co.get("sicCode"),
            lead.get("employeeCount") or lead.get("employees") or lead.get("numberOfEmployees") or co.get("employeeCount"),
            lead.get("_distance_miles"),
            lead.get("zip") or lead.get("zipCode") or co.get("zip"),
            lead.get("state") or co.get("state"),
            lead.get("_score", 0),
            workflow_type,
            exported_at,
            source_features,
        )

    def record_lead_outcomes_batch(self, params_list: list[tuple]) -> None:
        """Batch INSERT lead outcomes. Each tuple:
        (batch_id, company_name, company_id, person_id, sic_code, employee_count,
         distance_miles, zip_code, state, hades_score, workflow_type,
         exported_at, source_features)
        """
        self.execute_many(
            """INSERT OR IGNORE INTO lead_outcomes
               (batch_id, company_name, company_id, person_id, sic_code, employee_count,
                distance_miles, zip_code, state, hades_score, workflow_type,
                exported_at, source_features)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            params_list,
        )

    def get_outcomes_by_batch(self, batch_id: str) -> list[dict]:
        """Get all lead outcomes for a batch (includes person_id and company_id)."""
        rows = self.execute(
            """SELECT id, batch_id, company_name, company_id, person_id,
                      sic_code, employee_count, hades_score, workflow_type,
                      exported_at, outcome, outcome_at, zip_code, state
               FROM lead_outcomes WHERE batch_id = ?
               ORDER BY id""",
            (batch_id,),
        )
        return [
            {
                "id": r[0], "batch_id": r[1], "company_name": r[2],
                "company_id": r[3], "person_id": r[4],
                "sic_code": r[5], "employee_count": r[6], "hades_score": r[7],
                "workflow_type": r[8], "exported_at": r[9], "outcome": r[10],
                "outcome_at": r[11], "zip_code": r[12], "state": r[13],
            }
            for r in rows
        ]

    def get_all_outcomes_for_calibration(self) -> list[dict]:
        """UNION query across historical_outcomes and lead_outcomes for calibration.

        Returns normalized rows with: company_name, sic_code, employee_count,
        zip_code, state, outcome, source ('historical' or 'hades').
        """
        rows = self.execute(
            """SELECT company_name, sic_code, employee_count, zip_code, state,
                      outcome, 'historical' AS source
               FROM historical_outcomes
               UNION ALL
               SELECT company_name, sic_code, employee_count, zip_code, state,
                      outcome, 'hades' AS source
               FROM lead_outcomes
               WHERE outcome IS NOT NULL"""
        )
        return [
            {
                "company_name": r[0], "sic_code": r[1], "employee_count": r[2],
                "zip_code": r[3], "state": r[4], "outcome": r[5], "source": r[6],
            }
            for r in rows
        ]

    def get_historical_count(self) -> int:
        """Count rows in historical_outcomes (for idempotent import check)."""
        rows = self.execute("SELECT COUNT(*) FROM historical_outcomes")
        return rows[0][0] if rows else 0

    def insert_historical_outcomes_batch(self, params_list: list[tuple]) -> None:
        """Batch INSERT historical outcomes. Each tuple:
        (company_name, sic_code, employee_count, zip_code, state,
         outcome, source_file, created_at, imported_at)
        """
        self.execute_many(
            """INSERT INTO historical_outcomes
               (company_name, sic_code, employee_count, zip_code, state,
                outcome, source_file, created_at, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            params_list,
        )

    def get_recent_batches(self, limit: int = 10) -> list[dict]:
        """Get recent export batches with outcome summary."""
        rows = self.execute(
            """SELECT batch_id, workflow_type, exported_at,
                      COUNT(*) as lead_count,
                      SUM(CASE WHEN outcome = 'delivery' THEN 1 ELSE 0 END) as deliveries,
                      SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as outcomes_known
               FROM lead_outcomes
               GROUP BY batch_id
               ORDER BY exported_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [
            {
                "batch_id": r[0], "workflow_type": r[1], "exported_at": r[2],
                "lead_count": r[3], "deliveries": r[4], "outcomes_known": r[5],
            }
            for r in rows
        ]

    def get_exported_company_ids(self, days_back: int = 180) -> dict[str, dict]:
        """Get companies exported within the last N days.

        Returns dict mapping company_id -> {company_name, exported_at, workflow_type}.
        Only includes rows where company_id is not NULL/empty.
        """
        rows = self.execute(
            """SELECT company_id, company_name, exported_at, workflow_type
               FROM lead_outcomes
               WHERE exported_at >= date('now', ?)
                 AND company_id IS NOT NULL AND company_id != ''
               ORDER BY exported_at DESC""",
            (f"-{days_back} days",),
        )
        result = {}
        for r in rows:
            cid = r[0]
            if cid not in result:
                result[cid] = {
                    "company_name": r[1],
                    "exported_at": r[2],
                    "workflow_type": r[3],
                }
        return result

    def update_lead_outcome(self, batch_id: str, company_name: str,
                            outcome: str, outcome_at: str) -> None:
        """Update outcome for a specific lead (matched by batch + company)."""
        self.execute_write(
            """UPDATE lead_outcomes
               SET outcome = ?, outcome_at = ?, updated_at = CURRENT_TIMESTAMP
               WHERE batch_id = ? AND company_name = ?""",
            (outcome, outcome_at, batch_id, company_name),
        )
