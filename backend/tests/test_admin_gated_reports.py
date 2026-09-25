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


@pytest.fixture(autouse=True)
def reset_admin_throttle():
    main._admin_failures.update(count=0, last_at=0.0)
    yield
    main._admin_failures.update(count=0, last_at=0.0)


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


class TestReportAcceptsQueryStringKey:
    """The report endpoint is opened as its own tab (not fetched via JS) and
    self-refreshes while the session runs, so it also accepts the key via
    ?admin_key= — the messages-csv endpoint is unaffected, header-only."""

    def test_correct_query_key_passes_the_gate(self, client):
        with patch.object(main, "ADMIN_PASSPHRASE", "correct-passphrase"):
            response = client.get(
                "/session/some-session-id/report?admin_key=correct-passphrase"
            )
        assert response.status_code == 503

    def test_wrong_query_key_is_401(self, client):
        with patch.object(main, "ADMIN_PASSPHRASE", "correct-passphrase"):
            response = client.get("/session/some-session-id/report?admin_key=wrong")
        assert response.status_code == 401

    def test_header_takes_precedence_over_query(self, client):
        """If both are somehow present, the header (the more deliberate,
        JS-driven fetch path) wins over a stray query string."""
        with patch.object(main, "ADMIN_PASSPHRASE", "correct-passphrase"):
            response = client.get(
                "/session/some-session-id/report?admin_key=wrong",
                headers={"X-Admin-Key": "correct-passphrase"},
            )
        assert response.status_code == 503


class TestLiveRefreshInjection:
    """The report tab reloads itself while the session is still running so
    an admin can watch it without reopening — stops once it has ended."""

    def test_running_session_gets_refresh_script(self):
        html = main._with_live_refresh("<html><body>hi</body></html>", "active")
        assert "setTimeout" in html
        assert html.index("setTimeout") < html.index("</body>")

    def test_pending_session_gets_refresh_script(self):
        html = main._with_live_refresh("<html><body>hi</body></html>", "pending")
        assert "setTimeout" in html

    def test_ended_session_is_untouched(self):
        original = "<html><body>hi</body></html>"
        assert main._with_live_refresh(original, "ended") == original

    def test_missing_body_tag_still_appends(self):
        html = main._with_live_refresh("<p>no body tag</p>", "active")
        assert "setTimeout" in html

    def test_pauses_while_a_details_block_is_open(self):
        """A prompt/response/event-data block is a <details> element; reading
        one open must not get collapsed out from under the admin."""
        html = main._with_live_refresh("<html><body>hi</body></html>", "active")
        assert 'document.querySelector("details[open]")' in html
