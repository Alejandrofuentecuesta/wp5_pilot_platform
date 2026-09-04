"""Idle pause: freeze the simulation while the activity reminder is shown.

Reuses the disconnect-pause engine (``_pause_started_monotonic`` +
``paused_seconds``) so the exposure timer stops and is credited back on
resume. Two things must hold: a repeated idle signal must not restart the
away-clock (or the 60-minute abandon never fires), and resuming must persist
the credit (or a restart under-credits the session).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.test_chatroom import _create_session, _patch_externals


def test_pause_for_idle_freezes_and_tags_trigger():
    with _patch_externals():
        session, _ = _create_session()
        session.running = True

        session.pause_for_idle()

        assert session._pause_started_monotonic is not None
        assert session._pause_trigger == "idle"


def test_pause_for_idle_is_noop_when_not_running():
    with _patch_externals():
        session, _ = _create_session()  # running is False

        session.pause_for_idle()

        assert session._pause_started_monotonic is None


def test_repeated_idle_pause_does_not_restart_the_away_clock():
    with _patch_externals():
        session, _ = _create_session()
        session.running = True

        session.pause_for_idle()
        first_stamp = session._pause_started_monotonic
        session.pause_for_idle()  # the client re-sends every reminder window

        assert session._pause_started_monotonic == first_stamp


def test_disconnect_during_idle_pause_keeps_the_idle_trigger():
    with _patch_externals():
        session, _ = _create_session()
        session.running = True

        session.pause_for_idle()
        session.pause_for_disconnect()  # no-op: already paused

        assert session._pause_trigger == "idle"


@pytest.mark.asyncio
async def test_resume_from_idle_persists_the_credit():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        session.pause_for_idle()
        await session.resume_from_idle()

        assert session._pause_started_monotonic is None
        assert session._pause_trigger is None
        assert session.state.paused_seconds >= 0
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()
        credited = mocks["session_repo"].add_paused_seconds.await_args.args[2]
        assert credited == pytest.approx(session.state.paused_seconds, abs=0.01)


@pytest.mark.asyncio
async def test_resume_from_idle_without_a_pause_persists_nothing():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        await session.resume_from_idle()  # never paused

        mocks["session_repo"].add_paused_seconds.assert_not_awaited()
