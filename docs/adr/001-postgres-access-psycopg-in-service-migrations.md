# ADR-001: Postgres access with psycopg 3, a small own connection pool, client-side deadlines and in-service migrations

## Status

Accepted (2026-11-06, spec 002-keep-tasks-in-postgres-answer-503-and).

## Context

The Task API moves its tasks from process memory into the system's Postgres (resource `postgres`, injected as
`DATABASE_URL` by the gitops-app). It runs as two replicas in dev. The system contract binds the failure behaviour:
connect timeout 3 s, statement timeout 5 s, at most 2 s waiting for a pooled connection, `503` within 10 s while the
database is down or does not answer, `/ready` answering within 1 s, and recovery on the next request after the
database returns, without a restart. The service must start while the database is down, and two instances
starting at once on an empty database must not break each other while creating the schema.

Facts that shape the choice:

- A server-side `statement_timeout` does not fire when the server does not run at all (a paused container, a frozen
  node): only a client-side deadline bounds that case.
- `psycopg_pool` reconnects in background workers with exponential backoff; while one such attempt sleeps, the pool
  does not start another, so "the next request after the outage succeeds" is not guaranteed.
- The service is small (one table, synchronous FastAPI handlers in the threadpool); an ORM adds nothing.

## Decision

- **Driver:** `psycopg` 3 (`psycopg[binary]`), synchronous, plain SQL. No ORM, no `psycopg_pool`.
- **Pool:** an own minimal pool in `taskboard4_api/db.py`: a bounded semaphore (max 5 connections, acquire timeout
  2 s), a deque of idle connections validated before reuse, connections opened synchronously on demand
  (`connect_timeout=3`, `options=-c statement_timeout=5000`), and every connection that saw an error discarded.
  No background threads: after an outage the next checkout opens a fresh connection.
- **Deadlines:** every database operation runs on a bounded worker executor and the caller waits with a deadline
  (7 s for task operations, 0.5 s for the readiness check). On expiry the caller gets `DatabaseUnavailable`
  (`503`); the worker rolls back instead of committing when it finishes late, so a request answered `503`
  never stores a task.
- **Migrations:** versioned SQL in `taskboard4_api/migrations.py`, applied by the service itself on its first
  successful database operation (not at startup, so it starts while the database is down), inside one transaction
  holding `pg_advisory_xact_lock(<fixed key>)`, recorded in `schema_version`. DDL also uses `IF NOT EXISTS`.
  No Alembic and no migration Job in the gitops-app.
- **Configuration:** only `DATABASE_URL` (both `postgres://` and `postgresql://`, which libpq accepts natively). The
  service refuses to start without it. The timeouts are constants of the contract, not settings.

## Consequences

**Positive:** the failure behaviour is explicit, deterministic and testable (no hidden backoff); no extra deployment
object for migrations; two replicas starting together serialize on the advisory lock; one dependency.

**Negative:** the pool and deadline code is ours to maintain (about a hundred lines with tests). A worker blocked on
a frozen server holds a thread and a connection slot until the server answers again; both are bounded (5
connections, a fixed executor size), so the worst case is `503` for further requests, which is the contract.
Schema changes in later specs must be additive within one release (expand/contract), because old and new replicas
run side by side during a rollout. Revisit this ADR when the service needs async handlers, more tables with
relations, or migrations that are too slow for a request path.
