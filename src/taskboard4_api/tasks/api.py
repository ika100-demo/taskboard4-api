"""HTTP routes for tasks."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends

from taskboard4_api.tasks.models import Task, TaskCreate
from taskboard4_api.tasks.store import TaskStore, get_task_store

StoreDep = Annotated[TaskStore, Depends(get_task_store)]
router = APIRouter(tags=["tasks"])
logger = structlog.get_logger()


@router.post("/tasks", status_code=201, response_model=Task)
def create_task(body: TaskCreate, store: StoreDep) -> Task:
    """Create a task."""
    task = store.add(body.title, body.due_date)
    logger.info("task_created", task_id=task.id)
    return task


@router.get("/tasks", response_model=list[Task])
def list_tasks(store: StoreDep) -> list[Task]:
    """List tasks, oldest first."""
    return store.list()
