"""Unit tests for task models and the in-memory store."""

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from taskboard4_api.tasks.models import TaskCreate
from taskboard4_api.tasks.store import TaskStore


def _fields(exc: ValidationError) -> set[str]:
    return {str(e["loc"][0]) for e in exc.errors()}


def test_valid_title_and_date() -> None:
    t = TaskCreate(title="File taxes", due_date="2026-12-31")  # type: ignore[arg-type]
    assert t.due_date == date(2026, 12, 31)
    assert TaskCreate(title="x").due_date is None


def test_past_date_accepted() -> None:
    t = TaskCreate(title="Overdue", due_date="2020-01-01")  # type: ignore[arg-type]
    assert t.due_date == date(2020, 1, 1)


def test_title_trimmed() -> None:
    assert TaskCreate(title="  Buy milk  ").title == "Buy milk"


def test_title_200_accepted() -> None:
    assert len(TaskCreate(title="a" * 200).title) == 200


@pytest.mark.parametrize("title", ["", "   ", "a" * 201, 5, None, ["x"]])
def test_invalid_title(title: Any) -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate(title=title)
    assert _fields(ei.value) == {"title"}


def test_missing_title() -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate.model_validate({})
    assert _fields(ei.value) == {"title"}


@pytest.mark.parametrize(
    "bad",
    ["2026-13-01", "2026-02-30", "tomorrow", "2026-12-31T10:00:00Z", 20261231, ""],
)
def test_invalid_due_date(bad: Any) -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate(title="x", due_date=bad)
    assert _fields(ei.value) == {"due_date"}


def test_store_unique_ids_and_order() -> None:
    store = TaskStore()
    a = store.add("same", None)
    b = store.add("same", date(2026, 1, 1))
    c = store.add("C", None)
    assert a.id and a.id != b.id
    assert [t.id for t in store.list()] == [a.id, b.id, c.id]
    store.list().clear()
    assert len(store.list()) == 3
