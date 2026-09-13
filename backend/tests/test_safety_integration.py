"""Safety screening wired into the session: gate placement, hold, recovery.

The gate must be the only route by which agent text reaches the participant,
so these tests check the AgentManager call order (screen before state,
persist and broadcast) and the researcher hold (frozen clock, rejoin does
not lift it, resume credits time, end returns r=2).
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.agent_manager import AgentManager
from agents.STAGE.orchestrator import TurnResult
from models.message import Message
from platforms.safety_screen import ScreenOutcome
from tests.test_agent_manager import _make_state
from tests.test_chatroom import MINIMAL_CONFIG, _create_session, _patch_externals
from utils.safety import SafetyVerdict


def _manager_with_screen(publish: bool):
    state = _make_state()
    screen = MagicMock()
    screen.screen_agent = AsyncMock(
        return_value=ScreenOutcome(publish=publish, verdict=SafetyVerdict(status="safe"), user_turn="")
    )
    screen.after_publish = AsyncMock()
    logger = MagicMock()
    am = AgentManager(
        state=state, orchestrator=MagicMock(), logger=logger,
        session_id="s", experiment_id="e", safety_screen=screen,
    )
    return am, state, screen


class TestAgentManagerGate:
    async def test_withheld_turn_never_reaches_state_db_or_redis(self):
        am, state, screen = _manager_with_screen(publish=False)
        msg = Message.create(sender="Alice", content="withheld")
        with patch("agents.agent_manager.db_conn"), \
             patch("agents.agent_manager.message_repo") as repo, \
             patch("agents.agent_manager.redis_client") as redis:
            repo.insert_message = AsyncMock()
            redis.publish_event = AsyncMock()
            redis.push_to_window = AsyncMock()
            await am._handle_message(TurnResult(action_type="message", agent_name="Alice", message=msg))
            assert msg not in state.messages
            repo.insert_message.assert_not_awaited()
            redis.publish_event.assert_not_awaited()
            redis.push_to_window.assert_not_awaited()
            screen.after_publish.assert_not_awaited()
            am.logger.log_message.assert_not_called()

    async def test_published_turn_records_verdict_after_persist(self):
        am, state, screen = _manager_with_screen(publish=True)
        msg = Message.create(sender="Alice", content="ok")
        order = []
        with patch("agents.agent_manager.db_conn"), \
             patch("agents.agent_manager.message_repo") as repo, \
             patch("agents.agent_manager.redis_client") as redis:
            repo.insert_message = AsyncMock(side_effect=lambda *a, **k: order.append("persist"))
            screen.after_publish = AsyncMock(side_effect=lambda *a, **k: order.append("after_publish"))
            redis.publish_event = AsyncMock(side_effect=lambda *a, **k: order.append("publish"))
            redis.push_to_window = AsyncMock()
            await am._handle_message(TurnResult(action_type="message", agent_name="Alice", message=msg))
        assert msg in state.messages
        assert order == ["persist", "after_publish", "publish"]

    async def test_in_flight_turn_is_dropped_while_held(self):
        am, state, screen = _manager_with_screen(publish=True)
        am.hold_active = lambda: True
        msg = Message.create(sender="Alice", content="late")
        with patch("agents.agent_manager.db_conn"), \
             patch("agents.agent_manager.message_repo") as repo, \
             patch("agents.agent_manager.redis_client") as redis:
            repo.insert_message = AsyncMock()
            redis.publish_event = AsyncMock()
            await am._handle_message(TurnResult(action_type="message", agent_name="Alice", message=msg))
        assert msg not in state.messages
        repo.insert_message.assert_not_awaited()
        redis.publish_event.assert_not_awaited()
        screen.screen_agent.assert_not_awaited()
        am.logger.log_event.assert_called_with("turn_dropped_during_hold", {"sender": "Alice"})

    async def test_no_screen_keeps_legacy_behaviour(self):
        state = _make_state()
        am = AgentManager(state=state, orchestrator=MagicMock(), logger=MagicMock(), session_id="s")
        msg = Message.create(sender="Alice", content="ok")
        with patch("agents.agent_manager.db_conn"), \
             patch("agents.agent_manager.message_repo") as repo, \
             patch("agents.agent_manager.redis_client") as redis:
            repo.insert_message = AsyncMock()
            redis.publish_event = AsyncMock()
            redis.push_to_window = AsyncMock()
            await am._handle_message(TurnResult(action_type="message", agent_name="Alice", message=msg))
        assert msg in state.messages


def _safety_config(enabled=True, **extra):
    cfg = copy.deepcopy(MINIMAL_CONFIG)
    cfg["experimental"]["safety"] = {
        "enabled": enabled, "transport": "ollama_raw",
        "base_url": "https://sal.example", "model": "llama-guard3:8b", **extra,
    }
    return cfg


class TestSessionConstruction:
    def test_screen_disabled_by_default(self):
        with _patch_externals():
            session, _ = _create_session()
            assert session.safety_screen.enabled is False
            assert session.agent_manager.safety_screen is session.safety_screen

    def test_screen_enabled_from_config(self):
        with _patch_externals():
            session, _ = _create_session(config=_safety_config())
            assert session.safety_screen.enabled is True
            assert session.safety_screen.client.transport == "ollama_raw"
            assert session.safety_screen.client.model == "llama-guard3:8b"

    def test_enabled_without_endpoint_fails_at_construction(self, monkeypatch):
        monkeypatch.delenv("SAFETY_BASE_URL", raising=False)
        monkeypatch.delenv("SAFETY_MODEL", raising=False)
        with _patch_externals():
            with pytest.raises(ValueError):
                _create_session(config=_safety_config(base_url="", model=""))

    async def test_participant_message_is_screened(self):
        with _patch_externals():
            session, _ = _create_session(config=_safety_config())
            session.running = True
            session.safety_screen.screen_participant = AsyncMock()
            await session.handle_user_message("hola")
            session.safety_screen.screen_participant.assert_awaited_once()
            assert session.safety_screen.screen_participant.call_args[0][0].content == "hola"


class TestSafetyHold:
    async def test_pause_freezes_and_persists_and_notifies(self):
        with _patch_externals() as mocks, patch("platforms.chatroom.safety_repo") as sr:
            sr.set_safety_paused = AsyncMock()
            session, _ = _create_session()
            session.running = True
            assert await session.pause_for_safety("Laia") is True
            assert session.safety_held is True
            sr.set_safety_paused.assert_awaited_once()
            assert sr.set_safety_paused.call_args[0][2] is not None
            event = mocks["redis"].publish_event.call_args[0][2]
            assert event["event_type"] == "session_paused"
            assert event["trigger"] == "hold"
            assert "pausa" in event["notice"]
            # Second pause is a no-op.
            assert await session.pause_for_safety("Laia") is False

    async def test_pause_not_running_is_noop(self):
        with _patch_externals(), patch("platforms.chatroom.safety_repo") as sr:
            sr.set_safety_paused = AsyncMock()
            session, _ = _create_session()
            assert await session.pause_for_safety("Laia") is False
            assert session.safety_held is False

    async def test_rejoin_does_not_lift_hold(self):
        with _patch_externals(), patch("platforms.chatroom.safety_repo") as sr:
            sr.set_safety_paused = AsyncMock()
            session, _ = _create_session()
            session.running = True
            await session.pause_for_safety("Laia")
            session.pause_for_disconnect()
            ws = AsyncMock()
            await session.attach_websocket(ws)
            assert session.safety_held is True
            cfg = [c[0][0] for c in ws.call_args_list if c[0][0].get("event_type") == "session_config"][0]
            assert cfg["held"] is True and cfg["hold_notice"]

    async def test_resume_credits_time_and_clears(self):
        with _patch_externals() as mocks, patch("platforms.chatroom.safety_repo") as sr:
            sr.set_safety_paused = AsyncMock()
            mocks["session_repo"].add_paused_seconds = AsyncMock()
            session, _ = _create_session()
            session.running = True
            await session.pause_for_safety("Laia")
            session._safety_hold_started_monotonic -= 30
            credited = await session.resume_from_safety("Laia")
            assert credited >= 30
            assert session.safety_held is False
            assert session.state.paused_seconds >= 30
            mocks["session_repo"].add_paused_seconds.assert_awaited_once()
            assert sr.set_safety_paused.call_args[0][2] is None
            event = mocks["redis"].publish_event.call_args[0][2]
            assert event["event_type"] == "session_resumed" and event["trigger"] == "hold"

    async def test_end_stops_with_safety_stop_and_r2(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            session.running = True
            session.stop = AsyncMock()
            session._build_return_url = AsyncMock(return_value="https://panel?token=t&r=2")
            with patch("platforms.chatroom.asyncio.sleep", new=AsyncMock()):
                await session.end_for_safety("Laia")
            end_event = [
                c[0][2] for c in mocks["redis"].publish_event.call_args_list
                if c[0][2].get("event_type") == "session_end"
            ][0]
            # The browser sees a neutral reason; the return code still derives from safety_stop.
            assert end_event["reason"] == "closed_by_researcher"
            session._build_return_url.assert_awaited_with("safety_stop")
            session.stop.assert_awaited_once_with(reason="safety_stop")

    def test_restored_hold_from_db(self):
        with _patch_externals():
            session, _ = _create_session(_safety_paused_at=datetime.now(timezone.utc))
            assert session.safety_held is True

    async def test_clock_loop_does_nothing_while_held(self):
        with _patch_externals(), patch("platforms.chatroom.safety_repo") as sr:
            sr.set_safety_paused = AsyncMock()
            session, _ = _create_session()
            session.running = True
            session._first_user_message_received = True
            await session.pause_for_safety("Laia")
            session._guarded_turn = AsyncMock()
            ticks = {"n": 0}

            async def fake_sleep(_):
                ticks["n"] += 1
                if ticks["n"] >= 3:
                    session.running = False

            with patch("platforms.chatroom.asyncio.sleep", new=fake_sleep):
                await session._clock_loop()
            session._guarded_turn.assert_not_awaited()


class TestReturnCode:
    def test_safety_stop_is_r2(self):
        from platforms.chatroom import build_return_url
        assert build_return_url("https://p", "tok", "safety_stop").endswith("r=2")
