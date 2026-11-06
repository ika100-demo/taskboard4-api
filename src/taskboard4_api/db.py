"""Postgres access layer: a small pool, a worker executor, deadlines and error mapping."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

import psycopg
import structlog
from fastapi import Request

from taskboard4_api.migrations import ensure_schema

CONNECT_TIMEOUT_S = 3
STATEMENT_TIMEOUT_MS = 5000
POOL_WAIT_S = 2.0
OPERATION_DEADLINE_S = 7.0
READY_DEADLINE_S = 0.5
POOL_MAX_SIZE = 5

T = TypeVar("T")


class DatabaseUnavailable(Exception):  # noqa: N818 - name fixed by the contract
    """The database cannot serve the request; `reason` is a short machine-readable code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Abandoned(Exception):  # noqa: N818
    """Raised in the worker when the caller gave up: roll back instead of committing."""


class Database:
    """Pooled Postgres access with client-side deadlines. `__init__` does no I/O."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._slots = threading.BoundedSemaphore(POOL_MAX_SIZE)
        self._idle: deque[psycopg.Connection] = deque()
        self._idle_lock = threading.Lock()
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._executor = ThreadPoolExecutor(POOL_MAX_SIZE + 4, thread_name_prefix="db")

    # -- public API -------------------------------------------------------------------------

    def run(
        self,
        op: Callable[[psycopg.Connection], T],
        *,
        deadline: float = OPERATION_DEADLINE_S,
    ) -> T:
        """Run `op` in one transaction and commit; raise `DatabaseUnavailable` on failure."""
        return self._run(op, deadline=deadline, check_schema=True)

    def ping(self) -> bool:
        """`SELECT 1` within `READY_DEADLINE_S`; never raises."""
        try:
            self._run(
                lambda conn: conn.execute("SELECT 1").fetchone(),
                deadline=READY_DEADLINE_S,
                check_schema=False,
            )
        except Exception:  # noqa: BLE001 - readiness must never raise
            return False
        return True

    def close(self) -> None:
        """Close idle connections and shut the executor down without waiting."""
        with self._idle_lock:
            idle = list(self._idle)
            self._idle.clear()
        for conn in idle:
            self._discard(conn)
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- internals --------------------------------------------------------------------------

    def _run(
        self,
        op: Callable[[psycopg.Connection], T],
        *,
        deadline: float,
        check_schema: bool,
    ) -> T:
        abandoned = threading.Event()
        try:
            future = self._executor.submit(self._work, op, deadline, check_schema, abandoned)
        except RuntimeError as exc:  # executor shut down
            raise DatabaseUnavailable("not_initialized") from exc
        try:
            return future.result(timeout=deadline)
        except TimeoutError as exc:
            abandoned.set()
            future.cancel()
            raise DatabaseUnavailable("timeout") from exc

    def _work(
        self,
        op: Callable[[psycopg.Connection], T],
        deadline: float,
        check_schema: bool,
        abandoned: threading.Event,
    ) -> T:
        if abandoned.is_set():
            raise _Abandoned
        if not self._slots.acquire(timeout=min(POOL_WAIT_S, deadline)):
            raise DatabaseUnavailable("pool_timeout")
        conn: psycopg.Connection | None = None
        try:
            conn = self._checkout()
            if check_schema:
                self._ensure_schema_once(conn)
            with conn.transaction():
                result = op(conn)
                if abandoned.is_set():
                    raise _Abandoned
            self._checkin(conn)
            conn = None
            return result
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise DatabaseUnavailable("connection") from exc
        finally:
            if conn is not None:
                self._discard(conn)
            self._slots.release()

    def _ensure_schema_once(self, conn: psycopg.Connection) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if not self._schema_ready:
                ensure_schema(conn)
                self._schema_ready = True

    def _checkout(self) -> psycopg.Connection:
        while True:
            with self._idle_lock:
                conn = self._idle.pop() if self._idle else None
            if conn is None:
                break
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:  # noqa: BLE001 - stale connection: drop it, try the next
                self._discard(conn)
        return psycopg.connect(
            self._url,
            connect_timeout=CONNECT_TIMEOUT_S,
            options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            autocommit=True,
        )

    def _checkin(self, conn: psycopg.Connection) -> None:
        if conn.closed or conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            self._discard(conn)
            return
        with self._idle_lock:
            self._idle.append(conn)

    @staticmethod
    def _discard(conn: psycopg.Connection) -> None:
        try:
            conn.close()
        except Exception as exc:  # noqa: BLE001 - best effort
            structlog.get_logger().debug("connection_close_failed", error=type(exc).__name__)


def get_database(request: Request) -> Database:
    """FastAPI dependency: the app's `Database`, else `DatabaseUnavailable("not_initialized")`."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise DatabaseUnavailable("not_initialized")
    return db  # type: ignore[no-any-return]
