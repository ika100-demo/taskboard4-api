"""Acceptance tests for spec 002: tasks in Postgres, 503 and not-ready on database outage."""

from __future__ import annotations

import os
import socket
import subprocess  # nosec B404 - tests start the service as a subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pgproxy import PgProxy

UNAVAILABLE = {"detail": "database unavailable"}
Factory = Callable[[str], TestClient]
ROOT = Path(__file__).resolve().parent.parent


def _titles(c: TestClient) -> list[str]:
    return [t["title"] for t in c.get("/tasks").json()]


def test_tasks_survive_restart(pg_url: str, make_client: Factory) -> None:  # AC-002.1
    first = make_client(pg_url)
    a = first.post("/tasks", json={"title": "A"}).json()
    b = first.post("/tasks", json={"title": "B", "due_date": "2026-12-31"}).json()
    first.__exit__(None, None, None)
    second = make_client(pg_url)
    r = second.get("/tasks")
    assert r.status_code == 200
    assert r.json() == [a, b]
    assert b["due_date"] == "2026-12-31"


def test_two_instances_share_one_list(pg_url: str, make_client: Factory) -> None:  # AC-002.2
    one, two = make_client(pg_url), make_client(pg_url)
    a = one.post("/tasks", json={"title": "A"}).json()
    b = two.post("/tasks", json={"title": "B", "due_date": "2026-12-31"}).json()
    for c in (one, two):
        r = c.get("/tasks")
        assert r.status_code == 200
        assert r.json() == [a, b]


def _contract_checks() -> list[Callable[[TestClient], None]]:
    import test_tasks as t

    checks: list[Callable[[TestClient], None]] = [
        t.test_create_minimal_task_returns_201,
        t.test_create_with_due_date,
        t.test_same_title_gives_distinct_ids,
        t.test_title_over_200_rejected,
        t.test_title_of_200_accepted,
        t.test_malformed_json_rejected,
        t.test_list_empty_initially,
        t.test_list_in_creation_order,
        t.test_title_is_trimmed,
        t.test_past_due_date_accepted,
    ]
    for payload in ({}, {"title": ""}, {"title": "   "}, {"title": 5}, {"title": None}):
        checks.append(lambda c, p=payload: t.test_invalid_title_rejected(c, p))
    for due in ("2026-13-01", "2026-02-30", "tomorrow", "2026-12-31T10:00:00Z"):
        checks.append(lambda c, d=due: t.test_invalid_due_date_rejected(c, d))
    return checks


@pytest.mark.parametrize("index", range(19))
def test_spec_001_contract_holds_on_postgres(  # AC-002.3
    client: TestClient, index: int
) -> None:
    # Spec 001 checks (AC-001.1 to .9, .11, .12), each on a fresh Postgres database.
    _contract_checks()[index](client)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"title": ""}, "title"),
        ({"title": "x", "due_date": "2026-13-01"}, "due_date"),
    ],
)
def test_invalid_body_is_422_while_database_down(  # AC-002.4
    pg_proxy: PgProxy, make_client: Factory, body: dict, field: str
) -> None:
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    pg_proxy.refuse()
    r = c.post("/tasks", json=body)
    assert r.status_code == 422
    assert any(e["loc"][-1] == field for e in r.json()["detail"])


def test_malformed_json_is_422_while_database_down(  # AC-002.4
    pg_proxy: PgProxy, make_client: Factory
) -> None:
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    pg_proxy.refuse()
    r = c.post("/tasks", content=b"{nope", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert any(e["type"] == "json_invalid" for e in r.json()["detail"])


def test_503_when_database_refuses(pg_proxy: PgProxy, make_client: Factory) -> None:  # AC-002.5
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    assert c.post("/tasks", json={"title": "before"}).status_code == 201
    pg_proxy.refuse()
    for call in (lambda: c.post("/tasks", json={"title": "x"}), lambda: c.get("/tasks")):
        start = time.monotonic()
        r = call()
        assert r.status_code == 503
        assert r.json() == UNAVAILABLE
        assert time.monotonic() - start < 10


def test_503_when_database_does_not_answer(  # AC-002.6
    pg_proxy: PgProxy, make_client: Factory
) -> None:
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    assert c.post("/tasks", json={"title": "before"}).status_code == 201
    pg_proxy.blackhole()
    for call in (lambda: c.post("/tasks", json={"title": "x"}), lambda: c.get("/tasks")):
        start = time.monotonic()
        r = call()
        assert r.status_code == 503
        assert r.json() == UNAVAILABLE
        assert time.monotonic() - start < 10


def test_503_when_table_is_locked(pg_url: str, make_client: Factory) -> None:  # AC-002.6
    c = make_client(pg_url)
    assert c.post("/tasks", json={"title": "before"}).status_code == 201
    side = psycopg.connect(pg_url)
    try:
        side.execute("LOCK TABLE tasks IN ACCESS EXCLUSIVE MODE")
        for call in (lambda: c.post("/tasks", json={"title": "x"}), lambda: c.get("/tasks")):
            start = time.monotonic()
            r = call()
            assert r.status_code == 503
            assert r.json() == UNAVAILABLE
            assert time.monotonic() - start < 10
    finally:
        side.close()


def test_failed_create_stores_nothing(pg_proxy: PgProxy, make_client: Factory) -> None:  # AC-002.7
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    assert c.post("/tasks", json={"title": "before"}).status_code == 201
    pg_proxy.refuse()
    assert c.post("/tasks", json={"title": "lost-during-outage"}).status_code == 503
    pg_proxy.restore()
    assert _titles(c) == ["before"]


def test_ready_reflects_database(pg_proxy: PgProxy, make_client: Factory) -> None:  # AC-002.8
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    r = c.get("/ready")
    assert (r.status_code, r.json()) == (200, {"status": "ready"})
    for down in (pg_proxy.refuse, pg_proxy.blackhole):
        down()
        start = time.monotonic()
        r = c.get("/ready")
        assert time.monotonic() - start < 1
        assert (r.status_code, r.json()) == (503, {"status": "not ready"})
        pg_proxy.restore()
        assert c.get("/ready").status_code == 200


def test_health_ok_while_database_down(pg_proxy: PgProxy, make_client: Factory) -> None:  # AC-002.9
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    pg_proxy.refuse()
    for _ in range(2):
        r = c.get("/health")
        assert (r.status_code, r.json()) == (200, {"status": "ok"})


def test_recovers_without_restart(pg_proxy: PgProxy, make_client: Factory) -> None:  # AC-002.10
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    titles = ["A", "B", "C"]
    for t in titles:
        assert c.post("/tasks", json={"title": t}).status_code == 201
    pg_proxy.refuse()
    assert c.get("/ready").status_code == 503
    pg_proxy.restore()
    r = c.get("/ready")
    assert (r.status_code, r.json()) == (200, {"status": "ready"})
    r = c.get("/tasks")
    assert r.status_code == 200
    assert [t["title"] for t in r.json()] == titles


def test_starts_with_database_down_then_works(  # AC-002.11
    pg_proxy: PgProxy, make_client: Factory
) -> None:
    pg_proxy.refuse()
    c = make_client(pg_proxy.url)  # type: ignore[attr-defined]
    assert c.get("/health").status_code == 200
    assert c.get("/ready").status_code == 503
    pg_proxy.restore()
    r = c.get("/ready")
    assert (r.status_code, r.json()) == (200, {"status": "ready"})
    assert c.post("/tasks", json={"title": "late"}).status_code == 201
    assert _titles(c) == ["late"]


def test_two_instances_start_together(  # AC-002.12
    pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from taskboard4_api.main import create_app

    monkeypatch.setenv("DATABASE_URL", pg_url)
    clients = [TestClient(create_app()) for _ in range(2)]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def start(c: TestClient) -> None:
        try:
            barrier.wait()
            c.__enter__()
            assert c.get("/ready").status_code == 200
            assert c.post("/tasks", json={"title": "x"}).status_code == 201
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=start, args=(c,)) for c in clients]
    for th in threads:
        th.start()
    for th in threads:
        th.join(30)
    try:
        assert not errors
        for c in clients:
            assert c.get("/ready").status_code == 200
        one, two = clients
        t = one.post("/tasks", json={"title": "from-one"}).json()
        assert t in two.get("/tasks").json()
        assert _titles(one) == _titles(two)
        assert len(_titles(one)) == 3
    finally:
        for c in clients:
            c.__exit__(None, None, None)


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_database_url_schemes(pg_url: str, make_client: Factory, scheme: str) -> None:  # AC-002.13
    url = scheme + "://" + pg_url.split("://", 1)[1]
    c = make_client(url)
    assert c.get("/ready").status_code == 200
    assert c.post("/tasks", json={"title": "T"}).status_code == 201


def test_missing_database_url_exits_nonzero() -> None:  # AC-002.14
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    proc = subprocess.Popen(  # nosec B603
        [sys.executable, "-m", "uvicorn", "taskboard4_api.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    answered = False
    deadline = time.monotonic() + 15
    try:
        while proc.poll() is None and time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    answered = True
            except OSError:
                pass
            time.sleep(0.1)
        assert proc.poll() is not None, "process kept running without DATABASE_URL"
        out = proc.communicate(timeout=5)[0]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode != 0
    assert any("DATABASE_URL" in line for line in out.splitlines())
    assert not answered
