"""Task domain package."""

from taskboard4_api.tasks.store import TaskStore, get_task_store

__all__ = ["TaskStore", "get_task_store"]
