"""Redaction repository — scrubs one participant message from every stored copy.

Used when a session ends because the participant disclosed personal data: the
fact that it happened is kept (the message row, its metadata flag and the
safety events), but the text itself is replaced everywhere it was stored.
"""
from __future__ import annotations

import json

import asyncpg

PERSONAL_DATA_PLACEHOLDER = "[mensaje eliminado: datos personales]"


def _json_escaped(text: str) -> str:
    """``text`` as it appears inside a JSON string (without the quotes)."""
    return json.dumps(text, ensure_ascii=False)[1:-1]


async def redact_participant_message(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    message_id: str,
    content: str,
    placeholder: str = PERSONAL_DATA_PLACEHOLDER,
) -> None:
    """Replace ``content`` with ``placeholder`` in messages, safety flags and events.

    Events store the text inside JSON, sometimes nested once more inside a
    JSON-encoded prompt, so both escaping levels are replaced. The placeholder
    contains no characters that need JSON escaping, so the result stays valid.
    """
    escaped_once = _json_escaped(content)
    escaped_twice = _json_escaped(escaped_once)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """UPDATE messages
                   SET content = $1,
                       metadata = metadata || '{"personal_data_redacted": true}'::jsonb
                   WHERE message_id = $2""",
                placeholder,
                message_id,
            )
            # Agent replies quote the message they answer.
            await conn.execute(
                "UPDATE messages SET quoted_text = $1 WHERE session_id = $2 AND reply_to = $3",
                placeholder,
                session_id,
                message_id,
            )
            await conn.execute(
                """UPDATE safety_flags
                   SET content = replace(content, $1, $3),
                       context_user_turn = replace(context_user_turn, $1, $3)
                   WHERE session_id = $2""",
                content,
                session_id,
                placeholder,
            )
            await conn.execute(
                """UPDATE events
                   SET data = replace(replace(data::text, $1, $4), $2, $4)::jsonb
                   WHERE session_id = $3
                     AND (strpos(data::text, $1) > 0 OR strpos(data::text, $2) > 0)""",
                escaped_once,
                escaped_twice,
                session_id,
                placeholder,
            )
