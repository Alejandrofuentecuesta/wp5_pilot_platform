"""Telemetry ingestion bounds: live sessions only, rate-limited, batched.

The endpoint stays deliberately tolerant (always 204), but out-of-bounds
requests must not write anything: telemetry is research data and a closed
session's behavioural record must not keep growing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main


SESSION_ID = "11111111-2222-3333-4444-555555555555"
BODY = {"events": [{"kind": "activity", "at": "2026-09-03T10:00:00Z",
                    "data": {"is_visible": True}}]}


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def reset_counters():
    main._telemetry_rate_counters.clear()
    yield
    main._telemetry_rate_counters.clear()


def _patched(session_row):
    return patch.multiple(
        main,
        _get_pool=MagicMock(return_value="pool"),
        session_repo=MagicMock(get_session=AsyncMock(return_value=session_row)),
        event_repo=MagicMock(insert_events=AsyncMock()),
    )


def _row(status="active", ended_ago_seconds=None):
    row = {"status": status, "experiment_id": "exp", "ended_at": None}
    if ended_ago_seconds is not None:
        row["ended_at"] = datetime.now(timezone.utc) - timedelta(seconds=ended_ago_seconds)
    return row


def _post(client, ip="9.9.9.9"):
    return client.post(
        f"/session/{SESSION_ID}/telemetry", json=BODY,
        headers={"X-Forwarded-For": ip},
    )


class TestSessionLiveness:
    def test_active_session_is_written_in_one_batch(self, client):
        with _patched(_row("active")):
            response = _post(client)
            insert = main.event_repo.insert_events.await_args
        assert response.status_code == 204
        assert insert is not None
        assert insert.kwargs["events"][0]["event_type"] == "client_activity"

    def test_ended_session_is_dropped(self, client):
        with _patched(_row("ended", ended_ago_seconds=3600)):
            response = _post(client)
            assert main.event_repo.insert_events.await_args is None
        assert response.status_code == 204

    def test_just_ended_session_gets_the_grace_window(self, client):
        """The final page_unload beacon can race the session end."""
        with _patched(_row("ended", ended_ago_seconds=30)):
            _post(client)
            assert main.event_repo.insert_events.await_args is not None

    def test_crashed_session_is_dropped(self, client):
        with _patched(_row("crashed")):
            _post(client)
            assert main.event_repo.insert_events.await_args is None


class TestRateLimit:
    def test_over_budget_requests_write_nothing(self, client):
        with _patched(_row("active")):
            for _ in range(main._TELEMETRY_RATE_LIMIT_PER_MINUTE):
                _post(client)
            main.event_repo.insert_events.reset_mock()
            response = _post(client)
            assert main.event_repo.insert_events.await_args is None
        assert response.status_code == 204  # still silent by design

    def test_budget_is_per_ip(self, client):
        with _patched(_row("active")):
            for _ in range(main._TELEMETRY_RATE_LIMIT_PER_MINUTE):
                _post(client, ip="9.9.9.9")
            main.event_repo.insert_events.reset_mock()
            _post(client, ip="8.8.8.8")
            assert main.event_repo.insert_events.await_args is not None
