"""Safety repository — flags raised by the safety screen and their human review."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg


async def insert_flag(
    pool: asyncpg.Pool,
    *,
    flag_id: str,
    session_id: str,
    experiment_id: str,
    sender_type: str,
    sender: str,
    content: str,
    verdict: str,
    message_id: Optional[str] = None,
    seq: Optional[int] = None,
    context_user_turn: str = "",
    categories: Optional[List[str]] = None,
    raw_output: Optional[str] = None,
    rationale: Optional[str] = None,
    model: Optional[str] = None,
    prompt_hash: str = "",
    unsafe_prob: Optional[float] = None,
    latency_ms: Optional[int] = None,
    error: Optional[str] = None,
    displayed_at: Optional[datetime] = None,
) -> None:
    """Insert one flag row. Idempotent on flag_id."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO safety_flags(
                flag_id, session_id, experiment_id, message_id, seq,
                sender_type, sender, content, context_user_turn,
                verdict, categories, raw_output, rationale, model, prompt_hash,
                unsafe_prob, latency_ms, error, displayed_at
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
            ON CONFLICT(flag_id) DO NOTHING
            """,
            flag_id,
            session_id,
            experiment_id,
            message_id,
            seq,
            sender_type,
            sender,
            content,
            context_user_turn,
            verdict,
            categories or [],
            raw_output,
            rationale,
            model,
            prompt_hash,
            unsafe_prob,
            latency_ms,
            error,
            displayed_at,
        )


async def set_message_safety_verdict(
    pool: asyncpg.Pool, message_id: str, verdict: Optional[str]
) -> None:
    """Record the screen's verdict on a published message."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET safety_verdict = $1 WHERE message_id = $2",
            verdict,
            message_id,
        )


async def set_flag_seq(pool: asyncpg.Pool, flag_id: str, message_id: str) -> None:
    """Copy the message's seq onto the flag once the message row exists."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE safety_flags f
            SET    seq = m.seq
            FROM   messages m
            WHERE  f.flag_id = $1 AND m.message_id = $2
            """,
            flag_id,
            message_id,
        )


async def mark_flag_published(
    pool: asyncpg.Pool, flag_id: str, message_id: str, displayed_at: datetime
) -> None:
    """Link a reviewer-approved withheld flag to its newly published message."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE safety_flags f
            SET    message_id = $2,
                   displayed_at = $3,
                   seq = m.seq
            FROM   messages m
            WHERE  f.flag_id = $1
              AND  f.message_id IS NULL
              AND  m.message_id = $2
            """,
            flag_id,
            message_id,
            displayed_at,
        )


async def review_flag(
    pool: asyncpg.Pool,
    *,
    flag_id: str,
    verdict: str,
    reviewer: str,
    note: Optional[str] = None,
) -> bool:
    """Claim and record an open human review."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE safety_flags
            SET    reviewed_at = $1, reviewed_by = $2, review_verdict = $3, review_note = $4
            WHERE  flag_id = $5 AND reviewed_at IS NULL
            """,
            datetime.now(timezone.utc),
            reviewer,
            verdict,
            note,
            flag_id,
        )
    return result.endswith("1")


async def claim_flag_for_auto_release(pool: asyncpg.Pool, flag_id: str) -> bool:
    """Atomically close an unreviewed withheld flag after its review window."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE safety_flags
            SET    reviewed_at = $1,
                   reviewed_by = 'automatic_timeout',
                   review_verdict = 'no_concern',
                   review_note = 'Automatically published after 60 seconds without review'
            WHERE  flag_id = $2
              AND  reviewed_at IS NULL
              AND  message_id IS NULL
              AND  displayed_at IS NULL
              AND  sender_type = 'agent'
            """,
            datetime.now(timezone.utc),
            flag_id,
        )
    return result.endswith("1")


def _row_to_dict(r: asyncpg.Record) -> Dict[str, Any]:
    d = dict(r)
    for key in ("displayed_at", "created_at", "reviewed_at", "started_at", "ended_at", "safety_paused_at"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat()
    for key in ("flag_id", "session_id", "message_id"):
        if d.get(key) is not None:
            d[key] = str(d[key])
    if d.get("categories") is None:
        d["categories"] = []
    return d


async def list_flags(
    pool: asyncpg.Pool,
    *,
    status: str = "open",
    session_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    limit: int = 200,
    before: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """List flags newest first, joined with the session's alias, cell and status."""
    clauses: List[str] = []
    params: List[Any] = []
    if status == "open":
        clauses.append("f.reviewed_at IS NULL")
    elif status == "reviewed":
        clauses.append("f.reviewed_at IS NOT NULL")
    if session_id:
        params.append(session_id)
        clauses.append(f"f.session_id = ${len(params)}")
    if experiment_id:
        params.append(experiment_id)
        clauses.append(f"f.experiment_id = ${len(params)}")
    if before is not None:
        params.append(before)
        clauses.append(f"f.created_at < ${len(params)}")
    params.append(limit)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT f.*,
               s.user_name, s.treatment_group, s.status AS session_status,
               s.safety_paused_at, s.started_at, s.ended_at, s.end_reason
        FROM   safety_flags f
        JOIN   sessions s ON s.session_id = f.session_id
        {where}
        ORDER  BY f.created_at DESC
        LIMIT  ${len(params)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [_row_to_dict(r) for r in rows]


async def summary(pool: asyncpg.Pool) -> Dict[str, Any]:
    """Counts for the Safety tab header."""
    async with pool.acquire() as conn:
        open_count = await conn.fetchval(
            "SELECT COUNT(*) FROM safety_flags WHERE reviewed_at IS NULL"
        )
        unavailable_recent = await conn.fetchval(
            """
            SELECT COUNT(*) FROM safety_flags
            WHERE verdict = 'unavailable' AND created_at > NOW() - INTERVAL '10 minutes'
            """
        )
        last_flag_at = await conn.fetchval("SELECT MAX(created_at) FROM safety_flags")
        last_verdict_at = await conn.fetchval(
            "SELECT MAX(sent_at) FROM messages WHERE safety_verdict IS NOT NULL"
        )
        live = await conn.fetchval("SELECT COUNT(*) FROM sessions WHERE status = 'active'")
        paused = await conn.fetchval(
            "SELECT COUNT(*) FROM sessions WHERE status = 'active' AND safety_paused_at IS NOT NULL"
        )
    return {
        "open_flags": int(open_count or 0),
        "unavailable_last_10m": int(unavailable_recent or 0),
        "last_flag_at": last_flag_at.isoformat() if last_flag_at else None,
        "last_verdict_at": last_verdict_at.isoformat() if last_verdict_at else None,
        "live_sessions": int(live or 0),
        "paused_sessions": int(paused or 0),
    }


async def set_safety_paused(
    pool: asyncpg.Pool, session_id: str, paused_at: Optional[datetime]
) -> None:
    """Persist (or clear) the safety hold so it survives a restart."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET safety_paused_at = $1 WHERE session_id = $2",
            paused_at,
            session_id,
        )


async def verdicts_for_session(pool: asyncpg.Pool, session_id: str) -> Dict[str, Optional[str]]:
    """message_id → safety_verdict for one session (admin exports only).

    Kept out of ``message_repo.get_session_messages`` on purpose: that query
    is also replayed to the participant's browser on reconnect, and the
    verdict must never reach the participant.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT message_id, safety_verdict FROM messages WHERE session_id = $1", session_id
        )
    return {str(r["message_id"]): r["safety_verdict"] for r in rows}
