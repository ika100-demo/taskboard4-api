---
spec_id: 002-keep-tasks-in-postgres-answer-503-and
shape: service-python
spec_hash: 918f3cbd4b6b
summary: Tasks in Postgres (psycopg 3, own pool with deadlines, in-service migration), 503 and not-ready while the database is down, refuse to start without DATABASE_URL
tasks:
  - id: t1
    title: Add DATABASE_URL settings, the Database access layer and the tasks migration
    files: [pyproject.toml, uv.lock, src/taskboard4_api/settings.py, src/taskboard4_api/db.py, src/taskboard4_api/migrations.py, docs/env-vars.md]
    covers: [AC-002.5, AC-002.6, AC-002.7, AC-002.10, AC-002.11, AC-002.12, AC-002.13, AC-002.14]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Make TaskStore Postgres-backed behind the unchanged routes
    files: [src/taskboard4_api/tasks/store.py, src/taskboard4_api/tasks/api.py, src/taskboard4_api/tasks/__init__.py, tests/test_task_models.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.10, AC-002.11, AC-002.12, AC-002.13]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: App factory, lifespan, database readiness and the 503/500 handlers
    files: [src/taskboard4_api/main.py]
    covers: [AC-002.4, AC-002.5, AC-002.6, AC-002.8, AC-002.9, AC-002.10, AC-002.11, AC-002.12, AC-002.13, AC-002.14]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: Image smoke start with a throwaway Postgres (image-smoke, ci-extra)
    files: [scripts/image_smoke.sh, devbox.json, .claude/project-notes.md, README.md]
    covers: [AC-002.13, AC-002.14]
    parallel_safe: false
    depends_on: [t2, t3]
human_steps:
  - If the repo variable CI_RUNNER points at a self-hosted runner, make sure that runner has a working Docker daemon (the test job starts Postgres with testcontainers, the ci-extra job builds and smoke-starts the image).
  - Merge the taskboard4-gitops slice (postgres resource, uses postgres on taskboard4-api, 2 dev replicas) before this PR, so the new pods find DATABASE_URL on their first dev rollout.
---

# Plan — 002 Keep tasks in Postgres, answer 503 and report not ready while the database is down

The contract, the timeouts, the data model and the test seam are in [design.md](design.md) and are binding; the
architecture decision is [ADR-001](../../adr/001-postgres-access-psycopg-in-service-migrations.md). No gitops
task: the system's gitops slice (postgres resource, `DATABASE_URL` injection, two dev replicas) is planned and
built in `taskboard4-gitops`.

Levels: t1 → t2, t3 (parallel) → t4.

## Test phase (before t1, by the testers)

Not a coder task; listed so the build does it:

- Retire the test of the withdrawn AC-001.10: delete `test_restart_empties_list` from `tests/test_tasks.py`
  (justified by the 2026-11-06 amend of spec 001). Change nothing else in spec 001's assertions.
- Point spec 001's `tclient` fixture, `tests/conftest.py`'s `client` fixture and the template's `/ready` test at a
  fresh Postgres database through `create_app()` (design, "Test seam"). The model unit tests stay as they are.
- Write the AC-002.x acceptance tests with the Postgres fixtures, the TCP proxy for outages and the subprocess
  start for AC-002.14.

## t1 — Add DATABASE_URL settings, the Database access layer and the tasks migration

**Files:** pyproject.toml, uv.lock, src/taskboard4_api/settings.py, src/taskboard4_api/db.py, src/taskboard4_api/migrations.py, docs/env-vars.md
**Covers:** AC-002.5, AC-002.6, AC-002.7, AC-002.10, AC-002.11, AC-002.12, AC-002.13, AC-002.14
**Goal:** Everything the service needs to talk to Postgres, with the contract's timeouts and failure mapping, and
with nothing yet wired into the app: the `DATABASE_URL` check, the `Database` class (own pool, worker executor,
deadlines, `DatabaseUnavailable`), the `get_database` dependency, and the advisory-locked, versioned migration that
creates `tasks`.

**Implementation notes:**
- Dependencies: runtime `psycopg[binary]>=3.2`; dev extra `testcontainers[postgres]>=4.8`. Update `uv.lock`
  (`devbox run -- uv lock`); never `uv add` or `pip`. No `psycopg_pool`, no ORM (ADR-001).
- `settings.py`: `load_database_url()` returns the stripped value; unset or blank raises `MissingSetting("DATABASE_URL is not set")`. No other variable is read; no scheme rewriting (libpq accepts `postgres://` and `postgresql://`).
- `db.py`: constants, `DatabaseUnavailable(reason)`, `Database(url)` exactly as in design.md. `__init__` does no I/O.
  Pool = `threading.BoundedSemaphore(POOL_MAX_SIZE)` plus a lock-guarded deque of idle connections; validate an idle
  connection before reuse (a cheap round trip under the remaining deadline), discard it on failure and connect fresh
  in the same checkout. Connect with `psycopg.connect(url, connect_timeout=3, options="-c statement_timeout=5000")`.
- `run(op, deadline)`: worker on a `ThreadPoolExecutor(POOL_MAX_SIZE + 4, thread_name_prefix="db")`, caller waits
  `future.result(timeout=deadline)`; pool wait is `min(POOL_WAIT_S, deadline)`. On caller timeout set the request's
  `abandoned` event; the worker checks it before committing and rolls back instead (AC-002.7).
- Error mapping: `psycopg.OperationalError` and `psycopg.InterfaceError` (includes `QueryCanceled`, lock timeouts,
  refused/dropped connections), semaphore timeout and caller timeout become `DatabaseUnavailable` with the
  `reason` from design.md; other exceptions propagate. A connection that raised is closed, never returned.
- `ping()`: `SELECT 1` through the same path with `READY_DEADLINE_S`, schema check skipped; returns `False` on any
  failure, never raises. `close()`: close idle connections, `executor.shutdown(wait=False, cancel_futures=True)`.
- `get_database(request)`: `request.app.state.db` if present, else `DatabaseUnavailable("not_initialized")`.
- `migrations.py`: `ensure_schema(conn)` in its own transaction: `pg_advisory_xact_lock(ADVISORY_LOCK_KEY)`, create
  `schema_version`, apply each missing version from `MIGRATIONS` (migration 1 = table `tasks`, DDL in design.md),
  log `schema_migrated`. `Database` calls it once per instance (flag under a lock) before the first `op`; a failure
  leaves the flag unset so the next operation retries (AC-002.11, AC-002.12).
- Log `database_unavailable` (warning, `operation`, `reason`); never log the URL, password or titles.
- `docs/env-vars.md`: add `DATABASE_URL` (required, no default, both schemes, injected by the `postgres` resource;
  the service exits at startup without it).

**Done when:** `devbox run quality` passes, and the coder's own unit/integration tests in `tests/` (against the
test Postgres) show: `load_database_url` raises for unset and blank values; `run` returns results and commits;
an unreachable URL (`postgresql://x:y@127.0.0.1:1/z`) raises `DatabaseUnavailable` in under 3 s; an op that sleeps
past the deadline raises in about the deadline and its insert is not committed; `ensure_schema` run concurrently
from two threads on an empty database succeeds in both and creates `tasks` once; `ping` is `False` within 1 s on an
unreachable URL and `True` on the test database; both URL schemes connect. The HTTP acceptance tests pass only
after t2 and t3.

## t2 — Make TaskStore Postgres-backed behind the unchanged routes

**Files:** src/taskboard4_api/tasks/store.py, src/taskboard4_api/tasks/api.py, src/taskboard4_api/tasks/__init__.py, tests/test_task_models.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.10, AC-002.11, AC-002.12, AC-002.13
**Goal:** Replace the in-memory store with `TaskStore(db)` over the `tasks` table, keeping the routes, the models
and the 422 behaviour exactly as in spec 001.

**Implementation notes:**
- `TaskStore.add`: `uuid.uuid4()`, `INSERT ... RETURNING id, title, due_date` through `db.run`; build `Task` with
  `id=str(row_id)`. `TaskStore.list`: `SELECT id, title, due_date FROM tasks ORDER BY seq` through `db.run`.
- Remove the module-level in-memory `_store`. `get_task_store(db: Annotated[Database, Depends(get_database)])
  -> TaskStore` builds a store per request (cheap, no I/O).
- `api.py`: keep the handlers and `response_model`s; only the dependency type changes. Keep sync `def` handlers.
  Do not catch `DatabaseUnavailable` here (t3's handler maps it to `503`). Keep `task_created` with `task_id` only.
- `models.py` stays untouched, so validation (and `422`) happens before any database access (AC-002.4).
- `__init__.py`: re-export `TaskStore` and `get_task_store` as today.
- `tests/test_task_models.py`: remove `test_store_unique_ids_and_order` (it tests the deleted in-memory store; it is
  a unit test, not an acceptance test); keep every model test unchanged.

**Done when:** `devbox run quality` passes and, together with t3, the acceptance tests for spec 001 (AC-001.1 to
AC-001.9, AC-001.11, AC-001.12, run against Postgres) and for AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5,
AC-002.6, AC-002.7 pass.

## t3 — App factory, lifespan, database readiness and the 503/500 handlers

**Files:** src/taskboard4_api/main.py
**Covers:** AC-002.4, AC-002.5, AC-002.6, AC-002.8, AC-002.9, AC-002.10, AC-002.11, AC-002.12, AC-002.13, AC-002.14
**Goal:** Wire the `Database` into the app's lifecycle and probes: refuse to start without `DATABASE_URL`, start
without connecting, report readiness from `SELECT 1`, and answer every database failure with the contract's `503`.

**Implementation notes:**
- `create_app() -> FastAPI` builds the app as today (middleware, tasks router, `/health`, `/ready`, `/ping`,
  `/metrics`) plus a lifespan; keep `app = create_app()` and the import-time `configure_logging` / tracing setup.
- Lifespan: `load_database_url()`; on `MissingSetting` log `config_missing` (error, `variable="DATABASE_URL"`,
  `message="DATABASE_URL is not set"`) and re-raise, so uvicorn exits non-zero without binding (AC-002.14). Otherwise
  `app.state.db = Database(url)` with no connection attempt (AC-002.11); on shutdown `db.close()`.
- `/health` unchanged and database-free (AC-002.9).
- `/ready`: `get_database` failure or `db.ping()` false gives `JSONResponse(503, {"status": "not ready"})`, else
  `200 {"status": "ready"}` (AC-002.8, AC-002.10). Keep `response_model=HealthResponse` for the 200 case.
- Exception handler `DatabaseUnavailable` returns `503 {"detail": "database unavailable"}` (AC-002.5, AC-002.6).
- Exception handler `Exception` returns `500 {"detail": "internal server error"}`; the metrics middleware must still
  count the error (the existing metrics tests keep passing).
- Do not add a `RequestValidationError` handler: FastAPI's 422 stays the contract (AC-002.4).

**Done when:** `devbox run quality` passes; with t2, the acceptance tests for AC-002.8 to AC-002.14 pass, and the
existing health, metrics and tracing tests pass; `devbox run ci` is green.

## t4 — Image smoke start with a throwaway Postgres (image-smoke, ci-extra)

**Files:** scripts/image_smoke.sh, devbox.json, .claude/project-notes.md, README.md
**Covers:** AC-002.13, AC-002.14
**Goal:** Keep the container smoke start working now that the image needs a database: one script starts Postgres
next to the image, checks the real image end to end and checks that it refuses to start without `DATABASE_URL`.
It runs locally and as the repo's `ci-extra` gate.

**Implementation notes:**
- `scripts/image_smoke.sh` (bash, `set -euo pipefail`, `trap` cleanup of containers and network): needs the image
  `taskboard4-api:scan` (`devbox run image-build`); creates a unique docker network; starts `postgres:16-alpine`
  with a random password generated at runtime (no literal secret in the repo); waits for `pg_isready`.
- Runs the image like Kubernetes would: `--read-only --tmpfs /tmp --user 10001:10001`, on that network, with
  `DATABASE_URL=postgres://...` (the scheme the platform injects), published on a random localhost port.
- Checks with `curl` within 30 s: `/health` 200 `{"status":"ok"}`, `/ready` 200 `{"status":"ready"}`,
  `POST /tasks {"title":"smoke-<uuid>"}` 201, `GET /tasks` contains it.
- Runs the image once more without `DATABASE_URL` (`--rm`, bounded wait 30 s): exit status non-zero and output
  containing `DATABASE_URL`. Prints `image-smoke: ok` or the failing step and the container logs.
- `devbox.json`: add own recipes `"image-smoke": "bash scripts/image_smoke.sh"` and
  `"ci-extra": "devbox run image-build && devbox run image-smoke"`; leave every template recipe unchanged.
- `.claude/project-notes.md`: the image needs `DATABASE_URL` and exits without it by design (AC-002.14); a smoke
  start of the image is `devbox run image-build && devbox run image-smoke`, not a bare `docker run`; tests need
  Docker (testcontainers) or `TEST_DATABASE_URL`.
- `README.md`: local run needs Postgres (`DATABASE_URL=... uvicorn ...`), mention `devbox run image-smoke`.

**Done when:** `devbox run image-build && devbox run image-smoke` prints `image-smoke: ok` against the image built
from t2 and t3, `devbox run secrets-scan` stays clean, and the `ci-extra` CI job runs the script.
