"""Participant erasure endpoint: preview by default, delete only on confirm.

The endpoint is destructive, so the tests pin its safety properties: an
unknown token 404s, a call without confirm deletes nothing, a mismatched
confirm deletes nothing, and a confirmed call deletes every table in one
transaction plus the token row and the per-session export CSV.
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main


TOKEN = "erase-me-token-123"
SESSION_ID = "11111111-2222-3333-4444-555555555555"


class _FakeConn:
    def __init__(self):
        self.executed: list[tuple] = []

    async def fetch(self, query, *args):
        return [{"session_id": SESSION_ID}]

    async def fetchval(self, query, *args):
        return 7

    async def execute(self, query, *args):
        self.executed.append((query.strip().split()[0], query, args))

    def transaction(self):
        @contextlib.asynccontextmanager
        async def _tx():
            yield
        return _tx()


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        @contextlib.asynccontextmanager
        async def _acquire():
            yield self._conn
        return _acquire()


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def _patched(conn, token_exists=True, tmp_path=None):
    token_row = {"token": TOKEN, "used": True} if token_exists else None
    patches = dict(
        _get_pool=MagicMock(return_value=_FakePool(conn)),
        token_repo=MagicMock(get_token_status=AsyncMock(return_value=token_row)),
        session_manager=MagicMock(get_session=AsyncMock(return_value=None)),
        redis_client=MagicMock(get_redis=MagicMock(), invalidate_session=AsyncMock()),
        _require_admin=lambda key: None,
    )
    return patch.multiple(main, **patches)


def _post(client, body):
    return client.post("/admin/erase-participant", json=body)


def test_unknown_token_is_404(client):
    conn = _FakeConn()
    with _patched(conn, token_exists=False):
        response = _post(client, {"token": TOKEN, "confirm": TOKEN})
    assert response.status_code == 404
    assert conn.executed == []


def test_without_confirm_returns_preview_and_deletes_nothing(client):
    conn = _FakeConn()
    with _patched(conn):
        response = _post(client, {"token": TOKEN})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "preview"
    assert payload["rows"]["sessions"] == 1
    assert payload["rows"]["messages"] == 7
    assert conn.executed == []


def test_mismatched_confirm_deletes_nothing(client):
    conn = _FakeConn()
    with _patched(conn):
        response = _post(client, {"token": TOKEN, "confirm": "erase-me-typo-123"})
    assert response.json()["status"] == "preview"
    assert conn.executed == []


def test_confirmed_erase_deletes_all_tables_and_token(client, tmp_path):
    csv_file = tmp_path / f"{SESSION_ID}.csv"
    csv_file.write_text("message\nhola\n")
    conn = _FakeConn()
    with _patched(conn), patch.dict(
        "os.environ", {"SESSION_CSV_EXPORT_DIR": str(tmp_path)}
    ):
        response = _post(client, {"token": TOKEN, "confirm": TOKEN})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "erased"
    deleted_tables = [q for kind, q, _ in conn.executed if kind == "DELETE"]
    for table in ("manual_message_evaluations", "events", "agent_blocks",
                  "messages", "sessions", "tokens"):
        assert any(table in q for q in deleted_tables), table
    assert not csv_file.exists()
    assert payload["export_files"] == [csv_file.name]


def test_erase_requires_admin(client):
    # Without the _require_admin patch the real gate must reject.
    with patch.object(main, "ADMIN_PASSPHRASE", "right"), \
         patch.object(main, "_admin_failures", {"count": 0, "last_at": 0.0}):
        response = client.post(
            "/admin/erase-participant",
            json={"token": TOKEN},
            headers={"X-Admin-Key": "wrong"},
        )
    assert response.status_code == 401
