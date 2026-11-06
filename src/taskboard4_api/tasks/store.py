"""Thread-safe, process-local in-memory task store."""

import threading
import uuid
from datetime import date

from taskboard4_api.tasks.models import Task


class TaskStore:
    """Keeps tasks in creation order in memory."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def add(self, title: str, due_date: date | None) -> Task:
        """Create a task with a fresh uuid4 id and append it."""
        task = Task(id=str(uuid.uuid4()), title=title, due_date=due_date)
        with self._lock:
            self._tasks.append(task)
        return task

    def list(self) -> list[Task]:
        """Return a copy of all tasks in creation order."""
        with self._lock:
            return list(self._tasks)


_store = TaskStore()


def get_task_store() -> TaskStore:
    """Return the process-wide task store."""
    return _store
