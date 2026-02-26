"""Connection management and query execution core."""

import logging
from contextlib import contextmanager

import libsql_experimental as libsql

logger = logging.getLogger(__name__)


class ConnectionMixin:
    """Database connection and low-level query execution."""

    def __init__(self, url: str, auth_token: str):
        self.url = url
        self.auth_token = auth_token
        self._conn = None
        self._in_transaction = False

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

    @contextmanager
    def transaction(self):
        """Context manager for grouping writes into a single transaction.

        Usage::

            with db.transaction():
                db.execute_write("INSERT ...")
                db.execute_write("UPDATE ...")
            # committed here (or rolled back on exception)
        """
        self._in_transaction = True
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            self._in_transaction = False

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
        """Execute insert/update/delete and return lastrowid. Reconnects on stale stream.

        When called inside a ``transaction()`` context manager, the commit is
        deferred until the context exits.
        """
        try:
            cursor = self.connection.execute(query, params)
            if not self._in_transaction:
                self.connection.commit()
            return cursor.lastrowid
        except Exception as e:
            if self._is_stale_stream_error(e):
                logger.warning("Stale Hrana stream detected, reconnecting...")
                conn = self._reconnect()
                cursor = conn.execute(query, params)
                if not self._in_transaction:
                    conn.commit()
                return cursor.lastrowid
            raise

    def execute_many(self, query: str, params_list: list[tuple]) -> None:
        """Execute batch insert/update. Uses multi-row INSERT when possible.

        For INSERT statements, builds a single multi-row VALUES clause
        (1 round-trip instead of N). Falls back to individual statements
        for non-INSERT queries.

        Safe to replay on reconnect because the old connection never
        committed — partial writes are rolled back when the stream dies.
        """
        if not params_list:
            return

        # Optimize INSERT to multi-row (single round-trip to Turso)
        upper = query.strip().upper()
        if upper.startswith("INSERT") and "VALUES" in upper:
            self._execute_multi_row_insert(query, params_list)
            return

        # Non-INSERT: individual statements
        try:
            for params in params_list:
                self.connection.execute(query, params)
            self.connection.commit()
        except Exception as e:
            if self._is_stale_stream_error(e):
                logger.warning("Stale Hrana stream detected, reconnecting...")
                try:
                    self.connection.rollback()
                except Exception:
                    pass
                conn = self._reconnect()
                for params in params_list:
                    conn.execute(query, params)
                conn.commit()
                return
            raise

    def _execute_multi_row_insert(self, query: str, params_list: list[tuple]) -> None:
        """Build multi-row INSERT VALUES for single round-trip."""
        cols_per_row = len(params_list[0])
        row_placeholder = f"({', '.join(['?'] * cols_per_row)})"

        # Split at VALUES to get the prefix (INSERT ... INTO table (...) VALUES)
        idx = query.upper().find("VALUES")
        prefix = query[:idx] + "VALUES "

        # Batch to stay under SQLite's 999 parameter limit
        batch_size = max(1, 900 // cols_per_row)

        try:
            for i in range(0, len(params_list), batch_size):
                batch = params_list[i:i + batch_size]
                multi_query = prefix + ", ".join([row_placeholder] * len(batch))
                flat_params = tuple(p for row in batch for p in row)
                self.connection.execute(multi_query, flat_params)
            self.connection.commit()
        except Exception as e:
            if self._is_stale_stream_error(e):
                logger.warning("Stale Hrana stream detected, reconnecting...")
                try:
                    self.connection.rollback()
                except Exception:
                    pass
                conn = self._reconnect()
                for i in range(0, len(params_list), batch_size):
                    batch = params_list[i:i + batch_size]
                    multi_query = prefix + ", ".join([row_placeholder] * len(batch))
                    flat_params = tuple(p for row in batch for p in row)
                    conn.execute(multi_query, flat_params)
                conn.commit()
                return
            raise
