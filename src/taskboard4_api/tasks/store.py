"""Postgres-backed task store."""

import uuid
from datetime import date
from typing import Annotated

import psycopg
from fastapi import Depends

from taskboard4_api.db import Database, get_database
from taskboard4_api.tasks.models import Task


class TaskStore:
    """Keeps tasks in the `tasks` table, listed in creation order (`seq`)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, title: str, due_date: date | None) -> Task:
        """Create a task with a fresh uuid4 id and insert it."""
        task_id = uuid.uuid4()

        def op(conn: psycopg.Connection) -> tuple[object, str, date | None]:
            row = conn.execute(
                "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s) "
                "RETURNING id, title, due_date",
                (task_id, title, due_date),
            ).fetchone()
            assert row is not None  # noqa: S101 - RETURNING always yields a row
            return row

        row_id, row_title, row_due = self._db.run(op)
        return Task(id=str(row_id), title=row_title, due_date=row_due)

    def list(self) -> list[Task]:
        """Return all tasks in creation order."""

        def op(conn: psycopg.Connection) -> list[tuple[object, str, date | None]]:
            return conn.execute("SELECT id, title, due_date FROM tasks ORDER BY seq").fetchall()

        return [Task(id=str(i), title=t, due_date=d) for i, t, d in self._db.run(op)]


def get_task_store(db: Annotated[Database, Depends(get_database)]) -> TaskStore:
    """Build a store for this request."""
    return TaskStore(db)
