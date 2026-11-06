"""Versioned schema migrations, applied under a Postgres advisory lock."""

from __future__ import annotations

import psycopg
import structlog

ADVISORY_LOCK_KEY: int = 0x7461736B626F6172  # fixed 64-bit constant ("taskboar")

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS tasks (
          seq        bigserial    PRIMARY KEY,
          id         uuid         NOT NULL UNIQUE,
          title      varchar(200) NOT NULL,
          due_date   date         NULL,
          created_at timestamptz  NOT NULL DEFAULT now()
        )
        """,
    ),
]

_CREATE_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
  version    integer PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def ensure_schema(conn: psycopg.Connection) -> None:
    """Bring the schema up to date; idempotent and safe under concurrency."""
    log = structlog.get_logger()
    applied_now: list[int] = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
        conn.execute(_CREATE_VERSION_TABLE)
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        done = {row[0] for row in rows}
        for version, ddl in MIGRATIONS:
            if version in done:
                continue
            conn.execute(ddl)
            conn.execute("INSERT INTO schema_version (version) VALUES (%s)", (version,))
            applied_now.append(version)
    for version in applied_now:
        log.info("schema_migrated", version=version)
