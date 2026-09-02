"""Admin passphrase gate: constant-time comparison plus a guessing throttle.

After three consecutive wrong passphrases every further attempt is refused
for thirty seconds (HTTP 429), so the passphrase cannot be brute-forced at
request speed. A correct passphrase resets the counter.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

import main


PASSPHRASE = "correct-passphrase"


@pytest.fixture(autouse=True)
def reset_throttle():
    main._admin_failures.update(count=0, last_at=0.0)
    yield
    main._admin_failures.update(count=0, last_at=0.0)


def _attempt(key):
    with patch.object(main, "ADMIN_PASSPHRASE", PASSPHRASE):
        main._require_admin(key)


def _failed_attempt(key="wrong"):
    with pytest.raises(HTTPException) as exc:
        _attempt(key)
    return exc.value


class TestPassphraseCheck:
    def test_correct_key_passes(self):
        _attempt(PASSPHRASE)  # must not raise

    def test_wrong_key_is_401(self):
        assert _failed_attempt("wrong").status_code == 401

    def test_missing_key_is_401(self):
        assert _failed_attempt(None).status_code == 401

    def test_empty_configured_passphrase_rejects_everything(self):
        with patch.object(main, "ADMIN_PASSPHRASE", ""):
            with pytest.raises(HTTPException) as exc:
                main._require_admin("")
        assert exc.value.status_code == 401


class TestThrottle:
    def test_three_failures_then_429(self):
        for _ in range(3):
            assert _failed_attempt().status_code == 401
        assert _failed_attempt().status_code == 429

    def test_correct_key_during_throttle_is_also_refused(self):
        for _ in range(3):
            _failed_attempt()
        with patch.object(main, "ADMIN_PASSPHRASE", PASSPHRASE):
            with pytest.raises(HTTPException) as exc:
                main._require_admin(PASSPHRASE)
        assert exc.value.status_code == 429

    def test_throttle_expires_after_delay(self):
        for _ in range(3):
            _failed_attempt()
        # Age the last failure past the delay window.
        main._admin_failures["last_at"] -= main._ADMIN_FAILURE_DELAY_SECONDS + 1
        _attempt(PASSPHRASE)  # must not raise

    def test_success_resets_the_counter(self):
        for _ in range(2):
            _failed_attempt()
        _attempt(PASSPHRASE)
        for _ in range(2):
            _failed_attempt()
        # Only two consecutive failures since the success — not throttled.
        _attempt(PASSPHRASE)
