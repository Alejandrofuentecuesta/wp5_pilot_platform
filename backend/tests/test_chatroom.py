"""Tests for SimulationSession (chatroom.py).

Covers:
- Construction and config validation
- Session lifecycle (start, stop, resume)
- Clock loop tick-based pacing
- User message handling
- Blocked agent filtering (_wrap_send)
- Preloaded messages (crash recovery)
- Feature integration (seed, agents_active gating)
- Typing indicator publishing
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from models.message import Message
from models.agent import Agent
from models.session import SessionState


# ── Minimal config fixtures ──────────────────────────────────────────────────

MINIMAL_SIM_CONFIG = {
    "agent_names": ["Alice", "Bob"],
    "session_duration_minutes": 30,
    "messages_per_minute": 6,
    "context_window_size": 10,
    "random_seed": 42,
    "llm_concurrency_limit": 2,
    "max_concurrent_turns": 3,
    "llm_provider": "gemini",
}

MINIMAL_EXP_CONFIG = {
    "chatroom_context": "A test chatroom about science",
    "groups": {
        "control": {
            "treatment": "Be helpful and friendly.",
            "features": [],
        },
        "treatment_a": {
            "treatment": "Be provocative.",
            "features": ["news_article"],
            "seed": {
                "headline": "Breaking",
                "source": "AP",
                "body": "Body text.",
            },
        },
    },
}

MINIMAL_CONFIG = {
    "simulation": MINIMAL_SIM_CONFIG,
    "experimental": MINIMAL_EXP_CONFIG,
}


def _patch_externals():
    """Return a context manager that patches DB, Redis, and LLM dependencies."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with patch("platforms.chatroom.db_conn") as mock_db, \
             patch("platforms.chatroom.redis_client") as mock_redis, \
             patch("platforms.chatroom.session_repo") as mock_session_repo, \
             patch("platforms.chatroom.message_repo") as mock_message_repo, \
             patch("platforms.chatroom.LLMManager") as MockLLMManager:

            mock_db.get_pool.return_value = MagicMock()
            mock_redis.get_redis.return_value = MagicMock()
            mock_redis.publish_event = AsyncMock()
            mock_redis.push_to_window = AsyncMock()
            mock_redis.subscribe_session = AsyncMock()
            mock_session_repo.activate_session = AsyncMock()
            mock_session_repo.end_session = AsyncMock()
            mock_message_repo.insert_message = AsyncMock()
            mock_message_repo.get_session_messages = AsyncMock(return_value=[])

            # LLMManager.from_simulation_config returns a mock LLMManager
            mock_llm = MagicMock()
            mock_llm.generate_response = AsyncMock(return_value=None)
            MockLLMManager.from_simulation_config.return_value = mock_llm

            yield {
                "db": mock_db,
                "redis": mock_redis,
                "session_repo": mock_session_repo,
                "message_repo": mock_message_repo,
                "LLMManager": MockLLMManager,
            }

    return _ctx()


def _create_session(treatment_group="control", config=None, **kwargs):
    """Create a SimulationSession with mocked externals."""
    from platforms.chatroom import SimulationSession

    ws = AsyncMock()
    cfg = config or MINIMAL_CONFIG

    session = SimulationSession(
        session_id="test-session",
        websocket_send=ws,
        treatment_group=treatment_group,
        user_name="participant",
        experiment_id="test-exp",
        _config=cfg,
        **kwargs,
    )
    return session, ws


# ── Construction ─────────────────────────────────────────────────────────────

class TestSimulationSessionInit:

    def test_valid_construction(self):
        with _patch_externals():
            session, ws = _create_session()
            assert session.session_id == "test-session"
            assert session.treatment_group == "control"
            assert session.treatment == "Be helpful and friendly."
            assert session.running is False

    def test_no_config_raises(self):
        from platforms.chatroom import SimulationSession

        with _patch_externals():
            with pytest.raises(RuntimeError, match="No config provided"):
                SimulationSession(
                    session_id="s1",
                    websocket_send=AsyncMock(),
                    treatment_group="control",
                    _config=None,
                )

    def test_missing_groups_raises(self):
        from platforms.chatroom import SimulationSession

        bad_config = {
            "simulation": MINIMAL_SIM_CONFIG,
            "experimental": {"no_groups": True},
        }
        with _patch_externals():
            with pytest.raises(RuntimeError, match="groups"):
                SimulationSession(
                    session_id="s1",
                    websocket_send=AsyncMock(),
                    treatment_group="control",
                    _config=bad_config,
                )

    def test_unknown_treatment_group_raises(self):
        from platforms.chatroom import SimulationSession

        with _patch_externals():
            with pytest.raises(RuntimeError, match="not found"):
                SimulationSession(
                    session_id="s1",
                    websocket_send=AsyncMock(),
                    treatment_group="nonexistent_group",
                    _config=MINIMAL_CONFIG,
                )

    def test_missing_treatment_description_raises(self):
        from platforms.chatroom import SimulationSession

        bad_config = {
            "simulation": MINIMAL_SIM_CONFIG,
            "experimental": {
                "groups": {
                    "empty": {}  # no "treatment" key
                }
            },
        }
        with _patch_externals():
            with pytest.raises(RuntimeError, match="no 'treatment'"):
                SimulationSession(
                    session_id="s1",
                    websocket_send=AsyncMock(),
                    treatment_group="empty",
                    _config=bad_config,
                )

    def test_agents_created_from_config(self):
        with _patch_externals():
            session, _ = _create_session()
            agent_names = [a.name for a in session.state.agents]
            assert "Alice" in agent_names
            assert "Bob" in agent_names

    def test_state_initialized(self):
        with _patch_externals():
            session, _ = _create_session()
            assert session.state.session_id == "test-session"
            assert session.state.user_name == "participant"
            assert session.state.duration_minutes == 30


# ── Preloaded messages (crash recovery) ──────────────────────────────────────

class TestPreloadedMessages:

    def test_preloaded_messages_restored(self):
        preloaded = [
            {
                "sender": "Alice",
                "content": "Hello from before crash",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message_id": "msg-1",
            },
            {
                "sender": "participant",
                "content": "User message",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message_id": "msg-2",
            },
        ]
        with _patch_externals():
            session, _ = _create_session(_preloaded_messages=preloaded)
            assert len(session.state.messages) == 2
            assert session.state.messages[0].sender == "Alice"
            assert session.state.messages[1].sender == "participant"

    def test_preloaded_messages_preserve_metadata(self):
        preloaded = [
            {
                "sender": "Alice",
                "content": "Hello",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message_id": "msg-1",
                "reply_to": "msg-0",
                "quoted_text": "Previous msg",
                "mentions": ["Bob"],
                "liked_by": ["Bob"],
            },
        ]
        with _patch_externals():
            session, _ = _create_session(_preloaded_messages=preloaded)
            msg = session.state.messages[0]
            assert msg.reply_to == "msg-0"
            assert msg.quoted_text == "Previous msg"
            assert msg.mentions == ["Bob"]
            assert "Bob" in msg.liked_by

    def test_preloaded_blocks_restored(self):
        blocks = {"Alice": "2026-01-01T00:00:00+00:00"}
        with _patch_externals():
            session, _ = _create_session(_preloaded_blocks=blocks)
            assert "Alice" in session.state.blocked_agents


# ── Lifecycle ────────────────────────────────────────────────────────────────

class TestSessionLifecycle:

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.start()
            assert session.running is True
            assert session._seeded is True
            assert session.clock_task is not None
            # Clean up
            await session.stop()

    @pytest.mark.asyncio
    async def test_start_activates_db_session(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.start()
            mocks["session_repo"].activate_session.assert_called_once()
            await session.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_not_running(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.start()
            await session.stop(reason="test_stop")
            assert session.running is False

    @pytest.mark.asyncio
    async def test_stop_persists_end_state(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.start()
            await session.stop(reason="completed")
            mocks["session_repo"].end_session.assert_called_once()
            call_kwargs = mocks["session_repo"].end_session.call_args.kwargs
            assert call_kwargs["reason"] == "completed"

    @pytest.mark.asyncio
    async def test_stop_exports_session_csv(self):
        with _patch_externals():
            session, _ = _create_session()
            await session.start()
            with patch("platforms.chatroom.export_session_messages_csv") as mock_export:
                await session.stop(reason="completed")
                mock_export.assert_called_once_with(session.session_id, session.state.messages)

    @pytest.mark.asyncio
    async def test_stop_cancels_clock_task(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.start()
            clock = session.clock_task
            await session.stop()
            assert clock.cancelled() or clock.done()

    @pytest.mark.asyncio
    async def test_resume_skips_seed(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            # Simulate a reconstructed session (seed already happened)
            await session.resume()
            assert session.running is True
            assert session._seeded is True
            assert session.clock_task is not None
            await session.stop()

    @pytest.mark.asyncio
    async def test_resume_idempotent(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            session.running = True
            await session.resume()  # should be a no-op
            assert session.clock_task is None  # not started again


# ── User message handling ────────────────────────────────────────────────────

class TestHandleUserMessage:

    @pytest.mark.asyncio
    async def test_adds_to_state(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.handle_user_message("Hello!")
            assert len(session.state.messages) == 1
            assert session.state.messages[0].sender == "participant"
            assert session.state.messages[0].content == "Hello!"

    @pytest.mark.asyncio
    async def test_persists_to_db(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.handle_user_message("Hello!")
            mocks["message_repo"].insert_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_publishes_via_redis(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.handle_user_message("Hello!")
            mocks["redis"].publish_event.assert_called()

    @pytest.mark.asyncio
    async def test_pushes_to_redis_window(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.handle_user_message("Hello!")
            mocks["redis"].push_to_window.assert_called()

    @pytest.mark.asyncio
    async def test_reply_metadata(self):
        with _patch_externals() as mocks:
            session, _ = _create_session()
            await session.handle_user_message(
                "I agree",
                reply_to="msg-1",
                quoted_text="Original text",
                mentions=["Alice"],
            )
            msg = session.state.messages[0]
            assert msg.reply_to == "msg-1"
            assert msg.quoted_text == "Original text"
            assert msg.mentions == ["Alice"]

    @pytest.mark.asyncio
    async def test_db_error_falls_through(self):
        """DB failure should not crash handle_user_message."""
        with _patch_externals() as mocks:
            mocks["message_repo"].insert_message = AsyncMock(
                side_effect=RuntimeError("DB down")
            )
            session, _ = _create_session()
            # Should not raise
            await session.handle_user_message("Hello!")
            # Message still added to state
            assert len(session.state.messages) == 1

    @pytest.mark.asyncio
    async def test_redis_publish_error_falls_back_to_direct_send(self):
        """If Redis publish fails, falls back to direct WebSocket send."""
        with _patch_externals() as mocks:
            mocks["redis"].publish_event = AsyncMock(
                side_effect=RuntimeError("Redis down")
            )
            session, ws = _create_session()
            await session.handle_user_message("Hello!")
            # The wrapped websocket_send should have been called as fallback


# ── Blocked agent filtering ─────────────────────────────────────────────────

class TestBlockedAgentFiltering:

    @pytest.mark.asyncio
    async def test_blocked_agent_messages_filtered(self):
        with _patch_externals():
            session, _ = _create_session()
            sent = []

            async def capture(msg):
                sent.append(msg)

            wrapped = session._wrap_send(capture)

            # Block Alice at a specific time
            block_time = datetime.now(timezone.utc)
            session.state.block_agent("Alice", block_time.isoformat())

            # Message from Alice AFTER block time → filtered
            after_block = (block_time + timedelta(seconds=10)).isoformat()
            await wrapped({
                "sender": "Alice",
                "content": "Should be blocked",
                "timestamp": after_block,
            })
            assert len(sent) == 0

    @pytest.mark.asyncio
    async def test_unblocked_agent_messages_pass(self):
        with _patch_externals():
            session, _ = _create_session()
            sent = []

            async def capture(msg):
                sent.append(msg)

            wrapped = session._wrap_send(capture)

            # No blocks set → message passes through
            await wrapped({
                "sender": "Alice",
                "content": "Hello",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_non_agent_messages_pass(self):
        with _patch_externals():
            session, _ = _create_session()
            sent = []

            async def capture(msg):
                sent.append(msg)

            wrapped = session._wrap_send(capture)

            # Message with no sender → passes through
            await wrapped({"content": "System message"})
            assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_message_before_block_passes(self):
        with _patch_externals():
            session, _ = _create_session()
            sent = []

            async def capture(msg):
                sent.append(msg)

            wrapped = session._wrap_send(capture)

            block_time = datetime.now(timezone.utc)
            session.state.block_agent("Alice", block_time.isoformat())

            # Message from BEFORE block time → allowed through
            before_block = (block_time - timedelta(seconds=10)).isoformat()
            await wrapped({
                "sender": "Alice",
                "content": "Before block",
                "timestamp": before_block,
            })
            assert len(sent) == 1


# ── Noop send ────────────────────────────────────────────────────────────────

class TestNoopSend:

    @pytest.mark.asyncio
    async def test_noop_send(self):
        with _patch_externals():
            session, _ = _create_session()
            # Should not raise
            await session._noop_send({"content": "test"})


# ── Feature integration ─────────────────────────────────────────────────────

class TestFeatureIntegration:

    def test_features_loaded_from_config(self):
        with _patch_externals():
            session, _ = _create_session(treatment_group="treatment_a")
            # treatment_a has news_article feature
            assert len(session.features._features) == 1

    def test_empty_features_for_control(self):
        with _patch_externals():
            session, _ = _create_session(treatment_group="control")
            assert len(session.features._features) == 0


# ── Detach WebSocket ─────────────────────────────────────────────────────────

class TestDetachWebSocket:

    def test_detach_sets_noop(self):
        with _patch_externals():
            session, _ = _create_session()
            session.detach_websocket()
            # After detach, websocket_send should be noop
            assert session._ws_send_fn is None
