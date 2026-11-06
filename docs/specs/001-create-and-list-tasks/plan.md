---
spec_id: 001-create-and-list-tasks
shape: service-python
spec_hash: 34387f221398
summary: In-memory tasks with POST /tasks (title, optional due date) and GET /tasks in creation order
tasks:
  - id: t1
    title: Add task models, validation and in-memory store
    files: [src/taskboard4_api/tasks/__init__.py, src/taskboard4_api/tasks/models.py, src/taskboard4_api/tasks/store.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.9, AC-001.10, AC-001.11, AC-001.12]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add POST /tasks and GET /tasks routes and wire them into the app
    files: [src/taskboard4_api/tasks/api.py, src/taskboard4_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11, AC-001.12]
    parallel_safe: false
    depends_on: [t1]
    done: true
---

# Plan — 001 Create and list tasks

The contract, error format and test seam are in [design.md](design.md) and are binding.

## t1 — Add task models, validation and in-memory store

**Files:** src/taskboard4_api/tasks/__init__.py, src/taskboard4_api/tasks/models.py, src/taskboard4_api/tasks/store.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.9, AC-001.10, AC-001.11, AC-001.12
**Goal:** The domain layer: request and response models that enforce every input rule of the spec, and a thread-safe, process-local store that hands out unique ids and keeps tasks in creation order.

**Implementation notes:**
- `models.py`: `Title = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]`. Trimming happens before the length check, so whitespace-only titles fail and padded titles are stored trimmed.
- `TaskCreate(title: Title, due_date: date | None = None)` with `extra="ignore"`. A `field_validator("due_date", mode="before")` accepts `None`. Anything else must be a `str` that fully matches `^\d{4}-\d{2}-\d{2}$` and parses with `date.fromisoformat`. Otherwise it raises `ValueError` so pydantic reports `loc` `["body", "due_date"]`. Do not use pydantic's lax `date` parsing (it accepts timestamps and zero-time datetimes).
- `Task(id: str, title: str, due_date: date | None)`. Pydantic serializes `date` as `YYYY-MM-DD` and `None` as `null`.
- `store.py`: `TaskStore` holds a `list[Task]` and a `threading.Lock`. `add(title, due_date) -> Task` builds the id with `str(uuid.uuid4())` and appends under the lock. `list() -> list[Task]` returns a copy under the lock.
- Module-level `_store = TaskStore()` and `def get_task_store() -> TaskStore: return _store`.
- `__init__.py` re-exports `TaskStore` and `get_task_store`. t2 adds the `router` re-export, so t2 must not need this file: import the router from `taskboard4_api.tasks.api` directly.
- Docstrings, full type hints, mypy-clean. No logging of titles (user content).

**Done when:** `devbox run quality` passes and model-level unit tests (the coder's own, in `tests/`) show: a valid title and date are accepted, past dates are accepted, each AC-001.4 / AC-001.5 / AC-001.6 invalid case raises a `ValidationError` on the right field, a 200-character title is accepted, `"  Buy milk  "` becomes `"Buy milk"`, two `add` calls return different ids, and `list()` keeps insertion order. The HTTP acceptance tests pass only after t2.

## t2 — Add POST /tasks and GET /tasks routes and wire them into the app

**Files:** src/taskboard4_api/tasks/api.py, src/taskboard4_api/main.py
**Covers:** AC-001.1 to AC-001.12
**Goal:** Expose the store over HTTP exactly as the contract in design.md describes and register the router on the existing app.

**Implementation notes:**
- `api.py`: `router = APIRouter(tags=["tasks"])`.
- `@router.post("/tasks", status_code=201, response_model=Task)` with `def create_task(body: TaskCreate, store: TaskStore = Depends(get_task_store)) -> Task`. It calls `store.add(body.title, body.due_date)`. Validation runs before the handler, so a rejected request never touches the store.
- `@router.get("/tasks", response_model=list[Task])` with `def list_tasks(store: TaskStore = Depends(get_task_store)) -> list[Task]`.
- Use sync `def` handlers, consistent with `main.py` (they run in the threadpool, and the store's lock covers it).
- Do not add a custom `RequestValidationError` handler. FastAPI's default 422 body (including `json_invalid` for malformed JSON) is the contract.
- `main.py`: `from .tasks.api import router as tasks_router` and `app.include_router(tasks_router)` after the middleware. Leave the existing routes untouched.
- Log one structured event per created task (`task_created`, `task_id` only) through the existing structlog setup.

**Done when:** every acceptance test for AC-001.1 to AC-001.12 passes, the existing health, metrics and tracing tests still pass, and `devbox run ci` is green (coverage gate included).
