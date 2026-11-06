"""The silence clock: a session nobody has spoken to for too long ends.

Active seconds since the participant's first message or the last agent
message shown, whichever is later. It does not run before the first
message, while the room is frozen (participant away or idle, reviewer
hold, experiment pause), or while an unsafe agent message awaits a human.
At the threshold the session ends as ``session_failed`` (r=4, nothing was
ever shown; token reopened for a recontact) or ``session_stalled`` (r=2,
agents had spoken). Synthetic runs never use it.

Times are simulated by backdating the monotonic tick stamp.
"""
from __future__ import annotations

import asyncio
import copy
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.repositories import config_repo
from platforms.chatroom import SILENCE_FAILURE_DEFAULT_SECONDS
from tests.test_chatroom import MINIMAL_CONFIG, _create_session, _patch_externals
from tests.test_config_repo import _minimal_sim


def _ready(session, threshold=240):
    """A running session whose participant has posted; nothing shown yet."""
    session.running = True
    session._first_user_message_received = True
    session._silence_failure_seconds = threshold
    session._last_watchdog_tick = time.monotonic()


def _tick(session, seconds):
    """Advance the clock as if ``seconds`` passed since the last tick."""
    session._last_watchdog_tick -= seconds
    return session._tick_silence_clock()


class TestWhenTheClockRuns:
    def test_default_threshold_and_fresh_state(self):
        with _patch_externals():
            session, _ = _create_session()
            assert session._silence_failure_seconds == SILENCE_FAILURE_DEFAULT_SECONDS == 240
            assert session._silence_seconds == 0.0
            assert session._agent_message_shown is False

    def test_not_before_the_first_participant_message(self):
        with _patch_externals():
            session, _ = _create_session()
            session.running = True
            session._last_watchdog_tick = time.monotonic()
            assert _tick(session, 300) is False
            assert session._silence_seconds == 0.0

    def test_runs_after_the_first_message(self):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session)
            _tick(session, 0.5)
            assert session._silence_seconds == pytest.approx(0.5, abs=0.05)

    def test_each_tick_is_capped_at_one_second(self):
        """A stalled event loop must not count a long gap as silence."""
        with _patch_externals():
            session, _ = _create_session()
            _ready(session)
            _tick(session, 30)
            assert session._silence_seconds == pytest.approx(1.0, abs=0.05)

    def test_first_tick_counts_nothing(self):
        with _patch_externals():
            session, _ = _create_session()
            session.running = True
            session._first_user_message_received = True
            assert session._last_watchdog_tick is None
            assert session._tick_silence_clock() is False
            assert session._silence_seconds == 0.0

    @pytest.mark.parametrize("freeze", ["disconnect", "idle", "experiment", "hold"])
    def test_not_while_frozen(self, freeze):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session)
            if freeze == "disconnect":
                session.pause_for_disconnect()
            elif freeze == "idle":
                session.pause_for_idle()
            elif freeze == "experiment":
                session._experiment_paused = True
            else:
                session._safety_hold_started_monotonic = time.monotonic()
            assert session.frozen
            _tick(session, 0.5)
            assert session._silence_seconds == 0.0

    def test_not_while_an_unsafe_message_awaits_review(self):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session)
            session.safety_screen._unsafe_holds.add("flag-1")
            _tick(session, 0.5)
            assert session._silence_seconds == 0.0
            session.safety_screen.resolve_flag("flag-1")
            _tick(session, 0.5)
            assert session._silence_seconds == pytest.approx(0.5, abs=0.05)

    def test_an_unavailable_hold_still_counts(self):
        """A safety-model outage is a failure the participant sees as silence."""
        with _patch_externals():
            session, _ = _create_session()
            _ready(session)
            session.safety_screen._pending_review_agents["Lucia"] = {"flag-u"}
            _tick(session, 0.5)
            assert session._silence_seconds == pytest.approx(0.5, abs=0.05)

    def test_disabled_by_zero(self):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session, threshold=0)
            assert _tick(session, 1) is False
            assert session._silence_seconds == 0.0

    def test_synthetic_runs_never_use_it(self):
        cfg = copy.deepcopy(MINIMAL_CONFIG)
        cfg["simulation"]["synthetic_participant"] = True
        cfg["simulation"]["silence_failure_seconds"] = 240
        with _patch_externals():
            session, _ = _create_session(config=cfg)
            assert session._silence_failure_seconds == 0

    def test_experiment_setting_overrides_the_default(self):
        cfg = copy.deepcopy(MINIMAL_CONFIG)
        cfg["simulation"]["silence_failure_seconds"] = 90
        with _patch_externals():
            session, _ = _create_session(config=cfg)
            assert session._silence_failure_seconds == 90


class TestResetAndThreshold:
    def test_a_shown_agent_message_resets_the_clock(self):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session)
            _tick(session, 1)
            session._note_agent_message_shown()
            assert session._silence_seconds == 0.0
            assert session._agent_message_shown is True

    def test_the_hook_is_wired_to_the_agent_manager(self):
        with _patch_externals():
            session, _ = _create_session()
            assert session.agent_manager.on_message_shown == session._note_agent_message_shown

    def test_reaches_threshold(self):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session, threshold=2)
            assert _tick(session, 1) is False
            assert _tick(session, 1) is True

    def test_reconstructed_session_with_agent_messages_knows_it(self):
        with _patch_externals():
            session, _ = _create_session(
                treatment_group="treatment_a",
                _preloaded_messages=[
                    {"sender": "participant", "content": "hola", "message_id": "m1",
                     "timestamp": "2026-11-06T10:00:00+00:00"},
                    {"sender": "Lucia", "content": "hola!", "message_id": "m2",
                     "timestamp": "2026-11-06T10:00:20+00:00"},
                ],
            )
            assert session._agent_message_shown is True


class TestEnding:
    @pytest.mark.asyncio
    async def test_nothing_shown_ends_as_session_failed(self):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session, threshold=1)
            session._silence_seconds = 1.0
            session._publish_session_end = AsyncMock()
            session.stop = AsyncMock()
            session.logger = MagicMock()

            await session._end_for_silence()

            session._publish_session_end.assert_awaited_once_with("session_failed")
            session.stop.assert_awaited_once_with(reason="session_failed")
            event = session.logger.log_event.call_args.args
            assert event[0] == "silence_failure"
            assert event[1]["reason"] == "session_failed"

    @pytest.mark.asyncio
    async def test_agents_had_spoken_ends_as_session_stalled(self):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session, threshold=1)
            session._note_agent_message_shown()
            session._publish_session_end = AsyncMock()
            session.stop = AsyncMock()
            session.logger = MagicMock()

            await session._end_for_silence()

            session._publish_session_end.assert_awaited_once_with("session_stalled")
            session.stop.assert_awaited_once_with(reason="session_stalled")

    @pytest.mark.asyncio
    async def test_once_only_shared_with_the_duration_ending(self):
        with _patch_externals():
            session, _ = _create_session()
            _ready(session, threshold=1)
            session._publish_session_end = AsyncMock()
            session.stop = AsyncMock()
            session.logger = MagicMock()
            session._duration_end_started = True

            await session._end_for_silence()

            session._publish_session_end.assert_not_awaited()
            session.stop.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_watchdog_ends_the_session_at_the_threshold(self):
        """The watchdog, not the clock loop, must fire: a hung turn blocks the loop."""
        with _patch_externals():
            session, _ = _create_session()
            _ready(session, threshold=1)
            session._publish_session_end = AsyncMock()
            session.logger = MagicMock()
            stopped = asyncio.Event()

            async def fake_stop(reason):
                session.running = False
                stopped.set()
                fake_stop.reason = reason

            session.stop = fake_stop
            # Real half-second ticks against a one-second threshold: the
            # watchdog must end the session within a few seconds.
            task = asyncio.create_task(session._expiration_watchdog())
            await asyncio.wait_for(stopped.wait(), timeout=10)
            await task

            assert fake_stop.reason == "session_failed"
            session._publish_session_end.assert_awaited_once_with("session_failed")


class TestStop:
    @pytest.mark.asyncio
    async def test_session_failed_reopens_the_token_and_pings_the_panel(self):
        with _patch_externals() as mocks, patch("platforms.chatroom.token_repo") as tr:
            mocks["session_repo"].get_session = AsyncMock(return_value={"token": "tok-1"})
            tr.reopen_token = AsyncMock(return_value=True)
            session, _ = _create_session()
            session.running = True
            session.logger = MagicMock()
            session.logger.drain = AsyncMock()
            session._notify_panel_return = AsyncMock()

            await session.stop(reason="session_failed")

            tr.reopen_token.assert_awaited_once()
            assert tr.reopen_token.await_args.args[1:] == ("tok-1", "test-session")
            session._notify_panel_return.assert_awaited_once_with("session_failed")
            mocks["session_repo"].end_session.assert_awaited_once()
            assert mocks["session_repo"].end_session.await_args.kwargs["reason"] == "session_failed"

    @pytest.mark.asyncio
    async def test_session_stalled_pings_but_keeps_the_token(self):
        with _patch_externals() as mocks, patch("platforms.chatroom.token_repo") as tr:
            mocks["session_repo"].get_session = AsyncMock(return_value={"token": "tok-1"})
            tr.reopen_token = AsyncMock(return_value=True)
            session, _ = _create_session()
            session.running = True
            session.logger = MagicMock()
            session.logger.drain = AsyncMock()
            session._notify_panel_return = AsyncMock()

            await session.stop(reason="session_stalled")

            tr.reopen_token.assert_not_awaited()
            session._notify_panel_return.assert_awaited_once_with("session_stalled")

    @pytest.mark.asyncio
    async def test_other_endings_do_not_reopen(self):
        with _patch_externals() as mocks, patch("platforms.chatroom.token_repo") as tr:
            mocks["session_repo"].get_session = AsyncMock(return_value={"token": "tok-1"})
            tr.reopen_token = AsyncMock(return_value=True)
            session, _ = _create_session()
            session.running = True
            session.logger = MagicMock()
            session.logger.drain = AsyncMock()
            session._notify_panel_return = AsyncMock()

            await session.stop(reason="duration_expired")

            tr.reopen_token.assert_not_awaited()
            session._notify_panel_return.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reopen_failure_does_not_break_the_ending(self):
        with _patch_externals() as mocks, patch("platforms.chatroom.token_repo") as tr:
            mocks["session_repo"].get_session = AsyncMock(return_value={"token": "tok-1"})
            tr.reopen_token = AsyncMock(side_effect=RuntimeError("db down"))
            session, _ = _create_session()
            session.running = True
            session.logger = MagicMock()
            session.logger.drain = AsyncMock()
            session._notify_panel_return = AsyncMock()

            await session.stop(reason="session_failed")

            session.logger.log_error.assert_any_call("reopen_token", "db down")
            session._notify_panel_return.assert_awaited_once_with("session_failed")


class TestConfigValidation:
    def test_default_is_240(self):
        out = config_repo.validate_simulation_config(_minimal_sim())
        assert out["silence_failure_seconds"] == 240

    def test_explicit_value_and_zero_kept(self):
        sim = _minimal_sim()
        sim["silence_failure_seconds"] = 0
        assert config_repo.validate_simulation_config(sim)["silence_failure_seconds"] == 0
        sim["silence_failure_seconds"] = "180"
        assert config_repo.validate_simulation_config(sim)["silence_failure_seconds"] == 180

    def test_negative_rejected(self):
        sim = _minimal_sim()
        sim["silence_failure_seconds"] = -1
        with pytest.raises(ValueError, match="silence_failure_seconds"):
            config_repo.validate_simulation_config(sim)
