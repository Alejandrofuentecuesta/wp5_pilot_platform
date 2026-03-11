"""Session manager — tracks live SimulationSession objects.

Three-tier lookup strategy
--------------------------
1. Local in-process dict (fastest — zero network round-trips)
2. Redis hash cache (cross-worker metadata, sub-millisecond)
3. PostgreSQL sessions table (authoritative, crash-recovery source)

Within a single worker the in-process dict is the primary store; the DB and
Redis are updated on every create/end operation so other workers and crash-
recovery restarts have access to up-to-date state.

Crash recovery
--------------
If a worker crashes while sessions are active their DB rows remain in
``status='active'``.  When any worker subsequently receives a WebSocket
connection for that session_id it calls ``reconstruct_session()``, which
loads the session metadata and full message history from the DB, re-creates
the SimulationSession (without calling ``start()`` again for features that
already seeded), and resumes the clock loop.
"""
from __future__ import annotations

import asyncio
import json as _json
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from platforms import SimulationSession
from db import connection as db_conn
from db.repositories import session_repo, message_repo, config_repo
from cache import redis_client


class SessionManager:
    """Singleton manager for concurrent simulation sessions."""

    _instance: Optional["SessionManager"] = None

    def __init__(self) -> None:
        self._sessions: Dict[str, SimulationSession] = {}
        self._pending: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "SessionManager":
        if cls._instance is None:
            cls._instance = SessionManager()
        return cls._instance

    # ── Pending reservation (HTTP → WebSocket handoff) ────────────────────────

    async def reserve_pending(
        self,
        session_id: str,
        info: Dict,
        *,
        experiment_id: str,
    ) -> None:
        """Reserve a pending session slot (called from POST /session/start).

        Writes to both the in-process pending dict and the DB so the record
        survives an unlikely worker restart between HTTP and WebSocket steps.
        """
        async with self._lock:
            self._pending[session_id] = {**info, "experiment_id": experiment_id}

        pool = db_conn.get_pool()
        await session_repo.create_session(
            pool,
            session_id=session_id,
            token=info.get("token", ""),
            experiment_id=experiment_id,
            treatment_group=info["treatment_group"],
            user_name=info.get("user_name", "participant"),
        )

    async def pop_pending(self, session_id: str) -> Dict:
        async with self._lock:
            return self._pending.pop(session_id, {})

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def create_session(
        self,
        session_id: str,
        websocket_send: Callable,
        *,
        treatment_group: str,
        user_name: str = "participant",
        experiment_id: str = "default",
    ) -> SimulationSession:
        """Create, start, and register a new SimulationSession.

        Loads the experiment config from the DB, then creates the session.
        The session row in the DB is transitioned from 'pending' → 'active'
        inside ``SimulationSession.start()``, and a Redis metadata cache entry
        is written for cross-worker lookups.
        """
        pool = db_conn.get_pool()
        config = await config_repo.get_experiment_config(pool, experiment_id)
        if not config:
            raise RuntimeError(f"No config found for experiment '{experiment_id}'")

        async with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            session = SimulationSession(
                session_id=session_id,
                websocket_send=websocket_send,
                treatment_group=treatment_group,
                user_name=user_name,
                experiment_id=experiment_id,
                _config=config,
            )
            self._sessions[session_id] = session

        # start() is awaited outside the lock (it spawns background tasks).
        await session.start()

        # Cache metadata in Redis for other workers.
        r = redis_client.get_redis()
        await redis_client.cache_session(r, session_id, {
            "treatment_group": treatment_group,
            "user_name": user_name,
            "experiment_id": experiment_id,
            "status": "active",
        })

        return session

    async def get_session(self, session_id: str) -> Optional[SimulationSession]:
        """Return a session if it lives in this worker's process.

        Does NOT attempt cross-worker reconstruction — callers that need that
        should use ``get_or_reconstruct()``.
        """
        async with self._lock:
            return self._sessions.get(session_id)

    async def get_or_reconstruct(
        self,
        session_id: str,
        websocket_send: Callable,
    ) -> Optional[SimulationSession]:
        """Return an existing session or reconstruct one from the DB.

        Used on WebSocket (re)connect to handle:
        - Same-worker reconnect: fast path via in-process dict.
        - Cross-worker reconnect: Redis cache says 'active' but not local
          → reconstruct from DB and resume.
        - Crash recovery: DB shows 'active' but Redis has no entry
          → reconstruct from DB.

        If the session expired during downtime it is marked ended in the DB
        and None is returned so the frontend falls through to the login screen.
        """
        # Fast path — already live in this process.
        session = await self.get_session(session_id)
        if session:
            return session

        # Both the Redis and DB paths need the DB row to check expiry and
        # restore the original start time.
        pool = db_conn.get_pool()
        row = await session_repo.get_session(pool, session_id)
        if not row or row["status"] != "active":
            return None

        # Check if the session already expired during downtime.
        started_at = row.get("started_at")
        if started_at:
            sim_cfg = row.get("simulation_config")
            if isinstance(sim_cfg, str):
                sim_cfg = _json.loads(sim_cfg)
            duration = (sim_cfg or {}).get("session_duration_minutes", 15)
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds() / 60
            if elapsed >= duration:
                await session_repo.end_session(
                    pool,
                    session_id=session_id,
                    reason="duration_expired_on_recovery",
                    ended_at=datetime.now(timezone.utc),
                )
                r = redis_client.get_redis()
                await redis_client.invalidate_session(r, session_id)
                print(f"Session {session_id} expired during downtime — marked ended")
                return None

        meta = {
            "treatment_group": row["treatment_group"],
            "user_name": row["user_name"],
            "experiment_id": row["experiment_id"],
            "status": row["status"],
            "started_at": started_at,
        }
        return await self._reconstruct_session(session_id, websocket_send, meta)

    async def _reconstruct_session(
        self,
        session_id: str,
        websocket_send: Callable,
        meta: Dict,
    ) -> SimulationSession:
        """Rebuild a SimulationSession from persisted state and resume it."""
        experiment_id = meta.get("experiment_id", "default")
        treatment_group = meta["treatment_group"]
        user_name = meta.get("user_name", "participant")

        pool = db_conn.get_pool()

        # Load experiment config from DB.
        config = await config_repo.get_experiment_config(pool, experiment_id)
        if not config:
            raise RuntimeError(f"No config found for experiment '{experiment_id}' during reconstruction")

        # Load persisted messages and agent blocks so in-memory state is consistent.
        msg_rows = await message_repo.get_session_messages(pool, session_id)
        block_rows = await session_repo.get_agent_blocks(pool, session_id)

        async with self._lock:
            # Double-check — another coroutine may have reconstructed first.
            if session_id in self._sessions:
                return self._sessions[session_id]

            session = SimulationSession(
                session_id=session_id,
                websocket_send=websocket_send,
                treatment_group=treatment_group,
                user_name=user_name,
                experiment_id=experiment_id,
                _preloaded_messages=msg_rows,
                _preloaded_blocks=block_rows,
                _config=config,
                _started_at=meta.get("started_at"),
            )
            self._sessions[session_id] = session

        # Resume the clock loop (but don't re-seed the scenario).
        await session.resume()

        r = redis_client.get_redis()
        await redis_client.cache_session(r, session_id, {
            "treatment_group": treatment_group,
            "user_name": user_name,
            "experiment_id": experiment_id,
            "status": "active",
        })
        return session

    async def detach_websocket(self, session_id: str) -> None:
        session = await self.get_session(session_id)
        if session:
            session.detach_websocket()

    async def remove_session(self, session_id: str, reason: str = "removed") -> None:
        """Stop and remove a session, persisting its end state."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)

        if session:
            await session.stop(reason=reason)

        # Clean up Redis cache regardless.
        try:
            r = redis_client.get_redis()
            await redis_client.invalidate_session(r, session_id)
        except Exception as exc:
            print(f"[SessionManager] Redis invalidation failed for {session_id}: {exc}")

    async def list_sessions(self) -> Dict[str, SimulationSession]:
        async with self._lock:
            return dict(self._sessions)


session_manager = SessionManager.get()
