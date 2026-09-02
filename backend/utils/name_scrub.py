"""Name scrubbing for sessions that predate the alias system.

Sessions now run under a backend-assigned alias and the typed name never
leaves the browser, so nothing needs scrubbing going forward. Sessions
recorded before that change carry real first names, and the startup sweep
uses ``scrub_session_records`` to rewrite them to the canonical
``participant`` placeholder — the value the system has always used when no
name was given, so a scrubbed session is indistinguishable from a nameless
one to every downstream consumer.

Matching is by whole word, case- and accent-insensitive, because bots and
participants were inconsistent about accents ("Lucia" vs "Lucía"). The
text helpers here are also used for agent renames at session construction.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, List, Optional, Tuple

import asyncpg

CANONICAL_NAME = "participant"

# Unicode-aware word tokens ("Lucía", "María-José"): [^\W\d_] is "any
# letter" in stdlib re, avoiding a dependency on the `regex` package.
_WORD_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|['’-])*", re.UNICODE)


def fold(value: str) -> str:
    """Casefold and strip accents, for name comparison."""
    decomposed = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def is_scrub_target(name: Optional[str]) -> bool:
    """True when a session carries a real name that needs scrubbing."""
    return bool(name and name.strip()) and fold(name) != fold(CANONICAL_NAME)


def scrub_text(
    text: Optional[str],
    name: str,
    replacement: str = CANONICAL_NAME,
) -> Tuple[Optional[str], bool]:
    """Replace whole-word occurrences of ``name`` in free text.

    Tokens are compared accent- and case-insensitively, so "Lucía" matches
    a participant who typed "Lucia" and vice versa. "Lucianos" does not.
    Returns (new_text, changed).
    """
    if not text:
        return text, False
    target = fold(name)
    if not target:
        return text, False
    parts: List[str] = []
    last = 0
    changed = False
    for match in _WORD_RE.finditer(text):
        if fold(match.group()) == target:
            parts.append(text[last:match.start()])
            parts.append(replacement)
            last = match.end()
            changed = True
    if not changed:
        return text, False
    parts.append(text[last:])
    return "".join(parts), True


def scrub_json(value: Any, name: str) -> Tuple[Any, bool]:
    """Recursively scrub every string value in a parsed JSON structure.

    Keys are left untouched — they are schema, not content.
    """
    if isinstance(value, str):
        new, changed = scrub_text(value, name)
        return new, changed
    if isinstance(value, list):
        changed = False
        out = []
        for item in value:
            new, item_changed = scrub_json(item, name)
            out.append(new)
            changed = changed or item_changed
        return (out, True) if changed else (value, False)
    if isinstance(value, dict):
        changed = False
        out = {}
        for key, item in value.items():
            new, item_changed = scrub_json(item, name)
            out[key] = new
            changed = changed or item_changed
        return (out, True) if changed else (value, False)
    return value, False


def _parsed(blob: Any) -> Any:
    """asyncpg returns JSONB as str unless a codec is registered."""
    if isinstance(blob, str):
        return json.loads(blob)
    return blob


async def scrub_session_records(pool: asyncpg.Pool, session_id: str) -> bool:
    """Rewrite a session's stored name to the canonical placeholder.

    Touches messages (sender, content, quoted text, mentions, likes,
    metadata), events (the JSON payloads, which include full LLM prompts),
    and the session row's config blobs. ``sessions.user_name`` is updated
    LAST: if the scrub dies partway, the name survives there and the
    startup sweep retries the whole thing on the next boot.

    Returns True when a name was scrubbed, False when there was nothing
    to do.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_name FROM sessions WHERE session_id = $1", session_id
        )
        if not row or not is_scrub_target(row["user_name"]):
            return False
        name = row["user_name"].strip()
        folded_name = fold(name)

        messages = await conn.fetch(
            "SELECT message_id, sender, content, quoted_text, mentions, liked_by, metadata "
            "FROM messages WHERE session_id = $1",
            session_id,
        )
        for msg in messages:
            sender = msg["sender"]
            new_sender = CANONICAL_NAME if fold(sender) == folded_name else sender
            new_content, c1 = scrub_text(msg["content"], name)
            new_quoted, c2 = scrub_text(msg["quoted_text"], name)
            mentions = msg["mentions"] or []
            new_mentions = [
                CANONICAL_NAME if fold(m) == folded_name else m for m in mentions
            ]
            liked_by = msg["liked_by"] or []
            new_liked = [
                CANONICAL_NAME if fold(u) == folded_name else u for u in liked_by
            ]
            metadata = _parsed(msg["metadata"]) if msg["metadata"] is not None else None
            new_metadata, c3 = (
                scrub_json(metadata, name) if metadata is not None else (None, False)
            )
            if (
                new_sender != sender or c1 or c2 or c3
                or new_mentions != mentions or new_liked != liked_by
            ):
                await conn.execute(
                    "UPDATE messages SET sender=$2, content=$3, quoted_text=$4, "
                    "mentions=$5, liked_by=$6, metadata=$7::jsonb WHERE message_id=$1",
                    msg["message_id"],
                    new_sender,
                    new_content,
                    new_quoted,
                    new_mentions,
                    new_liked,
                    json.dumps(new_metadata) if new_metadata is not None else None,
                )

        events = await conn.fetch(
            "SELECT id, data FROM events WHERE session_id = $1", session_id
        )
        for event in events:
            data = _parsed(event["data"])
            new_data, changed = scrub_json(data, name)
            if changed:
                await conn.execute(
                    "UPDATE events SET data = $2::jsonb WHERE id = $1",
                    event["id"],
                    json.dumps(new_data),
                )

        srow = await conn.fetchrow(
            "SELECT simulation_config, experimental_config FROM sessions WHERE session_id = $1",
            session_id,
        )
        sim = _parsed(srow["simulation_config"]) if srow["simulation_config"] is not None else None
        exp = _parsed(srow["experimental_config"]) if srow["experimental_config"] is not None else None
        new_sim, _ = scrub_json(sim, name) if sim is not None else (None, False)
        new_exp, _ = scrub_json(exp, name) if exp is not None else (None, False)
        await conn.execute(
            "UPDATE sessions SET user_name=$2, simulation_config=$3::jsonb, "
            "experimental_config=$4::jsonb WHERE session_id=$1",
            session_id,
            CANONICAL_NAME,
            json.dumps(new_sim) if new_sim is not None else None,
            json.dumps(new_exp) if new_exp is not None else None,
        )
    return True
