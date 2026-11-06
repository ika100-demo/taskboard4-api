"""Unit/integration tests of the settings, database layer and migration (task t1)."""

from __future__ import annotations

import threading
import time
import uuid

import psycopg
import pytest

from taskboard4_api.db import Database, DatabaseUnavailable, get_database
from taskboard4_api.migrations import ensure_schema
from taskboard4_api.settings import MissingSetting, load_database_url

UNREACHABLE = "postgresql://x:y@127.0.0.1:1/z"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_load_database_url_missing(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(MissingSetting, match="DATABASE_URL is not set"):
        load_database_url()


def test_load_database_url_strips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "  postgres://a@h/d \n")
    assert load_database_url() == "postgres://a@h/d"


def test_run_returns_and_commits(pg_url: str) -> None:
    db = Database(pg_url)
    try:
        tid = uuid.uuid4()
        db.run(lambda c: c.execute("INSERT INTO tasks (id, title) VALUES (%s, 'a')", (tid,)))
        rows = db.run(lambda c: c.execute("SELECT id FROM tasks").fetchall())
        assert rows == [(tid,)]
    finally:
        db.close()


def test_unreachable_raises_quickly() -> None:
    db = Database(UNREACHABLE)
    start = time.monotonic()
    with pytest.raises(DatabaseUnavailable) as info:
        db.run(lambda c: c.execute("SELECT 1"))
    assert time.monotonic() - start < 3
    assert info.value.reason == "connection"
    db.close()


def test_deadline_rolls_back(pg_url: str) -> None:
    db = Database(pg_url)
    try:
        db.run(lambda c: c.execute("SELECT 1"))  # create the schema

        def slow(conn: psycopg.Connection) -> None:
            conn.execute("INSERT INTO tasks (id, title) VALUES (%s, 'slow')", (uuid.uuid4(),))
            time.sleep(1.5)

        start = time.monotonic()
        with pytest.raises(DatabaseUnavailable) as info:
            db.run(slow, deadline=0.5)
        elapsed = time.monotonic() - start
        assert info.value.reason == "timeout"
        assert 0.4 < elapsed < 1.2
        time.sleep(1.5)  # let the worker finish
        assert db.run(lambda c: c.execute("SELECT count(*) FROM tasks").fetchone()) == (0,)
    finally:
        db.close()


def test_ensure_schema_concurrent(pg_url: str) -> None:
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            with psycopg.connect(pg_url, autocommit=True) as conn:
                barrier.wait()
                ensure_schema(conn)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM schema_version").fetchone() == (1,)
        assert conn.execute("SELECT to_regclass('tasks')").fetchone() is not None


def test_ping(pg_url: str) -> None:
    good, bad = Database(pg_url), Database(UNREACHABLE)
    try:
        assert good.ping() is True
        start = time.monotonic()
        assert bad.ping() is False
        assert time.monotonic() - start < 1
    finally:
        good.close()
        bad.close()


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_both_schemes(pg_url: str, scheme: str) -> None:
    url = scheme + "://" + pg_url.split("://", 1)[1]
    db = Database(url)
    try:
        assert db.ping() is True
        assert db.run(lambda c: c.execute("SELECT 1").fetchone()) == (1,)
    finally:
        db.close()


def test_get_database_not_initialized() -> None:
    class _State:
        pass

    class _App:
        state = _State()

    class _Req:
        app = _App()

    with pytest.raises(DatabaseUnavailable) as info:
        get_database(_Req())  # type: ignore[arg-type]
    assert info.value.reason == "not_initialized"
