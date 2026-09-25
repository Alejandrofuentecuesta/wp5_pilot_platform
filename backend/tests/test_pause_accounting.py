"""Shared freeze clock: overlapping pause reasons are credited once.

A session can be frozen for several reasons at the same time (participant
disconnected or idle, researcher hold). The session countdown stops once,
so the frozen time must be credited once, when the last reason lifts, never
per reason. Time under a researcher hold also must not count toward the
participant's rejoin window: they cannot see or answer the idle reminder
behind the hold notice.

Times are simulated by backdating the monotonic stamps.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_chatroom import _create_session, _patch_externals


def _backdate(session, *, frozen=0.0, hold=0.0, pause=0.0):
    if frozen:
        session._frozen_since -= frozen
    if hold:
        session._safety_hold_started_monotonic -= hold
        session._operator_frozen_since -= hold
    if pause:
        session._pause_started_monotonic -= pause


@pytest.mark.asyncio
async def test_disconnect_during_hold_is_credited_once():
    with _patch_externals() as mocks, patch("platforms.chatroom.safety_repo") as sr:
        sr.set_safety_paused = AsyncMock()
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        # Hold began 100 s ago; the participant left 50 s ago.
        await session.pause_for_safety("Laia")
        _backdate(session, frozen=100, hold=100)
        session.pause_for_disconnect()
        _backdate(session, pause=50)

        # Lifting the hold credits nothing: the room is still frozen.
        assert await session.resume_from_safety("Laia") == 0.0
        mocks["session_repo"].add_paused_seconds.assert_not_awaited()

        # The rejoin credits the whole frozen span, once.
        await session.attach_websocket(AsyncMock())

        assert session._frozen_since is None
        assert session.state.paused_seconds == pytest.approx(100, abs=1)
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()
        assert mocks["session_repo"].add_paused_seconds.await_args.args[2] == pytest.approx(100, abs=1)


@pytest.mark.asyncio
async def test_hold_during_idle_pause_is_credited_once_and_spares_the_rejoin_window():
    with _patch_externals() as mocks, patch("platforms.chatroom.safety_repo") as sr:
        sr.set_safety_paused = AsyncMock()
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        # Idle for 100 s, of which the last 40 s under a researcher hold.
        session.pause_for_idle()
        _backdate(session, frozen=100, pause=100)
        await session.pause_for_safety("Laia")
        _backdate(session, hold=40)

        assert await session.resume_from_safety("Laia") == 0.0
        # The 40 held seconds do not count toward the idle time-out.
        away = time.monotonic() - session._pause_started_monotonic
        assert away == pytest.approx(60, abs=1)

        await session.resume_from_idle()

        assert session.state.paused_seconds == pytest.approx(100, abs=1)
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()


@pytest.mark.asyncio
async def test_hold_ending_last_credits_the_whole_span():
    with _patch_externals() as mocks, patch("platforms.chatroom.safety_repo") as sr:
        sr.set_safety_paused = AsyncMock()
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        # Disconnected 100 s ago; hold began 60 s ago; rejoined while held.
        session.pause_for_disconnect()
        _backdate(session, frozen=100, pause=100)
        await session.pause_for_safety("Laia")
        _backdate(session, hold=60)
        await session.attach_websocket(AsyncMock())
        mocks["session_repo"].add_paused_seconds.assert_not_awaited()

        credited = await session.resume_from_safety("Laia")

        assert credited == pytest.approx(100, abs=1)
        assert session.state.paused_seconds == pytest.approx(100, abs=1)
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()


def test_restored_hold_starts_the_freeze_clock():
    from datetime import datetime, timezone

    with _patch_externals():
        session, _ = _create_session(_safety_paused_at=datetime.now(timezone.utc))

        assert session.frozen is True
        assert session._frozen_since is not None


@pytest.mark.asyncio
async def test_first_message_restarts_a_running_freeze_clock():
    """Freeze time from before the session timer started must not be credited."""
    with _patch_externals(), patch("platforms.chatroom.safety_repo") as sr:
        sr.set_safety_paused = AsyncMock()
        session, _ = _create_session()
        session.running = True

        await session.pause_for_safety("Laia")
        _backdate(session, frozen=100, hold=100)
        await session.handle_user_message("hola")

        assert session.state.paused_seconds == 0.0
        assert time.monotonic() - session._frozen_since == pytest.approx(0, abs=1)


# ── Experiment pause (dashboard) ─────────────────────────────────────────────


def _hold_events(mocks):
    return [
        c.args[2] for c in mocks["redis"].publish_event.call_args_list
        if c.args[2].get("trigger") == "hold"
    ]


@pytest.mark.asyncio
async def test_experiment_pause_freezes_like_a_hold():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        assert await session.pause_for_experiment() is True
        assert await session.pause_for_experiment() is False  # already paused
        assert session.operator_held and session.frozen
        _backdate(session, frozen=30)

        ws = AsyncMock()
        await session.attach_websocket(ws)
        config = [c.args[0] for c in ws.call_args_list if c.args[0].get("event_type") == "session_config"][-1]
        assert config["held"] is True and config["hold_notice"]

        credited = await session.resume_from_experiment()

        assert credited == pytest.approx(30, abs=1)
        assert not session.frozen
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()
        assert [e["event_type"] for e in _hold_events(mocks)] == ["session_paused", "session_resumed"]


@pytest.mark.asyncio
async def test_clock_loop_runs_nothing_while_the_experiment_is_paused():
    with _patch_externals():
        session, _ = _create_session()
        session.running = True
        session._first_user_message_received = True
        await session.pause_for_experiment()
        session._guarded_turn = AsyncMock()
        session.stop = AsyncMock()
        ticks = {"n": 0}

        async def fake_sleep(_):
            ticks["n"] += 1
            if ticks["n"] >= 3:
                session.running = False

        with patch("platforms.chatroom.asyncio.sleep", new=fake_sleep):
            await session._clock_loop()

        session._guarded_turn.assert_not_awaited()
        session.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_and_experiment_pause_share_one_notice_and_one_credit():
    with _patch_externals() as mocks, patch("platforms.chatroom.safety_repo") as sr:
        sr.set_safety_paused = AsyncMock()
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session, _ = _create_session()
        session.running = True

        await session.pause_for_safety("Laia")
        _backdate(session, frozen=100, hold=100)
        await session.pause_for_experiment()

        # Lifting the hold leaves the room frozen and the notice up.
        assert await session.resume_from_safety("Laia") == 0.0
        assert session.operator_held
        assert [e["event_type"] for e in _hold_events(mocks)] == ["session_paused"]

        credited = await session.resume_from_experiment()

        assert credited == pytest.approx(100, abs=1)
        assert session.state.paused_seconds == pytest.approx(100, abs=1)
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()
        assert [e["event_type"] for e in _hold_events(mocks)] == ["session_paused", "session_resumed"]


@pytest.mark.asyncio
async def test_manager_freezes_and_unfreezes_only_that_experiments_live_sessions():
    from utils.session_manager import SessionManager

    with _patch_externals():
        manager = SessionManager()
        ours, _ = _create_session()
        ours.running = True
        other, _ = _create_session()
        other.running = True
        other.experiment_id = "another"
        manager._sessions = {"a": ours, "b": other}

        assert manager.count_running("test-exp") == 1
        assert await manager.set_experiment_paused("test-exp", True) == 1
        assert ours.operator_held and not other.operator_held

        assert await manager.set_experiment_paused("test-exp", False) == 1
        assert not ours.frozen


@pytest.mark.asyncio
async def test_session_created_while_experiment_paused_starts_frozen():
    from utils.session_manager import SessionManager

    with _patch_externals():
        session, _ = _create_session()
        session.running = True
        with patch("utils.session_manager.config_repo") as cr, \
             patch("utils.session_manager.db_conn"):
            cr.get_experiment = AsyncMock(return_value={"paused": True})
            await SessionManager()._apply_experiment_pause(session)

        assert session.operator_held


@pytest.mark.asyncio
async def test_pause_endpoint_asks_for_confirmation_while_sessions_are_live():
    from fastapi import HTTPException

    import main

    with patch.object(main, "_require_admin", lambda key: None), \
         patch.object(main, "_get_pool", lambda: None), \
         patch.object(main.config_repo, "set_paused", AsyncMock()) as set_paused, \
         patch.object(main.session_manager, "count_running", lambda _id: 2), \
         patch.object(main.session_manager, "set_experiment_paused", AsyncMock(return_value=2)) as freeze:
        with pytest.raises(HTTPException) as exc:
            await main.admin_pause_experiment("exp", x_admin_key="k")
        assert exc.value.status_code == 409
        assert exc.value.detail["reason"] == "sessions_would_freeze"
        assert exc.value.detail["total"] == 2
        set_paused.assert_not_awaited()

        result = await main.admin_pause_experiment("exp", confirm=True, x_admin_key="k")

        assert result["sessions_paused"] == 2
        set_paused.assert_awaited_once_with(None, "exp", True)
        freeze.assert_awaited_once_with("exp", True)
