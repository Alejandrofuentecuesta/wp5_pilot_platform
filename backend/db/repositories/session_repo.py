"""Session repository — CRUD for sessions and agent_blocks tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

import asyncpg


async def create_session(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    token: str,
    experiment_id: str,
    treatment_group: str,
    user_name: str,
    participant_stance: Optional[str] = None,
) -> None:
    """Insert a new session row with status='pending'."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions(session_id, token, experiment_id, treatment_group, user_name, participant_stance, status)
            VALUES($1, $2, $3, $4, $5, $6, 'pending')
            ON CONFLICT(session_id) DO NOTHING
            """,
            session_id,
            token,
            experiment_id,
            treatment_group,
            user_name,
            participant_stance,
        )


async def update_participant_stance(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    participant_stance: Optional[str],
) -> bool:
    """Update the participant self-report on an existing session row."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE sessions
            SET participant_stance = $1
            WHERE session_id = $2
            """,
            participant_stance,
            session_id,
        )
    return result.endswith("1")


async def activate_session(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    started_at: datetime,
    random_seed: int,
    simulation_config: dict,
    experimental_config: dict,
) -> None:
    """Transition session status to 'active' and store config snapshots."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions
            SET    status = 'active',
                   started_at = $1,
                   random_seed = $2,
                   simulation_config = $3,
                   experimental_config = $4
            WHERE  session_id = $5
            """,
            started_at,
            random_seed,
            json.dumps(simulation_config),
            json.dumps(experimental_config),
            session_id,
        )


async def end_session(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    reason: str,
    ended_at: Optional[datetime] = None,
) -> None:
    """Transition session status to 'ended'."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions
            SET    status = 'ended', end_reason = $1, ended_at = $2
            WHERE  session_id = $3
            """,
            reason,
            ended_at or datetime.now(timezone.utc),
            session_id,
        )


async def get_session(pool: asyncpg.Pool, session_id: str) -> Optional[dict]:
    """Fetch a session row as a dict, or None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sessions WHERE session_id = $1", session_id
        )
    return dict(row) if row else None


async def list_active_sessions(
    pool: asyncpg.Pool, experiment_id: str
) -> List[dict]:
    """List all active sessions for an experiment."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM sessions WHERE experiment_id = $1 AND status = 'active'",
            experiment_id,
        )
    return [dict(r) for r in rows]


async def count_live_sessions_by_experiment(pool: asyncpg.Pool) -> List[dict]:
    """Count sessions still owed a conclusion, per experiment.

    'pending' rows are included: the participant has consumed a token and is
    on their way to the websocket. 'active' covers both connected
    participants and those disconnected but still inside their rejoin
    window, who would otherwise come back to a paused experiment.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT experiment_id, count(*) AS live
            FROM sessions
            WHERE status IN ('active', 'pending')
            GROUP BY experiment_id
            ORDER BY experiment_id
            """
        )
    return [dict(r) for r in rows]


# ── Agent blocks ──────────────────────────────────────────────────────────────

async def upsert_agent_block(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    agent_name: str,
    blocked_at: datetime,
    blocked_by: str,
) -> None:
    """Insert or update an agent block record."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agent_blocks(session_id, agent_name, blocked_at, blocked_by)
            VALUES($1, $2, $3, $4)
            ON CONFLICT(session_id, agent_name)
            DO UPDATE SET blocked_at = EXCLUDED.blocked_at, blocked_by = EXCLUDED.blocked_by
            """,
            session_id,
            agent_name,
            blocked_at,
            blocked_by,
        )


async def get_agent_blocks(
    pool: asyncpg.Pool, session_id: str
) -> Dict[str, str]:
    """Return {agent_name: iso_timestamp} for all blocks in the session."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT agent_name, blocked_at FROM agent_blocks WHERE session_id = $1",
            session_id,
        )
    return {r["agent_name"]: r["blocked_at"].isoformat() for r in rows}
