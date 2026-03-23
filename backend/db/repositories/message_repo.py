"""Message repository — persistent storage for chat messages."""
from __future__ import annotations

import json
import uuid
from typing import Dict, List, Optional

import asyncpg


async def insert_message(
    pool: asyncpg.Pool,
    *,
    message_id: str,
    session_id: str,
    experiment_id: str,
    sender: str,
    content: str,
    sent_at,
    reply_to: Optional[str] = None,
    quoted_text: Optional[str] = None,
    mentions: Optional[List[str]] = None,
    liked_by: Optional[List[str]] = None,
    reported: bool = False,
    is_incivil: Optional[bool] = None,
    is_like_minded: Optional[bool] = None,
    inferred_participant_stance: Optional[str] = None,
    classification_rationale: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Insert a new message row. Idempotent on message_id conflict."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messages(
                message_id, session_id, experiment_id, sender, content, sent_at,
                reply_to, quoted_text, mentions, liked_by, reported,
                is_incivil, is_like_minded, inferred_participant_stance, classification_rationale,
                metadata
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
            ON CONFLICT(message_id) DO NOTHING
            """,
            message_id,
            session_id,
            experiment_id,
            sender,
            content,
            sent_at,
            reply_to,
            quoted_text,
            mentions or [],
            liked_by or [],
            reported,
            is_incivil,
            is_like_minded,
            inferred_participant_stance,
            classification_rationale,
            json.dumps(metadata or {}),
        )


async def get_session_messages(
    pool: asyncpg.Pool, session_id: str
) -> List[dict]:
    """Return all messages for a session ordered by seq (chronological)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT message_id, sender, content, sent_at,
                   reply_to, quoted_text, mentions, liked_by, reported,
                   is_incivil, is_like_minded, inferred_participant_stance, classification_rationale,
                   metadata, seq
            FROM   messages
            WHERE  session_id = $1
            ORDER  BY seq
            """,
            session_id,
        )
    results = []
    for r in rows:
        meta = r["metadata"] if isinstance(r["metadata"], dict) else json.loads(r["metadata"]) if r["metadata"] else {}
        d = {
            "message_id": str(r["message_id"]),
            "sender": r["sender"],
            "content": r["content"],
            "timestamp": r["sent_at"].isoformat(),
            "reply_to": str(r["reply_to"]) if r["reply_to"] else None,
            "quoted_text": r["quoted_text"],
            "mentions": list(r["mentions"]) if r["mentions"] else None,
            "likes_count": len(r["liked_by"]),
            "liked_by": list(r["liked_by"]),
            "reported": r["reported"],
            "is_incivil": r["is_incivil"],
            "is_like_minded": r["is_like_minded"],
            "inferred_participant_stance": r["inferred_participant_stance"],
            "classification_rationale": r["classification_rationale"],
        }
        if meta:
            d.update(meta)
        results.append(d)
    return results


async def get_manual_evaluations(
    pool: asyncpg.Pool, session_id: str
) -> Dict[str, dict]:
    """Return saved manual evaluation rows keyed by message_id."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                message_id,
                incivility,
                hate_speech,
                threats_to_dem_freedom,
                impoliteness,
                alignment,
                human_like,
                other,
                updated_at
            FROM manual_message_evaluations
            WHERE session_id = $1
            """,
            session_id,
        )
    return {
        str(r["message_id"]): {
            "incivility": bool(r["incivility"]),
            "hate_speech": bool(r["hate_speech"]),
            "threats_to_dem_freedom": bool(r["threats_to_dem_freedom"]),
            "impoliteness": bool(r["impoliteness"]),
            "alignment": r["alignment"] or "",
            "human_like": r["human_like"] or "",
            "other": r["other"] or "",
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    }


async def replace_manual_evaluations(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    experiment_id: str,
    evaluations: List[dict],
) -> None:
    """Replace the full saved manual evaluation snapshot for a session."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM manual_message_evaluations WHERE session_id = $1",
            session_id,
        )
        if not evaluations:
            return

        await conn.executemany(
            """
            INSERT INTO manual_message_evaluations(
                session_id,
                message_id,
                experiment_id,
                incivility,
                hate_speech,
                threats_to_dem_freedom,
                impoliteness,
                alignment,
                human_like,
                other,
                updated_at
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
            """,
            [
                (
                    session_id,
                    str(uuid.UUID(str(item["message_id"]))),
                    experiment_id,
                    bool(item.get("incivility", False)),
                    bool(item.get("hate_speech", False)),
                    bool(item.get("threats_to_dem_freedom", False)),
                    bool(item.get("impoliteness", False)),
                    str(item.get("alignment", "") or ""),
                    str(item.get("human_like", "") or ""),
                    str(item.get("other", "") or ""),
                )
                for item in evaluations
            ],
        )


async def update_message_likes(
    pool: asyncpg.Pool, message_id: str, liked_by: List[str]
) -> None:
    """Replace the liked_by array for a message."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET liked_by = $1 WHERE message_id = $2",
            liked_by,
            message_id,
        )


async def update_message_reported(
    pool: asyncpg.Pool, message_id: str, reported: bool
) -> None:
    """Update the reported flag for a message."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET reported = $1 WHERE message_id = $2",
            reported,
            message_id,
        )
