"""Idle pause: freeze the simulation while the activity reminder is shown.

Reuses the disconnect-pause engine (``_pause_started_monotonic`` +
``paused_seconds``) so the exposure timer stops and is credited back on
resume. What must hold:

- a repeated idle signal must not restart the away-clock (or the 60-minute
  idle time-out never fires);
- only the participant lifts an idle pause (the reminder's button or
  posting a message), never a websocket reconnect, which browsers do on
  their own for hidden or sleeping tabs;
- a reconnect still lifts a disconnect pause;
- resuming must persist the credit (or a restart under-credits the session).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from platforms.chatroom import REJOIN_WINDOW_MINUTES
from tests.test_chatroom import _create_session, _patch_externals


def _session_config(ws):
    return [
        c.args[0] for c in ws.call_args_list
        if c.args[0].get("event_type") == "session_config"
    ][-1]


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
        session.pause_for_idle()  # the client re-sends after every reconnect

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


@pytest.mark.asyncio
async def test_resume_from_idle_does_not_lift_a_disconnect_pause():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        session.pause_for_disconnect()
        await session.resume_from_idle()

        assert session._pause_trigger == "disconnect"
        mocks["session_repo"].add_paused_seconds.assert_not_awaited()


# ── Reconnects ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconnect_does_not_lift_an_idle_pause():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        session.pause_for_idle()
        stamp = session._pause_started_monotonic
        ws = AsyncMock()
        await session.attach_websocket(ws)

        assert session._pause_trigger == "idle"
        assert session._pause_started_monotonic == stamp
        mocks["session_repo"].add_paused_seconds.assert_not_awaited()
        # The client is told, so a reloaded page shows the reminder again.
        assert _session_config(ws)["idle_paused"] is True


@pytest.mark.asyncio
async def test_reconnect_lifts_a_disconnect_pause():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        session.pause_for_disconnect()
        ws = AsyncMock()
        await session.attach_websocket(ws)

        assert session._pause_started_monotonic is None
        assert session._pause_trigger is None
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()
        assert _session_config(ws)["idle_paused"] is False


@pytest.mark.asyncio
async def test_idle_pause_survives_repeated_drops_and_resumes_once():
    """The reported session: idle, then the socket drops and reconnects twice."""
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        session.pause_for_idle()
        stamp = session._pause_started_monotonic
        for _ in range(2):
            session.pause_for_disconnect()  # no-op: already paused
            await session.attach_websocket(AsyncMock())
            session.pause_for_idle()  # the client re-sends on reconnect

        assert session._pause_trigger == "idle"
        assert session._pause_started_monotonic == stamp
        mocks["session_repo"].add_paused_seconds.assert_not_awaited()

        await session.resume_from_idle()

        assert session._pause_started_monotonic is None
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()


@pytest.mark.asyncio
async def test_idle_pause_through_a_reconnect_ends_as_idle_timeout():
    with _patch_externals():
        session, _ = _create_session()
        session.running = True
        session._first_user_message_received = True

        session.pause_for_idle()
        await session.attach_websocket(AsyncMock())
        # The rejoin window has elapsed since the idle pause began.
        session._pause_started_monotonic -= REJOIN_WINDOW_MINUTES * 60 + 1
        session._publish_session_end = AsyncMock()
        session.stop = AsyncMock()
        session._guarded_turn = AsyncMock()

        with patch("platforms.chatroom.asyncio.sleep", new=AsyncMock()):
            await session._clock_loop()

        session.stop.assert_awaited_once_with(reason="idle_timeout")
        session._publish_session_end.assert_awaited_once_with("idle_timeout")
        session._guarded_turn.assert_not_awaited()


# ── Posting a message ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_posting_a_message_lifts_an_idle_pause():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True
        session._first_user_message_received = True

        session.pause_for_idle()
        await session.handle_user_message("sigo aquí")
        await asyncio.gather(*session._safety_tasks, *session._participant_screen_tasks)

        assert session._pause_started_monotonic is None
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()
        assert session.state.messages[-1].content == "sigo aquí"
