"""Acceptance tests for spec 001: create and list tasks."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

LONG = "x" * 200


@pytest.fixture()
def tclient() -> Iterator[TestClient]:
    """A client with an empty task store injected."""
    from taskboard4_api.tasks.store import TaskStore, get_task_store

    from taskboard4_api.main import app

    store = TaskStore()
    app.dependency_overrides[get_task_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_task_store, None)


def _names_field(response, field: str) -> bool:
    detail = response.json()["detail"]
    return bool(detail) and any(e["loc"][-1] == field for e in detail)


def _assert_rejected(c: TestClient, payload, field: str) -> None:
    r = c.post("/tasks", json=payload)
    assert r.status_code == 422
    assert _names_field(r, field)
    assert c.get("/tasks").json() == []


def test_create_minimal_task_returns_201(tclient: TestClient) -> None:  # AC-001.1
    r = tclient.post("/tasks", json={"title": "Buy milk"})
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] is None
    assert set(body) == {"id", "title", "due_date"}


def test_create_with_due_date(tclient: TestClient) -> None:  # AC-001.2
    r = tclient.post("/tasks", json={"title": "File taxes", "due_date": "2026-12-31"})
    assert r.status_code == 201
    assert r.json()["due_date"] == "2026-12-31"


def test_same_title_gives_distinct_ids(tclient: TestClient) -> None:  # AC-001.3
    a = tclient.post("/tasks", json={"title": "Same"}).json()
    b = tclient.post("/tasks", json={"title": "Same"}).json()
    assert a["id"] != b["id"]


@pytest.mark.parametrize(
    "payload", [{}, {"title": ""}, {"title": "   "}, {"title": 5}, {"title": None}]
)
def test_invalid_title_rejected(tclient: TestClient, payload: dict) -> None:  # AC-001.4
    _assert_rejected(tclient, payload, "title")


def test_title_over_200_rejected(tclient: TestClient) -> None:  # AC-001.5
    _assert_rejected(tclient, {"title": LONG + "x"}, "title")


def test_title_of_200_accepted(tclient: TestClient) -> None:  # AC-001.5
    r = tclient.post("/tasks", json={"title": LONG})
    assert r.status_code == 201
    assert r.json()["title"] == LONG


@pytest.mark.parametrize("due", ["2026-13-01", "2026-02-30", "tomorrow", "2026-12-31T10:00:00Z"])
def test_invalid_due_date_rejected(tclient: TestClient, due: str) -> None:  # AC-001.6
    _assert_rejected(tclient, {"title": "T", "due_date": due}, "due_date")


def test_malformed_json_rejected(tclient: TestClient) -> None:  # AC-001.7
    r = tclient.post("/tasks", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert any(e["type"] == "json_invalid" for e in r.json()["detail"])
    assert tclient.get("/tasks").json() == []


def test_list_empty_initially(tclient: TestClient) -> None:  # AC-001.8
    r = tclient.get("/tasks")
    assert r.status_code == 200
    assert r.json() == []


def test_list_in_creation_order(tclient: TestClient) -> None:  # AC-001.9
    created = [tclient.post("/tasks", json={"title": t}).json() for t in ("A", "B", "C")]
    r = tclient.get("/tasks")
    assert r.status_code == 200
    assert r.json() == created
    assert [t["title"] for t in r.json()] == ["A", "B", "C"]


def test_restart_empties_list() -> None:  # AC-001.10
    from taskboard4_api.tasks.store import TaskStore, get_task_store

    from taskboard4_api.main import app

    first, second = TaskStore(), TaskStore()
    try:
        app.dependency_overrides[get_task_store] = lambda: first
        c = TestClient(app)
        assert c.post("/tasks", json={"title": "Keep"}).status_code == 201
        assert len(c.get("/tasks").json()) == 1
        app.dependency_overrides[get_task_store] = lambda: second
        r = c.get("/tasks")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_task_store, None)


def test_title_is_trimmed(tclient: TestClient) -> None:  # AC-001.11
    r = tclient.post("/tasks", json={"title": "  Buy milk  "})
    assert r.status_code == 201
    assert r.json()["title"] == "Buy milk"
    assert tclient.get("/tasks").json()[0]["title"] == "Buy milk"


def test_past_due_date_accepted(tclient: TestClient) -> None:  # AC-001.12
    r = tclient.post("/tasks", json={"title": "Overdue", "due_date": "2020-01-01"})
    assert r.status_code == 201
    assert r.json()["due_date"] == "2020-01-01"
