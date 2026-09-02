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
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from platforms import SimulationSession
from platforms.chatroom import REJOIN_WINDOW_MINUTES
from db import connection as db_conn
from db.repositories import session_repo, message_repo, config_repo
from cache import redis_client

# Ended sessions stay in the registry for this long so a participant who
# reconnects shortly after expiry still reaches the in-process session and
# receives the clean "session_ended" close from the heartbeat.
REAP_GRACE_SECONDS = 600
REAP_INTERVAL_SECONDS = 60


class SessionManager:
    """Singleton manager for concurrent simulation sessions."""

    _instance: Optional["SessionManager"] = None

    def __init__(self) -> None:
        self._sessions: Dict[str, SimulationSession] = {}
        self._pending: Dict[str, Dict] = {}
        self._ended_at: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "SessionManager":
        if cls._instance is None:
            cls._instance = SessionManager()
        return cls._instance

    # ── Experiment-level pause/resume ─────────────────────────────────────────

    def set_experiment_paused(self, experiment_id: str, paused: bool) -> int:
        """Propagate pause/resume to all active in-memory sessions for an experiment.

        Returns the number of sessions affected.
        """
        count = 0
        for session in self._sessions.values():
            if session.experiment_id == experiment_id:
                session._paused = paused
                count += 1
        return count

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
            participant_stance=info.get("participant_stance"),
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
        participant_stance: Optional[str] = None,
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
                participant_stance_hint=participant_stance,
                _config=config,
            )
            self._sessions[session_id] = session

        # start() is awaited outside the lock (it spawns background tasks).
        # A failure here (e.g. the scenario seed) must not leave a zombie in
        # the registry: it would hold a cap slot forever and block the
        # participant's retry. Deregister and re-raise; the DB row stays
        # 'pending', which the reconnect path can recover.
        try:
            await session.start()
        except Exception as exc:
            await self._discard_failed_session(session_id, session)
            raise RuntimeError(f"Session start failed for {session_id}: {exc}") from exc

        # Cache metadata in Redis for other workers.
        r = redis_client.get_redis()
        await redis_client.cache_session(r, session_id, {
            "treatment_group": treatment_group,
            "user_name": user_name,
            "participant_stance": participant_stance or "",
            "experiment_id": experiment_id,
            "status": "active",
        })

        return session

    async def _discard_failed_session(
        self, session_id: str, session: SimulationSession
    ) -> None:
        """Best-effort teardown of a session whose start/resume failed."""
        session.running = False
        if session.clock_task:
            session.clock_task.cancel()
        async with self._lock:
            if self._sessions.get(session_id) is session:
                del self._sessions[session_id]
        try:
            r = redis_client.get_redis()
            await redis_client.invalidate_session(r, session_id)
        except Exception:
            pass

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
        if not row or row["status"] not in ("active", "pending"):
            return None

        # A 'pending' row means the token was consumed at /session/start but
        # the worker restarted before the WebSocket arrived. Without recovery
        # the participant is locked out forever on a burned token, so rebuild
        # the session as if the WebSocket had reached the original worker —
        # unless the row is stale, in which case the participant never showed
        # up and the session is closed out as a non-complete instead.
        if row["status"] == "pending":
            created_at = row.get("created_at")
            age_minutes = (
                (datetime.now(timezone.utc) - created_at).total_seconds() / 60
                if created_at else None
            )
            if age_minutes is not None and age_minutes >= REJOIN_WINDOW_MINUTES:
                await session_repo.end_session(
                    pool,
                    session_id=session_id,
                    reason="no_first_message",
                    ended_at=datetime.now(timezone.utc),
                )
                print(f"Stale pending session {session_id} closed instead of revived")
                return None
            meta = {
                "treatment_group": row["treatment_group"],
                "user_name": row["user_name"],
                "participant_stance": row.get("participant_stance"),
                "experiment_id": row["experiment_id"],
                "status": "pending",
                "started_at": None,
            }
            return await self._reconstruct_session(
                session_id, websocket_send, meta, fresh=True,
            )

        # Check if the session already expired during downtime. Persisted
        # pause credit (disconnected time) is subtracted first, so a
        # participant who was away during a restart is not billed for it.
        started_at = row.get("started_at")
        paused_seconds = float(row.get("paused_seconds") or 0.0)
        if started_at:
            sim_cfg = row.get("simulation_config")
            if isinstance(sim_cfg, str):
                sim_cfg = _json.loads(sim_cfg)
            duration = (sim_cfg or {}).get("session_duration_minutes", 15)
            elapsed = (
                (datetime.now(timezone.utc) - started_at).total_seconds()
                - paused_seconds
            ) / 60
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
            "participant_stance": row.get("participant_stance"),
            "experiment_id": row["experiment_id"],
            "status": row["status"],
            "started_at": started_at,
            "paused_seconds": paused_seconds,
        }
        return await self._reconstruct_session(session_id, websocket_send, meta)

    async def _reconstruct_session(
        self,
        session_id: str,
        websocket_send: Callable,
        meta: Dict,
        *,
        fresh: bool = False,
    ) -> SimulationSession:
        """Rebuild a SimulationSession from persisted state and resume it.

        ``fresh=True`` rebuilds a pending session that never went live: it is
        started like a brand-new session (scenario seeded, timer waiting for
        the first message) instead of resumed.
        """
        experiment_id = meta.get("experiment_id", "default")
        treatment_group = meta["treatment_group"]
        user_name = meta.get("user_name", "participant")
        participant_stance = meta.get("participant_stance")

        pool = db_conn.get_pool()

        # Load experiment config from DB.
        config = await config_repo.get_experiment_config(pool, experiment_id)
        if not config:
            raise RuntimeError(f"No config found for experiment '{experiment_id}' during reconstruction")

        # Load persisted messages and agent blocks so in-memory state is
        # consistent (both empty for a fresh pending rebuild).
        msg_rows = [] if fresh else await message_repo.get_session_messages(pool, session_id)
        block_rows = {} if fresh else await session_repo.get_agent_blocks(pool, session_id)

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
                participant_stance_hint=participant_stance,
                _preloaded_messages=msg_rows,
                _preloaded_blocks=block_rows,
                _config=config,
                _started_at=meta.get("started_at"),
                _paused_seconds=float(meta.get("paused_seconds") or 0.0),
            )
            self._sessions[session_id] = session

        # Same zombie guard as create_session: a failed start/resume must
        # not leave a registered, running-but-clockless session behind.
        try:
            if fresh:
                # Never went live: seed the scenario and start from scratch.
                await session.start()
            else:
                # Resume the clock loop (but don't re-seed the scenario).
                await session.resume()
        except Exception as exc:
            await self._discard_failed_session(session_id, session)
            raise RuntimeError(
                f"Session reconstruction failed for {session_id}: {exc}"
            ) from exc

        r = redis_client.get_redis()
        await redis_client.cache_session(r, session_id, {
            "treatment_group": treatment_group,
            "user_name": user_name,
            "participant_stance": participant_stance or "",
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

    # ── Ended-session eviction ────────────────────────────────────────────────

    async def reap_ended_sessions(self) -> int:
        """Evict stopped sessions from the in-process registry.

        Sessions end via ``SimulationSession.stop()`` (duration expiry, user
        exit, admin stop), which persists their end state but leaves the
        object in ``_sessions``. Without eviction, memory grows with
        cumulative rather than concurrent sessions. Eviction happens
        REAP_GRACE_SECONDS after a session is first observed stopped; the DB
        row (already ``status='ended'``) remains the authoritative record.

        Returns the number of sessions evicted.
        """
        now = time.monotonic()
        evicted = []
        async with self._lock:
            for session_id, session in list(self._sessions.items()):
                if session.running:
                    self._ended_at.pop(session_id, None)
                    continue
                first_seen = self._ended_at.setdefault(session_id, now)
                if now - first_seen >= REAP_GRACE_SECONDS:
                    del self._sessions[session_id]
                    del self._ended_at[session_id]
                    evicted.append(session_id)

        for session_id in evicted:
            try:
                r = redis_client.get_redis()
                await redis_client.invalidate_session(r, session_id)
            except Exception as exc:
                print(f"[SessionManager] Redis invalidation failed for {session_id}: {exc}")

        return len(evicted)

    async def reap_loop(self) -> None:
        """Periodically evict ended sessions. Started once at app startup."""
        while True:
            await asyncio.sleep(REAP_INTERVAL_SECONDS)
            try:
                evicted = await self.reap_ended_sessions()
                if evicted:
                    print(f"[SessionManager] Evicted {evicted} ended session(s) from registry")
            except Exception as exc:
                print(f"[SessionManager] Reaper error: {exc}")

    async def list_sessions(self) -> Dict[str, SimulationSession]:
        async with self._lock:
            return dict(self._sessions)


session_manager = SessionManager.get()
