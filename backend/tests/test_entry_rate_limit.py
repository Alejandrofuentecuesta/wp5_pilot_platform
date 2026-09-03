"""Per-IP rate limit on the participant entry endpoints.

A real participant makes a handful of intake/start requests; scripted
arrivals make thousands. Above the per-minute budget the endpoints return
429 before touching the database.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def reset_counters():
    main._entry_rate_counters.clear()
    yield
    main._entry_rate_counters.clear()


def _no_pool():
    # The rate limit must fire before any DB access; with no pool the
    # non-throttled requests surface as 503.
    return patch.object(
        main, "_get_pool",
        MagicMock(side_effect=HTTPException(status_code=503, detail="down")),
    )


@pytest.mark.parametrize("path,body", [
    ("/session/intake", {"token": "sometoken-123"}),
    ("/session/start", {"token": "sometoken-123"}),
])
def test_budget_then_429(client, path, body):
    with _no_pool():
        for _ in range(main._ENTRY_RATE_LIMIT_PER_MINUTE):
            response = client.post(path, json=body, headers={"X-Forwarded-For": "1.2.3.4"})
            assert response.status_code == 503
        throttled = client.post(path, json=body, headers={"X-Forwarded-For": "1.2.3.4"})
    assert throttled.status_code == 429


def test_budget_is_per_ip(client):
    with _no_pool():
        for _ in range(main._ENTRY_RATE_LIMIT_PER_MINUTE):
            client.post("/session/intake", json={"token": "sometoken-123"},
                        headers={"X-Forwarded-For": "1.2.3.4"})
        other = client.post("/session/intake", json={"token": "sometoken-123"},
                            headers={"X-Forwarded-For": "5.6.7.8"})
    assert other.status_code == 503  # fresh IP, fresh budget


def test_intake_and_start_share_one_budget(client):
    with _no_pool():
        for _ in range(main._ENTRY_RATE_LIMIT_PER_MINUTE):
            client.post("/session/intake", json={"token": "sometoken-123"},
                        headers={"X-Forwarded-For": "1.2.3.4"})
        response = client.post("/session/start", json={"token": "sometoken-123"},
                               headers={"X-Forwarded-For": "1.2.3.4"})
    assert response.status_code == 429
