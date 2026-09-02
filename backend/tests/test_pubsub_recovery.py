"""A dead pub/sub subscriber must close the WebSocket, not freeze the screen.

If the Redis subscription dies while the socket stays open, the participant
silently stops receiving messages. The attach-time callback closes the
socket so the client's reconnect loop rebuilds the pipeline. Cancellation
is the normal detach path and must NOT trigger the callback.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import platforms.chatroom as chatroom_module
from platforms.chatroom import SimulationSession


def _fake_self(callback):
    return SimpleNamespace(
        session_id="sess-1",
        logger=MagicMock(),
        _on_subscriber_dead=callback,
    )


@pytest.mark.asyncio
async def test_subscriber_crash_triggers_the_close_callback():
    callback = AsyncMock()
    fake = _fake_self(callback)
    broken_redis = MagicMock(
        get_redis=MagicMock(side_effect=ConnectionError("redis gone")),
    )
    with patch.object(chatroom_module, "redis_client", broken_redis):
        await SimulationSession._pubsub_loop(fake, AsyncMock())
    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_exhausted_subscription_triggers_the_close_callback():
    """The subscribe generator ending (connection closed server-side) is
    just as dead as an exception."""
    callback = AsyncMock()
    fake = _fake_self(callback)

    async def _empty_subscription(r, session_id):
        if False:
            yield  # pragma: no cover — makes this an async generator

    quiet_redis = MagicMock(
        get_redis=MagicMock(),
        subscribe_session=_empty_subscription,
    )
    with patch.object(chatroom_module, "redis_client", quiet_redis):
        await SimulationSession._pubsub_loop(fake, AsyncMock())
    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_does_not_trigger_the_callback():
    callback = AsyncMock()
    fake = _fake_self(callback)

    async def _hanging_subscription(r, session_id):
        await asyncio.sleep(3600)
        yield  # pragma: no cover

    hanging_redis = MagicMock(
        get_redis=MagicMock(),
        subscribe_session=_hanging_subscription,
    )
    with patch.object(chatroom_module, "redis_client", hanging_redis):
        task = asyncio.create_task(SimulationSession._pubsub_loop(fake, AsyncMock()))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task  # the loop swallows cancellation and returns
        except asyncio.CancelledError:
            pass
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_callback_registered_is_harmless():
    fake = _fake_self(None)
    broken_redis = MagicMock(
        get_redis=MagicMock(side_effect=ConnectionError("redis gone")),
    )
    with patch.object(chatroom_module, "redis_client", broken_redis):
        await SimulationSession._pubsub_loop(fake, AsyncMock())  # must not raise
