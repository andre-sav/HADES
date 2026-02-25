"""Schema initialization and migrations."""

import logging

logger = logging.getLogger(__name__)


class SchemaMixin:
    """Database schema creation and migration."""

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
            "CREATE INDEX IF NOT EXISTS idx_history_workflow_created ON query_history(workflow_type, created_at)",
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
                person_id TEXT,
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
            "CREATE INDEX IF NOT EXISTS idx_lead_outcomes_exported_company ON lead_outcomes(exported_at, company_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_outcomes_batch_person ON lead_outcomes(batch_id, person_id)",
            # Staged exports (persist leads for CSV re-export after session loss)
            """
            CREATE TABLE IF NOT EXISTS staged_exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_type TEXT NOT NULL,
                leads_json TEXT NOT NULL,
                lead_count INTEGER NOT NULL,
                query_params TEXT,
                operator_id INTEGER,
                batch_id TEXT,
                exported_at TEXT,
                push_status TEXT,
                pushed_at TEXT,
                push_results_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_staged_created ON staged_exports(created_at)",
            # Pipeline automation run history
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_type TEXT NOT NULL,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                config_json TEXT,
                summary_json TEXT,
                batch_id TEXT,
                credits_used INTEGER DEFAULT 0,
                leads_exported INTEGER DEFAULT 0,
                error_message TEXT,
                started_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_workflow ON pipeline_runs(workflow_type)",
            "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_created ON pipeline_runs(created_at)",
            # Error log table
            """
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_type TEXT NOT NULL,
                error_type TEXT NOT NULL,
                user_message TEXT NOT NULL,
                technical_message TEXT DEFAULT '',
                recoverable INTEGER DEFAULT 1,
                context_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_error_log_created ON error_log(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_error_log_workflow ON error_log(workflow_type)",
            # Title preferences — learn which job titles users prefer to enrich
            """
            CREATE TABLE IF NOT EXISTS title_preferences (
                title TEXT PRIMARY KEY,
                selected_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                last_selected TIMESTAMP
            )
            """,
        ]

        for statement in schema_statements:
            self.connection.execute(statement)
        self.connection.commit()

        # Migrations for existing tables (add columns if they don't exist)
        self._run_migrations()

        # PII retention: purge old staged exports on startup
        self.purge_old_staged_exports(days=90)

    def _run_migrations(self) -> None:
        """Run schema migrations for existing tables."""
        migrations = [
            # Add Zoho sync columns to operators table
            ("operators", "zoho_id", "ALTER TABLE operators ADD COLUMN zoho_id TEXT UNIQUE"),
            ("operators", "synced_at", "ALTER TABLE operators ADD COLUMN synced_at TIMESTAMP"),
            ("lead_outcomes", "person_id", "ALTER TABLE lead_outcomes ADD COLUMN person_id TEXT"),
            # Add push tracking columns to staged_exports
            ("staged_exports", "push_status", "ALTER TABLE staged_exports ADD COLUMN push_status TEXT"),
            ("staged_exports", "pushed_at", "ALTER TABLE staged_exports ADD COLUMN pushed_at TEXT"),
            ("staged_exports", "push_results_json", "ALTER TABLE staged_exports ADD COLUMN push_results_json TEXT"),
        ]

        for table, column, statement in migrations:
            # Check if column exists via PRAGMA (immune to error message format changes)
            existing_cols = {
                row[1] for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column in existing_cols:
                logger.debug(f"Migration: {table}.{column} already exists")
                continue
            try:
                self.connection.execute(statement)
                self.connection.commit()
                logger.info(f"Migration: Added {column} to {table}")
            except Exception as e:
                logger.error(f"Migration failed for {table}.{column}: {e}")
