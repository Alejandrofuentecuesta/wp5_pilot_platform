"""Panel return URL: r=1 complete, r=2 non-complete, r=3 chose to leave.

`duration_expired_on_recovery` must map to r=2 — the session ran out of
wall-clock time while the server was down and the participant disconnected,
so completion cannot be claimed.
"""
from __future__ import annotations

import pytest

from platforms.chatroom import build_return_url


BASE = "https://panel.example/return"
TOKEN = "tok-123"


@pytest.mark.parametrize("reason,expected_r", [
    ("duration_expired", "1"),
    ("user_exit", "3"),
    ("abandoned", "2"),
    ("no_first_message", "2"),
    ("idle_timeout", "2"),
    ("duration_expired_on_recovery", "2"),
    ("", "2"),
])
def test_r_codes(reason, expected_r):
    url = build_return_url(BASE, TOKEN, reason)
    assert url == f"{BASE}?token={TOKEN}&r={expected_r}"


def test_no_redirect_url_yields_empty():
    assert build_return_url("", TOKEN, "duration_expired") == ""


def test_no_token_yields_bare_url():
    assert build_return_url(BASE, "", "duration_expired") == BASE
