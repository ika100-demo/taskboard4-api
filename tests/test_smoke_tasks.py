"""Smoke tests for spec 001 (AC-001.1, AC-001.9); base URL only."""

from __future__ import annotations

import json
import urllib.request
import uuid

import pytest


def _request(base: str, method: str, data: dict | None = None) -> tuple[int, object]:
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(  # noqa: S310
        base + "/tasks", data=body, method=method, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310  # nosec B310
        return response.status, json.load(response)


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    status, body = _request(smoke_base_url, "POST", {"title": title})
    assert status == 201
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == title
    assert body["due_date"] is None


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_9_list_in_creation_order(smoke_base_url: str) -> None:  # AC-001.9
    tag = f"smoke-{uuid.uuid4()}"
    created = [_request(smoke_base_url, "POST", {"title": f"{tag}-{n}"})[1] for n in "ABC"]
    status, listed = _request(smoke_base_url, "GET")
    assert status == 200
    mine = [t for t in listed if t["title"].startswith(tag)]
    assert mine == created


@pytest.mark.smoke
def test_smoke_list_tasks_is_json_array(smoke_base_url: str) -> None:  # AC-001.8
    status, body = _request(smoke_base_url, "GET")
    assert status == 200
    assert isinstance(body, list)
