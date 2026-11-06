# Verification — 001 Create and list tasks

**Result:** pass
**Commit:** dfbfd01 · **Base:** 7af9aef · **Trace:** 12/12 criteria named by tests (smoke: AC-001.1, AC-001.9)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_minimal_task_returns_201`, smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task` | `src/taskboard4_api/tasks/api.py:16-21`, `src/taskboard4_api/tasks/store.py:19` | asserts 201, non-empty string `id`, `title == "Buy milk"`, `due_date is None`, and exactly three keys (contract). The smoke test uses a `smoke-<uuid>` title, as design.md requires |
| AC-001.2 | met | `tests/test_tasks.py::test_create_with_due_date` | `src/taskboard4_api/tasks/models.py:25-36`, `models.py:44` | asserts 201 and `due_date == "2026-12-31"` |
| AC-001.3 | met | `tests/test_tasks.py::test_same_title_gives_distinct_ids` | `src/taskboard4_api/tasks/store.py:19` (`uuid4`) | two posts with the same title, ids differ |
| AC-001.4 | met | `tests/test_tasks.py::test_invalid_title_rejected` (with `{}`, `""`, `"   "`, `5`, `None`) | `src/taskboard4_api/tasks/models.py:9-12`, `models.py:22` | each case: 422, a `loc` ending in `title`, and `GET /tasks == []`. Strip-then-length handles whitespace only; `StrictStr` rejects non-strings |
| AC-001.5 | met | `tests/test_tasks.py::test_title_over_200_rejected`, `::test_title_of_200_accepted` | `src/taskboard4_api/tasks/models.py:11` | 201 characters gives 422 on `title` with nothing added; exactly 200 gives 201 with the title unchanged |
| AC-001.6 | met | `tests/test_tasks.py::test_invalid_due_date_rejected` (with `2026-13-01`, `2026-02-30`, `tomorrow`, `2026-12-31T10:00:00Z`) | `src/taskboard4_api/tasks/models.py:14`, `models.py:25-36` | each of the four examples from the spec: 422, `loc` ends in `due_date`, nothing added. The full-match regex rejects the datetime form; `fromisoformat` rejects dates that do not exist |
| AC-001.7 | met | `tests/test_tasks.py::test_malformed_json_rejected` | FastAPI default handling (no custom handler; `src/taskboard4_api/tasks/api.py:17` request body model) | asserts 422, an entry with `type == "json_invalid"` (contract), and an empty list afterwards |
| AC-001.8 | met | `tests/test_tasks.py::test_list_empty_initially` | `src/taskboard4_api/tasks/api.py:24-27`, `store.py:24-27` | 200 and `[]` on a fresh store |
| AC-001.9 | met | `tests/test_tasks.py::test_list_in_creation_order`, smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_9_list_in_creation_order` | `src/taskboard4_api/tasks/store.py:20-21` (append under lock), `store.py:24-27` | the list equals the three created response bodies in order (same id, title and due_date), and the titles are `A, B, C`. The smoke test filters on its own tag, as design.md requires |
| AC-001.10 | met | `tests/test_tasks.py::test_restart_empties_list` | `src/taskboard4_api/tasks/store.py:30-35` (process-local module singleton, no persistence) | the test simulates a restart with a fresh `TaskStore()` through the seam that design.md makes binding. The code has no persistence, so a real restart starts empty |
| AC-001.11 | met | `tests/test_tasks.py::test_title_is_trimmed` | `src/taskboard4_api/tasks/models.py:11` (`strip_whitespace=True`) | the POST response and the later GET both return `"Buy milk"` |
| AC-001.12 | met | `tests/test_tasks.py::test_past_due_date_accepted` | `src/taskboard4_api/tasks/models.py:25-36` (no check against today) | 201 with `due_date == "2020-01-01"` |

## Non-goals

- No persistence and no sharing between replicas: there is only the in-memory list (`store.py:14`). ✔
- No single-task read, update, complete or delete routes. `api.py` defines only `POST /tasks` and `GET /tasks`. ✔
- No filtering, sorting, searching or pagination: `list_tasks` takes no query parameters. ✔
- No users or auth. ✔ No due times: datetime strings are rejected (`models.py:31`). ✔ No cap on the task count. ✔
- No fields beyond `id`, `title` and `due_date` (`models.py:39-44`); extra input keys are ignored (`models.py:20`). ✔
- Template-owned layout: `main.py` gains only the router import and `app.include_router(tasks_router)` (2 lines). The existing health, ready, ping and metrics routes are untouched. ✔
- Logging sends only `task_id`, never the title (`api.py:20`). ✔

## Deviations from the plan

- **t2 `Depends` via `StoreDep = Annotated[TaskStore, Depends(get_task_store)]`** (`api.py:11`) instead of a default argument. This was done to satisfy ruff B008. The dependency key is the same `get_task_store`, so `app.dependency_overrides` behaves the same way. Acceptable.
- **`tests/test_task_models.py`** is in no task's `files`. t1's "Done when" asks for exactly these coder unit tests in `tests/`. Acceptable.
- **`tests/test_tasks.py` changed after the red commit 91baa09**: only the order of the local imports in the `tclient` fixture and in `test_restart_empties_list` (from lint-fix). No assertion or criterion id changed, and the user approved the change. Acceptable.
- **`tests/test_smoke_tasks.py::test_smoke_list_tasks_is_json_array`** is an extra read-only smoke check that carries the `AC-001.8` comment. It only asserts a 200 status and a JSON array, not `[]`. It does not prove AC-001.8; `test_list_empty_initially` does. It exists because CLAUDE.md requires a read-only smoke check for staging and prod. Acceptable. The comment overstates what the test proves, so it could be reworded later.
- Both tasks t1 and t2 are `done: true`. ✔

## Contract

- The status codes (201, 200, 422), the bare-array GET, the three-key task object, the `YYYY-MM-DD` serialization and FastAPI's default 422 body all match `design.md`. ✔
- The signatures of `TaskCreate`, `Task`, `TaskStore.add` and `TaskStore.list` and of `get_task_store` match the public interfaces in design.md. ✔
- Small difference: in design.md's module table, `tasks/__init__.py` re-exports `router`. The built `__init__.py:3-5` re-exports only `TaskStore` and `get_task_store`. The plan has `main.py` import the router from `tasks.api` directly, and no task lists `__init__.py` for t2. No caller depends on the re-export. Acceptable.
