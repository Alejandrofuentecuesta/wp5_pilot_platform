"""Event repository — append-only log of simulation events."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import asyncpg


async def insert_event(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    experiment_id: str,
    event_type: str,
    data: Any,
) -> None:
    """Append an event row. Swallows exceptions so logging never crashes callers."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO events(session_id, experiment_id, event_type, data)
                VALUES($1, $2, $3, $4)
                """,
                session_id,
                experiment_id,
                event_type,
                json.dumps(data),
            )
    except Exception as exc:
        # Event logging must never crash the application.
        import sys
        print(f"[event_repo] Failed to insert event '{event_type}': {exc}", file=sys.stderr)


async def get_session_events(
    pool: asyncpg.Pool,
    session_id: str,
    event_types: Optional[List[str]] = None,
) -> List[dict]:
    """Return events for a session, optionally filtered by type."""
    async with pool.acquire() as conn:
        if event_types:
            rows = await conn.fetch(
                """
                SELECT id, event_type, occurred_at, data
                FROM   events
                WHERE  session_id = $1 AND event_type = ANY($2)
                ORDER  BY occurred_at
                """,
                session_id,
                event_types,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, event_type, occurred_at, data
                FROM   events
                WHERE  session_id = $1
                ORDER  BY occurred_at
                """,
                session_id,
            )
    return [
        {
            "id": r["id"],
            "event_type": r["event_type"],
            "occurred_at": r["occurred_at"].isoformat(),
            "data": r["data"] if isinstance(r["data"], dict) else json.loads(r["data"]),
        }
        for r in rows
    ]
