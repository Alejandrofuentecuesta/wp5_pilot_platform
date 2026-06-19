"""Redis client — module-level singleton + helpers for session caching and pub/sub.

Pub/sub pattern
---------------
Agent messages are published to `session:{session_id}:chan`.
Each WebSocket connection subscribes to that channel via `subscribe_session()`.
This decouples message generation (which may run on any worker) from WebSocket
delivery, enabling multi-worker deployments without sticky sessions.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, Optional

import redis.asyncio as aioredis

_redis: Optional[aioredis.Redis] = None


async def init_redis(url: str) -> aioredis.Redis:
    global _redis
    _redis = aioredis.from_url(url, decode_responses=True, socket_timeout=None, socket_keepalive=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised — call init_redis() at startup")
    return _redis


# ── Session metadata cache ────────────────────────────────────────────────────

SESSION_TTL = 7200  # 2 h — generous upper bound for session duration


async def cache_session(
    r: aioredis.Redis,
    session_id: str,
    metadata: Dict[str, str],
    ttl: int = SESSION_TTL,
) -> None:
    """Store session metadata as a Redis hash with an expiry."""
    key = f"session:{session_id}"
    await r.hset(key, mapping=metadata)
    await r.expire(key, ttl)


async def get_cached_session(
    r: aioredis.Redis, session_id: str
) -> Optional[Dict[str, str]]:
    """Return session metadata dict from Redis, or None if not found."""
    key = f"session:{session_id}"
    data = await r.hgetall(key)
    return data if data else None


async def invalidate_session(r: aioredis.Redis, session_id: str) -> None:
    """Remove all Redis keys belonging to a session."""
    await r.delete(
        f"session:{session_id}",
        f"session:{session_id}:window",
    )


# ── Recent-message window (LLM context) ──────────────────────────────────────

WINDOW_TTL = SESSION_TTL


async def push_to_window(
    r: aioredis.Redis,
    session_id: str,
    message_dict: Dict[str, Any],
    window: int = 10,
) -> None:
    """Append a message to the rolling context window for LLM prompts."""
    key = f"session:{session_id}:window"
    await r.rpush(key, json.dumps(message_dict))
    await r.ltrim(key, -window, -1)
    await r.expire(key, WINDOW_TTL)


async def get_window(
    r: aioredis.Redis, session_id: str
) -> list[Dict[str, Any]]:
    """Return the recent-message window as a list of dicts."""
    key = f"session:{session_id}:window"
    items = await r.lrange(key, 0, -1)
    return [json.loads(item) for item in items]


# ── Pub/Sub for WebSocket delivery ───────────────────────────────────────────

def _chan(session_id: str) -> str:
    return f"session:{session_id}:chan"


async def publish_event(
    r: aioredis.Redis, session_id: str, event: Dict[str, Any]
) -> None:
    """Publish a serialised event dict to the session channel."""
    await r.publish(_chan(session_id), json.dumps(event))


async def subscribe_session(
    r: aioredis.Redis, session_id: str
) -> AsyncIterator[Dict[str, Any]]:
    """Async-generator that yields decoded dicts from the session channel.

    Usage::

        async for event in subscribe_session(r, session_id):
            await ws_send(event)

    The generator exits when the caller's task is cancelled.
    """
    # Each subscriber needs its own dedicated connection.
    pubsub = r.pubsub()
    await pubsub.subscribe(_chan(session_id))
    try:
        async for raw in pubsub.listen():
            if raw["type"] == "message":
                try:
                    yield json.loads(raw["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
    finally:
        await pubsub.unsubscribe(_chan(session_id))
        await pubsub.aclose()
