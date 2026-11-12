"""Erasure of a participant message that disclosed personal data, within one session.

The session's write filter (``utils.personal_data_filter``) keeps the text out
of everything written after the classifier's verdict. This repository removes
the copies written in the seconds before the verdict: the message row itself,
replies quoting it, safety flags and logged events.

Every change is limited to one session and to rows written from ``since`` on,
runs in one transaction, replaces only string values (JSON structure and keys
are never rewritten as text), and updates only rows whose content actually
changes. The message row is kept, with its text replaced and a
``personal_data_redacted`` marker, so the incident stays visible.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from utils.personal_data_filter import (
    PERSONAL_DATA_PLACEHOLDER,
    PersonalDataFilter,
    json_escaped,
)

_MESSAGE_TEXT_COLUMNS = ("content", "quoted_text", "classification_rationale")
_FLAG_TEXT_COLUMNS = ("content", "context_user_turn", "raw_output", "rationale", "reasoning")


def _search_patterns(data_filter: PersonalDataFilter) -> List[str]:
    """Each flagged text as stored raw, JSON-escaped once (a JSON value) and
    twice (a JSON payload inside a logged prompt). Used only to pick candidate
    rows; the filter decides what changes."""
    patterns: List[str] = []
    for text in data_filter.texts:
        once = json_escaped(text)
        for pattern in (text, once, json_escaped(once)):
            if pattern not in patterns:
                patterns.append(pattern)
    return patterns


def _scrub_json_text(data_filter: PersonalDataFilter, raw: Optional[str]) -> Tuple[Optional[str], bool]:
    if raw is None:
        return None, False
    value = json.loads(raw)
    new_value = data_filter.apply(value)
    if new_value == value:
        return raw, False
    return json.dumps(new_value, ensure_ascii=False), True


async def _plan(
    conn: asyncpg.Connection,
    session_id: str,
    data_filter: PersonalDataFilter,
    since: datetime,
) -> Dict[str, List[Tuple[Any, ...]]]:
    """Find the rows of one session that still hold a flagged text and work out
    their new values. Reads only."""
    patterns = _search_patterns(data_filter)
    plan: Dict[str, List[Tuple[Any, ...]]] = {"messages": [], "safety_flags": [], "events": []}

    rows = await conn.fetch(
        """SELECT message_id, content, quoted_text, classification_rationale,
                  metadata::text AS metadata
           FROM messages
           WHERE session_id = $1 AND sent_at >= $2
             AND EXISTS (SELECT 1 FROM unnest($3::text[]) AS p(t)
                         WHERE strpos(content, p.t) > 0
                            OR strpos(coalesce(quoted_text, ''), p.t) > 0
                            OR strpos(coalesce(classification_rationale, ''), p.t) > 0
                            OR strpos(coalesce(metadata::text, ''), p.t) > 0)""",
        session_id, since, patterns,
    )
    for row in rows:
        values = [
            data_filter.scrub_text(row[col]) if row[col] is not None else None
            for col in _MESSAGE_TEXT_COLUMNS
        ]
        metadata, metadata_changed = _scrub_json_text(data_filter, row["metadata"])
        if metadata_changed or any(
            new != row[col] for new, col in zip(values, _MESSAGE_TEXT_COLUMNS)
        ):
            plan["messages"].append((row["message_id"], *values, metadata))

    rows = await conn.fetch(
        """SELECT flag_id, content, context_user_turn, raw_output, rationale, reasoning
           FROM safety_flags
           WHERE session_id = $1 AND created_at >= $2
             AND EXISTS (SELECT 1 FROM unnest($3::text[]) AS p(t)
                         WHERE strpos(content, p.t) > 0
                            OR strpos(context_user_turn, p.t) > 0
                            OR strpos(coalesce(raw_output, ''), p.t) > 0
                            OR strpos(coalesce(rationale, ''), p.t) > 0
                            OR strpos(coalesce(reasoning, ''), p.t) > 0)""",
        session_id, since, patterns,
    )
    for row in rows:
        values = [
            data_filter.scrub_text(row[col]) if row[col] is not None else None
            for col in _FLAG_TEXT_COLUMNS
        ]
        if any(new != row[col] for new, col in zip(values, _FLAG_TEXT_COLUMNS)):
            plan["safety_flags"].append((row["flag_id"], *values))

    rows = await conn.fetch(
        """SELECT id, data::text AS data
           FROM events
           WHERE session_id = $1 AND occurred_at >= $2
             AND EXISTS (SELECT 1 FROM unnest($3::text[]) AS p(t)
                         WHERE strpos(data::text, p.t) > 0)""",
        session_id, since, patterns,
    )
    for row in rows:
        data, changed = _scrub_json_text(data_filter, row["data"])
        if changed:
            plan["events"].append((row["id"], data))
    return plan


async def count_personal_data_copies(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    data_filter: PersonalDataFilter,
    since: datetime,
) -> Dict[str, int]:
    """How many rows per table still hold a flagged text. Writes nothing."""
    if not data_filter.active:
        return {"messages": 0, "safety_flags": 0, "events": 0}
    async with pool.acquire() as conn:
        plan = await _plan(conn, session_id, data_filter, since)
    return {table: len(rows) for table, rows in plan.items()}


async def erase_personal_data(
    pool: asyncpg.Pool,
    *,
    session_id: str,
    data_filter: PersonalDataFilter,
    since: datetime,
    message_id: Optional[str] = None,
) -> Dict[str, int]:
    """Replace the flagged texts in this session's rows written from ``since``.

    ``message_id`` names the flagged message, whose text is replaced whole and
    which is marked ``personal_data_redacted``. Returns the number of rows
    changed per table.
    """
    counts = {"message": 0, "messages": 0, "safety_flags": 0, "events": 0}
    if not data_filter.active:
        return counts
    async with pool.acquire() as conn:
        async with conn.transaction():
            if message_id:
                status = await conn.execute(
                    """UPDATE messages
                       SET content = $1,
                           metadata = coalesce(metadata, '{}'::jsonb)
                                      || '{"personal_data_redacted": true}'::jsonb
                       WHERE message_id = $2 AND session_id = $3""",
                    PERSONAL_DATA_PLACEHOLDER, message_id, session_id,
                )
                counts["message"] = int(status.split()[-1])

            plan = await _plan(conn, session_id, data_filter, since)
            for message_row_id, content, quoted_text, rationale, metadata in plan["messages"]:
                await conn.execute(
                    """UPDATE messages
                       SET content = $2, quoted_text = $3,
                           classification_rationale = $4, metadata = $5::jsonb
                       WHERE message_id = $1 AND session_id = $6""",
                    message_row_id, content, quoted_text, rationale, metadata, session_id,
                )
            for flag_id, content, context, raw_output, rationale, reasoning in plan["safety_flags"]:
                await conn.execute(
                    """UPDATE safety_flags
                       SET content = $2, context_user_turn = $3, raw_output = $4,
                           rationale = $5, reasoning = $6
                       WHERE flag_id = $1 AND session_id = $7""",
                    flag_id, content, context, raw_output, rationale, reasoning, session_id,
                )
            for event_id, data in plan["events"]:
                await conn.execute(
                    "UPDATE events SET data = $2::jsonb WHERE id = $1 AND session_id = $3",
                    event_id, data, session_id,
                )
            counts["messages"] = len(plan["messages"])
            counts["safety_flags"] = len(plan["safety_flags"])
            counts["events"] = len(plan["events"])
    return counts
