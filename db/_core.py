"""Connection management and query execution core."""

import logging
import threading
from contextlib import contextmanager

import libsql_experimental as libsql

logger = logging.getLogger(__name__)

# Guards lazy creation of per-instance locks (the instance may be built via
# @st.cache_resource and first touched by several session threads at once).
_LOCK_INIT = threading.Lock()


class ConnectionMixin:
    """Database connection and low-level query execution."""

    def __init__(self, url: str, auth_token: str):
        self.url = url
        self.auth_token = auth_token
        self._conn = None
        self._in_transaction = False
        self._lock = threading.RLock()

    @property
    def lock(self):
        """Reentrant lock serializing all access to the shared connection.

        The instance is an @st.cache_resource singleton shared by every
        Streamlit session thread; without this, one user's transaction()
        toggled _in_transaction for everyone (skipped commits, interleaved
        partial state) — HADES-638. Lazily created so instances constructed
        through non-standard paths (tests) still get one.
        """
        lk = getattr(self, "_lock", None)
        if lk is None:
            with _LOCK_INIT:
                lk = getattr(self, "_lock", None)
                if lk is None:
                    lk = threading.RLock()
                    self._lock = lk
        return lk

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
        with self.lock:
            self._in_transaction = True
            try:
                yield
                self.connection.commit()
            except Exception:
                try:
                    self.connection.rollback()
                except Exception:
                    # rollback on a dead stream fails too — don't mask the
                    # original error
                    logger.warning("Rollback failed after transaction error", exc_info=True)
                raise
            finally:
                self._in_transaction = False

    def execute(self, query: str, params: tuple = ()) -> list:
        """Execute query and return results. Reconnects on stale stream."""
        with self.lock:
            try:
                cursor = self.connection.execute(query, params)
                return cursor.fetchall()
            except Exception as e:
                if self._is_stale_stream_error(e):
                    if getattr(self, "_in_transaction", False):
                        # Earlier uncommitted statements died with the stream;
                        # replaying just this one would let transaction() commit
                        # a PARTIAL transaction (HADES-638).
                        raise
                    logger.warning("Stale Hrana stream detected, reconnecting...")
                    cursor = self._reconnect().execute(query, params)
                    return cursor.fetchall()
                raise

    def execute_write(self, query: str, params: tuple = ()) -> int:
        """Execute insert/update/delete and return lastrowid. Reconnects on stale stream.

        When called inside a ``transaction()`` context manager, the commit is
        deferred until the context exits.
        """
        with self.lock:
            try:
                cursor = self.connection.execute(query, params)
                if not self._in_transaction:
                    self.connection.commit()
                return cursor.lastrowid
            except Exception as e:
                if self._is_stale_stream_error(e):
                    if getattr(self, "_in_transaction", False):
                        # See execute(): no single-statement replay inside an
                        # open transaction (HADES-638).
                        raise
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

        Inside a ``transaction()`` context the commit is deferred to the
        context exit (same contract as execute_write); outside one, any
        non-stale failure rolls back the partially-executed batch so it
        can't ride along with a later unrelated commit.

        Safe to replay on reconnect (outside a transaction) because the old
        connection never committed — partial writes are rolled back when
        the stream dies.
        """
        if not params_list:
            return

        # Optimize INSERT to multi-row (single round-trip to Turso). Skipped
        # when a clause follows the VALUES tuple — the rewrite would drop it
        # (see _has_clause_after_values); correctness beats the round-trip.
        upper = query.strip().upper()
        if (
            upper.startswith("INSERT")
            and "VALUES" in upper
            and not self._has_clause_after_values(query)
        ):
            self._execute_multi_row_insert(query, params_list)
            return

        # Non-INSERT: individual statements
        with self.lock:
            self._execute_many_fallback(query, params_list)

    def _execute_many_fallback(self, query: str, params_list: list[tuple]) -> None:
        try:
            for params in params_list:
                self.connection.execute(query, params)
            if not self._in_transaction:
                self.connection.commit()
        except Exception as e:
            if getattr(self, "_in_transaction", False):
                # transaction() owns rollback; replaying/committing here would
                # produce a partial transaction (HADES-638 contract).
                raise
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
            # Roll back the rows that DID execute — left pending on the
            # shared connection, the next unrelated commit would silently
            # persist a partial batch (review N-01).
            try:
                self.connection.rollback()
            except Exception:
                logger.warning("Rollback failed after execute_many error", exc_info=True)
            raise

    @staticmethod
    def _has_clause_after_values(query: str) -> bool:
        """True if anything follows the VALUES tuple (ON CONFLICT, RETURNING…).

        The multi-row rewrite keeps only `query[:idx] + "VALUES "` and appends
        its own placeholder groups, so every trailing clause is discarded — an
        upsert would quietly become a plain INSERT with no conflict handling
        and no error. No caller writes one today; this makes sure the next one
        is not silently broken.
        """
        idx = query.upper().find("VALUES")
        if idx == -1:
            return False
        depth = 0
        for pos, ch in enumerate(query[idx:], start=idx):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return bool(query[pos + 1:].strip())
        return False

    def _execute_multi_row_insert(self, query: str, params_list: list[tuple]) -> None:
        """Build multi-row INSERT VALUES for single round-trip."""
        with self.lock:
            self._execute_multi_row_insert_locked(query, params_list)

    def _execute_multi_row_insert_locked(self, query: str, params_list: list[tuple]) -> None:
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
            if not self._in_transaction:
                self.connection.commit()
        except Exception as e:
            if getattr(self, "_in_transaction", False):
                # transaction() owns rollback; replaying/committing here would
                # produce a partial transaction (HADES-638 contract).
                raise
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
            # Roll back the batches that DID execute — left pending on the
            # shared connection, the next unrelated commit would silently
            # persist a partial batch (review N-01).
            try:
                self.connection.rollback()
            except Exception:
                logger.warning("Rollback failed after execute_many error", exc_info=True)
            raise
