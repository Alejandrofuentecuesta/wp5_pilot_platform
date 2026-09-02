"""The session report and transcript CSV are admin-only.

Both endpoints expose the treatment group and (for the report) every LLM
prompt, so an unauthenticated fetch would let a participant unblind
themselves with nothing but their own session id from DevTools.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    # No lifespan: these requests must be rejected before any DB access.
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize("path", [
    "/session/some-session-id/report",
    "/session/some-session-id/messages-csv",
])
class TestReportEndpointsRequireAdmin:
    def test_no_key_is_401(self, client, path):
        with patch.object(main, "ADMIN_PASSPHRASE", "correct-passphrase"):
            response = client.get(path)
        assert response.status_code == 401

    def test_wrong_key_is_401(self, client, path):
        with patch.object(main, "ADMIN_PASSPHRASE", "correct-passphrase"):
            response = client.get(path, headers={"X-Admin-Key": "wrong"})
        assert response.status_code == 401

    def test_correct_key_passes_the_gate(self, client, path):
        """With the right key the request reaches the DB layer (503 here,
        because no pool is initialised in tests) instead of being rejected."""
        with patch.object(main, "ADMIN_PASSPHRASE", "correct-passphrase"):
            response = client.get(path, headers={"X-Admin-Key": "correct-passphrase"})
        assert response.status_code == 503
