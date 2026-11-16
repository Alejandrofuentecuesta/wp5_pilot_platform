"""Token repository — DB-backed single-use token management.

Token consumption uses a PostgreSQL transaction with SELECT FOR UPDATE SKIP LOCKED
so it is safe under simultaneous requests from multiple workers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import asyncpg


async def seed_tokens(
    pool: asyncpg.Pool,
    experiment_id: str,
    groups: Dict[str, List[str]],
) -> None:
    """Insert tokens into the DB for a given experiment.

    The experiment row must already exist (created by config_repo).
    Idempotent — already-seeded tokens are left untouched.
    """
    async with pool.acquire() as conn:
        rows = [
            (token, group, experiment_id)
            for group, tokens in groups.items()
            for token in tokens
        ]
        await conn.executemany(
            """
            INSERT INTO tokens(token, treatment_group, experiment_id)
            VALUES($1, $2, $3)
            ON CONFLICT(token) DO NOTHING
            """,
            rows,
        )


async def consume_token(
    pool: asyncpg.Pool,
    token: str,
    session_id: str,
) -> Optional[Tuple[str, str]]:
    """Atomically mark a token used and return (treatment_group, experiment_id).

    Uses SELECT FOR UPDATE SKIP LOCKED inside a transaction so concurrent
    workers cannot double-consume the same token.

    Returns (treatment_group, experiment_id) on success, or None if the token
    is invalid, already used, or not found.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT token, treatment_group, experiment_id
                FROM   tokens
                WHERE  token = $1 AND NOT used
                FOR UPDATE SKIP LOCKED
                """,
                token,
            )
            if row is None:
                return None
            await conn.execute(
                """
                UPDATE tokens
                SET    used = TRUE, used_at = $1, session_id = $2
                WHERE  token = $3
                """,
                datetime.now(timezone.utc),
                session_id,
                token,
            )
            return (row["treatment_group"], row["experiment_id"])


async def reopen_token(pool: asyncpg.Pool, token: str, session_id: str) -> bool:
    """Make a consumed token usable again after its session failed (r=4).

    Only the session that consumed the token may reopen it: the UPDATE is
    guarded on ``used AND session_id = $2``, so a token already reused by a
    later session is left alone. Returns True if the token was reopened.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE tokens
            SET    used = FALSE, used_at = NULL, session_id = NULL
            WHERE  token = $1 AND used AND session_id = $2
            """,
            token,
            session_id,
        )
    return result == "UPDATE 1"


async def get_token_status(pool: asyncpg.Pool, token: str) -> Optional[dict]:
    """Return token row as dict, or None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tokens WHERE token = $1", token)
    return dict(row) if row else None


async def count_tokens(pool: asyncpg.Pool, experiment_id: str) -> int:
    """Return the number of tokens seeded for an experiment."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM tokens WHERE experiment_id = $1",
            experiment_id,
        )


async def list_tokens(
    pool: asyncpg.Pool,
    experiment_id: str,
) -> List[dict]:
    """List all tokens for an experiment (for admin use)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM tokens WHERE experiment_id = $1 ORDER BY treatment_group, token",
            experiment_id,
        )
    return [dict(r) for r in rows]
