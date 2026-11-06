# Verification — 002 Keep tasks in Postgres, answer 503 and report not ready while the database is down

**Result:** pass
**Commit:** e33d416 · **Base:** e9310e7 · **Trace:** 14/14 criteria named by tests (all in `tests/test_postgres_storage.py`, none missing)

All acceptance tests run against a fresh Postgres database per test (`tests/conftest.py:38` `pg_url`, testcontainers `postgres:16-alpine` or `TEST_DATABASE_URL`). Outages go through the in-test TCP proxy `tests/pgproxy.py` (`refuse()` closes the listener and resets open connections with `SO_LINGER 0`; `blackhole()` holds connections without forwarding). Phase 3: `devbox run ci` green, including `image-smoke: ok`.

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_postgres_storage.py::test_tasks_survive_restart` | `src/taskboard4_api/tasks/store.py:37-43` (`ORDER BY seq`), `src/taskboard4_api/migrations.py:14-20` (table `tasks`), `src/taskboard4_api/main.py:34-47` (per-app `Database`) | Leaves the first app's lifespan and starts a fresh `create_app()` on the same URL; asserts `200` and `== [a, b]`, i.e. same `id`/`title`/`due_date`, A before B, B's due date `2026-12-31`. |
| AC-002.2 | met | `tests/test_postgres_storage.py::test_two_instances_share_one_list` | `src/taskboard4_api/tasks/store.py:41`, `src/taskboard4_api/main.py:56` (`create_app`) | A through instance one, B through instance two; both instances answer `200` with `[a, b]`. |
| AC-002.3 | met | `tests/test_postgres_storage.py::test_spec_001_contract_holds_on_postgres[0..18]`; `tests/test_tasks.py` (all AC-001.1–.9, .11, .12 tests) | `src/taskboard4_api/tasks/api.py:16-27` (unchanged routes/models), `src/taskboard4_api/tasks/store.py:20-35` | The 19 parametrized cases call every spec 001 test (including all 5 invalid titles and 4 invalid due dates) on a fresh Postgres database. `git diff` of `tests/test_tasks.py` changes only the `tclient` fixture (now the Postgres `client`) and deletes `test_restart_empties_list` (AC-001.10, withdrawn); no assertion changed. |
| AC-002.4 | met | `tests/test_postgres_storage.py::test_invalid_body_is_422_while_database_down[body0,body1]`, `::test_malformed_json_is_422_while_database_down` | `src/taskboard4_api/tasks/api.py:17` (`TaskCreate` body validated by FastAPI), `src/taskboard4_api/tasks/store.py:46-48` and `src/taskboard4_api/db.py:175-180` (dependency does no I/O) | Proxy refused before the call; `{"title": ""}` names `title`, `due_date: "2026-13-01"` names `due_date`, bad JSON gives `json_invalid`; all `422`. No `RequestValidationError` handler added (`main.py` has only the 503 and 500 handlers). |
| AC-002.5 | met | `tests/test_postgres_storage.py::test_503_when_database_refuses` | `src/taskboard4_api/db.py:127-128` (`OperationalError`/`InterfaceError` -> `DatabaseUnavailable`), `src/taskboard4_api/db.py:153-158` (connect timeout 3 s), `src/taskboard4_api/main.py:61-65` (503 handler) | `refuse()` both refuses new and resets open connections; POST and GET each assert `503`, body exactly `{"detail": "database unavailable"}`, elapsed `< 10` s. |
| AC-002.6 | met | `tests/test_postgres_storage.py::test_503_when_database_does_not_answer`, `::test_503_when_table_is_locked` | `src/taskboard4_api/db.py:97-102` (client-side deadline 7 s -> `timeout`), `src/taskboard4_api/db.py:156` (`statement_timeout=5000`) | Blackhole (accepts, never answers) and an `ACCESS EXCLUSIVE` lock held on a side connection; POST and GET both `503` with the exact body within 10 s. |
| AC-002.7 | met | `tests/test_postgres_storage.py::test_failed_create_stores_nothing`; supporting unit test `tests/test_db.py::test_deadline_rolls_back` | `src/taskboard4_api/db.py:120-123` (abandoned check before commit, rollback), `src/taskboard4_api/db.py:111-112` | POST answered `503` during the refusal; after `restore()` `GET /tasks` titles are exactly `["before"]`. The silent-database path (caller gave up, worker finishes later) is covered by the unit test, which asserts the late insert was not committed. |
| AC-002.8 | met | `tests/test_postgres_storage.py::test_ready_reflects_database` | `src/taskboard4_api/main.py:76-87`, `src/taskboard4_api/db.py:62-72` (`ping`, `READY_DEADLINE_S = 0.5`) | `200 {"status": "ready"}` when reachable; for both `refuse` and `blackhole` asserts `503 {"status": "not ready"}` and elapsed `< 1` s. |
| AC-002.9 | met | `tests/test_postgres_storage.py::test_health_ok_while_database_down` | `src/taskboard4_api/main.py:71-74` (no database access) | Two `/health` calls while refused, both `200 {"status": "ok"}`; the in-process app keeps serving between calls. |
| AC-002.10 | met | `tests/test_postgres_storage.py::test_recovers_without_restart` | `src/taskboard4_api/db.py:142-158` (stale idle connection dropped, fresh connect in the same checkout) | A, B, C created; refuse; `/ready` `503`; restore; the very next `/ready` is `200 {"status": "ready"}` and the next `GET /tasks` is `200` with `["A", "B", "C"]`, same client (no restart). |
| AC-002.11 | met | `tests/test_postgres_storage.py::test_starts_with_database_down_then_works` | `src/taskboard4_api/main.py:34-47` (lifespan does not connect), `src/taskboard4_api/db.py:134-140` (schema ensured on first operation, flag stays unset on failure) | Fresh database without schema, proxy refused before startup; startup succeeds, `/health` `200`, `/ready` `503`; after restore `/ready` `200`, POST `201`, list `["late"]`. |
| AC-002.12 | met | `tests/test_postgres_storage.py::test_two_instances_start_together` | `src/taskboard4_api/migrations.py:33-49` (`pg_advisory_xact_lock`, versioned, idempotent) | Two lifespans started behind a barrier on an empty database, each immediately calls `/ready` and creates a task concurrently; no errors; both `/ready` `200`; both lists identical with 3 tasks, the task from instance one is listed by instance two. |
| AC-002.13 | met | `tests/test_postgres_storage.py::test_database_url_schemes[postgres,postgresql]`; image level `scripts/image_smoke.sh:49` (`postgres://`) | `src/taskboard4_api/settings.py:12-17` (no rewriting; libpq parses both) | Each scheme: `/ready` `200`, POST `201`. |
| AC-002.14 | met | `tests/test_postgres_storage.py::test_missing_database_url_exits_nonzero`; image level `scripts/image_smoke.sh:83-94` | `src/taskboard4_api/main.py:37-41` (logs `config_missing` with `variable="DATABASE_URL"`, re-raises), `src/taskboard4_api/settings.py:14-16` | Real `uvicorn` subprocess without `DATABASE_URL`: process exits within 15 s, non-zero status, an output line contains `DATABASE_URL`, and the port never accepted a TCP connection (stronger than "/health never answered"). |

## Non-goals

- No migration of in-memory tasks, no backup/restore/retention code. ✔
- No retry of a failed database call and no queueing: a failed call raises `DatabaseUnavailable` straight to the 503 handler (`db.py:127-128`, `main.py:61-65`). Discarding a stale idle connection and connecting fresh within the same checkout (`db.py:142-158`) is connection validation, not a retry of the failed operation. ✔
- No new task endpoints, filters, pagination, users or extra fields (`tasks/api.py` unchanged; `tasks` table holds `seq` and `created_at` internally, never returned). ✔
- No storage limit. ✔
- No database error details reach callers: the 503 body is a constant (`main.py:65`); unexpected errors get `{"detail": "internal server error"}` (`main.py:67-69`). ✔
- Only `DATABASE_URL` is read by the service (`settings.py:14`). Observation, not a failure: libpq itself falls back to `PG*` environment variables for parts missing from the URL; the platform injects consistent values, so this has no effect in practice.
- Template-owned surface: `/health`, `/ready`, `/ping`, `/metrics`, middleware and logging/tracing setup kept (`main.py:23-25`, `58`, `89-97`); template devbox recipes unchanged, only `image-smoke` and `ci-extra` added. ✔

## Deviations from the plan

- `tests/conftest.py`, `tests/pgproxy.py`, `tests/test_postgres_storage.py`, `tests/test_tasks.py`: changed in the test phase (commit `e4b2d0a`), which the plan lists as a non-coder step. Acceptable.
- `tests/test_db.py`: in no task's `files`, but it is the coder's own unit/integration tests that t1's "Done when" demands. Acceptable.
- `docs/adr/001-postgres-access-psycopg-in-service-migrations.md` and the spec/design/plan files: planning artefacts, not code. Acceptable.
- `src/taskboard4_api/tasks/api.py` and `tasks/__init__.py` (t2 `files`, design "changed") are unchanged: the `StoreDep` alias already names `TaskStore`, so no edit was needed. Acceptable.
- All four tasks are `done: true`.

## Contract

Matches `design.md`: status codes and bodies for `POST /tasks`, `GET /tasks`, `/health`, `/ready`, 503 and 500; timeouts (`CONNECT_TIMEOUT_S = 3`, `STATEMENT_TIMEOUT_MS = 5000`, `POOL_WAIT_S = 2.0`, `OPERATION_DEADLINE_S = 7.0`, `READY_DEADLINE_S = 0.5`, `POOL_MAX_SIZE = 5`, executor `POOL_MAX_SIZE + 4`, `db.py:17-22,49`); public signatures of `settings.py`, `db.py`, `migrations.py`, `tasks/store.py`, `main.py`; migration DDL and the insert/list SQL. Minor, acceptable differences:

- `/ready` logs `database_unavailable` with `reason="ping_failed"` (`main.py:85`) instead of one of the `DatabaseUnavailable.reason` values, because `ping()` swallows the reason. Log content only; no caller-visible effect.
- `Database.run` maps a shut-down executor to `DatabaseUnavailable("not_initialized")` (`db.py:95-96`); an addition within the listed reasons.
- Connections are opened with `autocommit=True` and every operation uses an explicit `conn.transaction()` (`db.py:120`, `migrations.py:37`); equivalent to the design's "one transaction, commit".
