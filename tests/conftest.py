"""Shared pytest fixtures: a fresh Postgres database per test and the app built over it."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from pgproxy import PgProxy


def with_database(server_url: str, name: str) -> str:
    """Return `server_url` pointing at database `name`."""
    parts = urlsplit(server_url)
    return urlunsplit(parts._replace(path=f"/{name}"))


@pytest.fixture(scope="session")
def pg_server_url() -> Iterator[str]:
    """URL of a Postgres server that may create databases."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if url:
        yield url
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        raw = pg.get_connection_url()
        yield raw.replace("postgresql+psycopg2://", "postgresql://").replace(
            "postgresql+psycopg://", "postgresql://"
        )


@pytest.fixture()
def pg_url(pg_server_url: str) -> Iterator[str]:
    """URL of a fresh, empty database (no schema), dropped on teardown."""
    name = f"t_{uuid.uuid4().hex}"
    with psycopg.connect(pg_server_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield with_database(pg_server_url, name)
    finally:
        with psycopg.connect(pg_server_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture()
def pg_proxy(pg_url: str) -> Iterator[PgProxy]:
    """A TCP proxy in front of the fresh database; `.url` is the URL through it."""
    parts = urlsplit(pg_url)
    proxy = PgProxy(parts.hostname or "127.0.0.1", parts.port or 5432)
    proxy.start()
    netloc = f"{parts.username}:{parts.password}@127.0.0.1:{proxy.port}"
    proxy.url = urlunsplit(parts._replace(netloc=netloc))  # type: ignore[attr-defined]
    try:
        yield proxy
    finally:
        proxy.stop()


@pytest.fixture()
def make_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], TestClient]]:
    """Factory: start an app instance (lifespan run) over `url`; closed on teardown."""
    from taskboard4_api.main import create_app

    opened: list[TestClient] = []

    def _make(url: str) -> TestClient:
        monkeypatch.setenv("DATABASE_URL", url)
        c = TestClient(create_app())
        c.__enter__()
        opened.append(c)
        return c

    try:
        yield _make
    finally:
        for c in reversed(opened):
            try:
                c.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 - teardown must not mask the test result
                pass


@pytest.fixture()
def client(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient for the app over a fresh Postgres database."""
    from taskboard4_api.main import create_app

    monkeypatch.setenv("DATABASE_URL", pg_url)
    with TestClient(create_app()) as c:
        yield c
