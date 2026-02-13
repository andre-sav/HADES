"""
Turso database connection and operations for the ZoomInfo Lead Pipeline.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import libsql_experimental as libsql
import streamlit as st

# Configure logging
logger = logging.getLogger(__name__)


class TursoDatabase:
    """Turso database connection manager."""

    def __init__(self, url: str, auth_token: str):
        self.url = url
        self.auth_token = auth_token
        self._conn = None

    @property
    def connection(self):
        """Get or create database connection."""
        if self._conn is None:
            self._conn = libsql.connect(self.url, auth_token=self.auth_token)
        return self._conn

    def _reconnect(self):
        """Force a new connection (e.g. after a stale Hrana stream)."""
        self._conn = None
        return self.connection

    def _is_stale_stream_error(self, exc: Exception) -> bool:
        """Check if an exception is a stale Hrana stream error."""
        msg = str(exc).lower()
        return "stream not found" in msg or ("hrana" in msg and "404" in msg)

    def execute(self, query: str, params: tuple = ()) -> list:
        """Execute query and return results. Reconnects on stale stream."""
        try:
            cursor = self.connection.execute(query, params)
            return cursor.fetchall()
        except Exception as e:
            if self._is_stale_stream_error(e):
                logger.warning("Stale Hrana stream detected, reconnecting...")
                cursor = self._reconnect().execute(query, params)
                return cursor.fetchall()
            raise

    def execute_write(self, query: str, params: tuple = ()) -> int:
        """Execute insert/update/delete and return lastrowid. Reconnects on stale stream."""
        try:
            cursor = self.connection.execute(query, params)
            self.connection.commit()
            return cursor.lastrowid
        except Exception as e:
            if self._is_stale_stream_error(e):
                logger.warning("Stale Hrana stream detected, reconnecting...")
                conn = self._reconnect()
                cursor = conn.execute(query, params)
                conn.commit()
                return cursor.lastrowid
            raise

    def execute_many(self, query: str, params_list: list[tuple]) -> None:
        """Execute batch insert/update. Reconnects on stale stream.

        Safe to replay all items on reconnect because the old connection
        never committed — partial writes are rolled back when the stream dies.
        """
        try:
            for params in params_list:
                self.connection.execute(query, params)
            self.connection.commit()
        except Exception as e:
            if self._is_stale_stream_error(e):
                logger.warning("Stale Hrana stream detected, reconnecting...")
                # Attempt rollback on old connection to ensure no partial state
                try:
                    self.connection.rollback()
                except Exception:
                    pass  # Connection is dead, rollback is best-effort
                conn = self._reconnect()
                for params in params_list:
                    conn.execute(query, params)
                conn.commit()
                return
            raise

    def init_schema(self) -> None:
        """Initialize database schema."""
        schema_statements = [
            # Operators table
            """
            CREATE TABLE IF NOT EXISTS operators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operator_name TEXT UNIQUE NOT NULL,
                vending_business_name TEXT,
                operator_phone TEXT,
                operator_email TEXT,
                operator_zip TEXT,
                operator_website TEXT,
                team TEXT,
                zoho_id TEXT UNIQUE,
                synced_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
            """,
            # ZoomInfo cache table
            """
            CREATE TABLE IF NOT EXISTS zoominfo_cache (
                id TEXT PRIMARY KEY,
                workflow_type TEXT NOT NULL,
                query_params TEXT NOT NULL,
                lead_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_cache_expires ON zoominfo_cache(expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_cache_workflow ON zoominfo_cache(workflow_type)",
            # Credit usage table
            """
            CREATE TABLE IF NOT EXISTS credit_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_type TEXT NOT NULL,
                query_params TEXT,
                credits_used INTEGER NOT NULL,
                leads_returned INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_usage_created ON credit_usage(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_usage_workflow ON credit_usage(workflow_type)",
            # Location templates table
            """
            CREATE TABLE IF NOT EXISTS location_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                zip_codes TEXT NOT NULL,
                radius_miles INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # Query history table
            """
            CREATE TABLE IF NOT EXISTS query_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_type TEXT NOT NULL,
                query_params TEXT,
                leads_returned INTEGER,
                leads_exported INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_history_created ON query_history(created_at)",
            # Company ID mapping cache (hashed intent ID → numeric ID)
            """
            CREATE TABLE IF NOT EXISTS company_id_mapping (
                hashed_id TEXT PRIMARY KEY,
                numeric_id INTEGER NOT NULL,
                company_name TEXT,
                resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # Sync metadata table (for tracking last sync times)
            """
            CREATE TABLE IF NOT EXISTS sync_metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # One-time import of pre-HADES historical data
            """
            CREATE TABLE IF NOT EXISTS historical_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                sic_code TEXT,
                employee_count INTEGER,
                zip_code TEXT,
                state TEXT,
                outcome TEXT NOT NULL,
                source_file TEXT,
                created_at TEXT,
                imported_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_historical_outcome ON historical_outcomes(outcome)",
            # Ongoing HADES-originated lead tracking
            """
            CREATE TABLE IF NOT EXISTS lead_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                company_id TEXT,
                sic_code TEXT,
                employee_count INTEGER,
                distance_miles REAL,
                zip_code TEXT,
                state TEXT,
                hades_score INTEGER,
                workflow_type TEXT,
                exported_at TEXT NOT NULL,
                outcome TEXT,
                outcome_at TEXT,
                source_features TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_lead_outcomes_batch ON lead_outcomes(batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_lead_outcomes_company_exported ON lead_outcomes(company_id, exported_at)",
        ]

        for statement in schema_statements:
            self.connection.execute(statement)
        self.connection.commit()

        # Migrations for existing tables (add columns if they don't exist)
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Run schema migrations for existing tables."""
        migrations = [
            # Add Zoho sync columns to operators table
            ("operators", "zoho_id", "ALTER TABLE operators ADD COLUMN zoho_id TEXT UNIQUE"),
            ("operators", "synced_at", "ALTER TABLE operators ADD COLUMN synced_at TIMESTAMP"),
            ("lead_outcomes", "person_id", "ALTER TABLE lead_outcomes ADD COLUMN person_id TEXT"),
        ]

        for table, column, statement in migrations:
            # Check if column exists
            try:
                self.connection.execute(f"SELECT {column} FROM {table} LIMIT 1")
                logger.debug(f"Migration: {table}.{column} already exists")
            except Exception:
                # Column doesn't exist, add it
                try:
                    self.connection.execute(statement)
                    self.connection.commit()
                    logger.info(f"Migration: Added {column} to {table}")
                except Exception as e:
                    error_str = str(e).lower()
                    if "duplicate" in error_str or "already exists" in error_str:
                        logger.debug(f"Migration: {table}.{column} already exists (from error)")
                    else:
                        logger.error(f"Migration failed for {table}.{column}: {e}")

    # --- Operator CRUD ---

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

    # --- Cache Operations ---

    def get_cached_results(self, cache_id: str) -> list[dict] | None:
        """Get cached query results if not expired."""
        rows = self.execute(
            "SELECT lead_data FROM zoominfo_cache "
            "WHERE id = ? AND expires_at > CURRENT_TIMESTAMP",
            (cache_id,),
        )
        if not rows:
            return None
        return json.loads(rows[0][0])

    def cache_results(
        self, cache_id: str, workflow_type: str, query_params: dict, leads: list[dict], ttl_days: int = 7
    ) -> None:
        """Cache query results."""
        expires_at = datetime.now() + timedelta(days=ttl_days)
        self.execute_write(
            "INSERT OR REPLACE INTO zoominfo_cache "
            "(id, workflow_type, query_params, lead_data, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                cache_id,
                workflow_type,
                json.dumps(query_params),
                json.dumps(leads),
                expires_at.isoformat(),
            ),
        )

    def clear_expired_cache(self) -> int:
        """Remove expired cache entries. Returns count deleted."""
        # Count before delete
        rows = self.execute(
            "SELECT COUNT(*) FROM zoominfo_cache WHERE expires_at <= CURRENT_TIMESTAMP"
        )
        count = rows[0][0] if rows else 0

        if count > 0:
            self.execute_write("DELETE FROM zoominfo_cache WHERE expires_at <= CURRENT_TIMESTAMP")

        return count

    # --- Credit Usage ---

    def log_credit_usage(
        self, workflow_type: str, query_params: dict, credits_used: int, leads_returned: int
    ) -> None:
        """Log credit usage for a query."""
        self.execute_write(
            "INSERT INTO credit_usage (workflow_type, query_params, credits_used, leads_returned) "
            "VALUES (?, ?, ?, ?)",
            (workflow_type, json.dumps(query_params), credits_used, leads_returned),
        )

    def get_weekly_usage(self, workflow_type: str | None = None) -> int:
        """Get total credits used this week."""
        if workflow_type:
            rows = self.execute(
                "SELECT COALESCE(SUM(credits_used), 0) FROM credit_usage "
                "WHERE workflow_type = ? AND created_at >= date('now', '-7 days')",
                (workflow_type,),
            )
        else:
            rows = self.execute(
                "SELECT COALESCE(SUM(credits_used), 0) FROM credit_usage "
                "WHERE created_at >= date('now', '-7 days')"
            )
        return rows[0][0] if rows else 0

    def get_usage_summary(self, days: int = 30) -> list[dict]:
        """Get usage summary for dashboard."""
        rows = self.execute(
            "SELECT workflow_type, SUM(credits_used) as credits, "
            "SUM(leads_returned) as leads, COUNT(*) as queries "
            "FROM credit_usage WHERE created_at >= date('now', ?) "
            "GROUP BY workflow_type",
            (f"-{days} days",),
        )
        return [
            {"workflow_type": r[0], "credits": r[1], "leads": r[2], "queries": r[3]}
            for r in rows
        ]

    # --- Location Templates ---

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

    def delete_location_template(self, template_id: int) -> None:
        """Delete a location template."""
        self.execute_write("DELETE FROM location_templates WHERE id = ?", (template_id,))

    # --- Query History ---

    def log_query(
        self, workflow_type: str, query_params: dict, leads_returned: int, leads_exported: int = 0
    ) -> None:
        """Log a query execution."""
        self.execute_write(
            "INSERT INTO query_history (workflow_type, query_params, leads_returned, leads_exported) "
            "VALUES (?, ?, ?, ?)",
            (workflow_type, json.dumps(query_params), leads_returned, leads_exported),
        )

    def get_recent_queries(self, limit: int = 10) -> list[dict]:
        """Get recent query history."""
        rows = self.execute(
            "SELECT id, workflow_type, query_params, leads_returned, leads_exported, created_at "
            "FROM query_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "workflow_type": r[1],
                "query_params": json.loads(r[2]) if r[2] else {},
                "leads_returned": r[3],
                "leads_exported": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def get_last_query(self, workflow_type: str) -> dict | None:
        """Get the most recent query for a specific workflow type."""
        rows = self.execute(
            "SELECT id, workflow_type, query_params, leads_returned, leads_exported, created_at "
            "FROM query_history WHERE workflow_type = ? ORDER BY created_at DESC LIMIT 1",
            (workflow_type,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0],
            "workflow_type": r[1],
            "query_params": json.loads(r[2]) if r[2] else {},
            "leads_returned": r[3],
            "leads_exported": r[4],
            "created_at": r[5],
        }

    def update_query_exported(self, query_id: int, leads_exported: int) -> None:
        """Update the leads_exported count for a query."""
        self.execute_write(
            "UPDATE query_history SET leads_exported = ? WHERE id = ?",
            (leads_exported, query_id),
        )

    # --- Company ID mapping cache ---

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

    # --- Lead Outcomes ---

    def record_lead_outcomes_batch(self, params_list: list[tuple]) -> None:
        """Batch INSERT lead outcomes. Each tuple:
        (batch_id, company_name, company_id, person_id, sic_code, employee_count,
         distance_miles, zip_code, state, hades_score, workflow_type,
         exported_at, source_features)
        """
        self.execute_many(
            """INSERT INTO lead_outcomes
               (batch_id, company_name, company_id, person_id, sic_code, employee_count,
                distance_miles, zip_code, state, hades_score, workflow_type,
                exported_at, source_features)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            params_list,
        )

    def get_outcomes_by_batch(self, batch_id: str) -> list[dict]:
        """Get all lead outcomes for a batch."""
        rows = self.execute(
            """SELECT id, batch_id, company_name, sic_code, employee_count,
                      hades_score, workflow_type, exported_at, outcome, outcome_at
               FROM lead_outcomes WHERE batch_id = ?
               ORDER BY id""",
            (batch_id,),
        )
        return [
            {
                "id": r[0], "batch_id": r[1], "company_name": r[2],
                "sic_code": r[3], "employee_count": r[4], "hades_score": r[5],
                "workflow_type": r[6], "exported_at": r[7], "outcome": r[8],
                "outcome_at": r[9],
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


@st.cache_resource(ttl=3600)  # Refresh connection every hour to prevent stale connections
def get_database() -> TursoDatabase:
    """Get cached database instance from Streamlit secrets."""
    db = TursoDatabase(
        url=st.secrets["TURSO_DATABASE_URL"],
        auth_token=st.secrets["TURSO_AUTH_TOKEN"],
    )
    db.init_schema()
    return db
