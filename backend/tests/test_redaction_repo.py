"""redaction_repo against a live PostgreSQL (skips without one, like other DB tests).

What must hold: the flagged text disappears from every table of the session,
nothing outside the session or before ``since`` changes, JSON keys and
structure survive, rows without the text are not rewritten, and a short text
is only replaced where a whole value equals it.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from db.repositories import event_repo, message_repo, safety_repo
from db.repositories.redaction_repo import count_personal_data_copies, erase_personal_data
from utils.personal_data_filter import PERSONAL_DATA_PLACEHOLDER, PersonalDataFilter

EXP = "redaction_test_exp"
SESSION = "00000000-0000-0000-0000-00000000ab01"
OTHER_SESSION = "00000000-0000-0000-0000-00000000ab02"
ALIAS = "participante_test"
SECRET = 'Mi tlf es 612 345 678 y vivo en "Calle Falsa 1"'


@pytest_asyncio.fixture(loop_scope="session")
async def seed(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO experiments(experiment_id, config) VALUES($1, $2::jsonb) ON CONFLICT DO NOTHING",
            EXP, json.dumps({"simulation": {}, "experimental": {}}),
        )
        for token, session in (("redaction-tok", SESSION), ("redaction-tok-2", OTHER_SESSION)):
            await conn.execute(
                "INSERT INTO tokens(token, experiment_id, treatment_group) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                token, EXP, "control",
            )
            await conn.execute(
                """INSERT INTO sessions(session_id, experiment_id, token, treatment_group, user_name, status)
                   VALUES($1,$2,$3,$4,$5,'active') ON CONFLICT DO NOTHING""",
                session, EXP, token, "control", ALIAS,
            )
    yield
    async with db_pool.acquire() as conn:
        for session in (SESSION, OTHER_SESSION):
            for table in ("events", "safety_flags", "messages"):
                await conn.execute(f"DELETE FROM {table} WHERE session_id = $1", session)
            await conn.execute("DELETE FROM sessions WHERE session_id = $1", session)
        await conn.execute("DELETE FROM tokens WHERE token IN ('redaction-tok', 'redaction-tok-2')")
        await conn.execute("DELETE FROM experiments WHERE experiment_id = $1", EXP)


def _filter(*texts: str) -> PersonalDataFilter:
    data_filter = PersonalDataFilter()
    for text in texts:
        data_filter.add(text)
    return data_filter


async def _message(db_pool, session, content, *, sent_at, reply_to=None, quoted_text=None, sender=ALIAS):
    message_id = str(uuid.uuid4())
    await message_repo.insert_message(
        db_pool, message_id=message_id, session_id=session, experiment_id=EXP,
        sender=sender, content=content, sent_at=sent_at,
        reply_to=reply_to, quoted_text=quoted_text,
    )
    return message_id


async def _dump(db_pool, session) -> str:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT content, quoted_text, metadata::text AS m FROM messages WHERE session_id = $1", session
        )
        flags = await conn.fetch(
            "SELECT content, context_user_turn FROM safety_flags WHERE session_id = $1", session
        )
        events = await conn.fetch("SELECT data::text AS d FROM events WHERE session_id = $1", session)
    return (
        json.dumps([dict(r) for r in rows], default=str)
        + json.dumps([dict(f) for f in flags], default=str)
        + "".join(e["d"] for e in events)
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_erasure_removes_the_text_from_every_table(db_pool, seed):
    now = datetime.now(timezone.utc)
    mid = await _message(db_pool, SESSION, SECRET, sent_at=now)
    await _message(db_pool, SESSION, "respuesta", sent_at=now, reply_to=mid,
                   quoted_text=SECRET, sender="Carlos")
    await event_repo.insert_event(db_pool, session_id=SESSION, experiment_id=EXP,
                                  event_type="message", data={"content": SECRET, "sender": ALIAS})
    # A logged prompt holds the message JSON-encoded inside a JSON payload.
    await event_repo.insert_event(
        db_pool, session_id=SESSION, experiment_id=EXP, event_type="llm_call",
        data={"prompt": "Chat:\n" + json.dumps({"latest": SECRET}, ensure_ascii=False)},
    )
    await safety_repo.insert_flag(
        db_pool, flag_id=str(uuid.uuid4()), session_id=SESSION, experiment_id=EXP,
        message_id=mid, sender_type="participant", sender=ALIAS, content=SECRET,
        context_user_turn=SECRET, verdict="unsafe",
    )

    counts = await erase_personal_data(
        db_pool, session_id=SESSION, data_filter=_filter(SECRET),
        since=now - timedelta(seconds=5), message_id=mid,
    )

    dump = await _dump(db_pool, SESSION)
    assert "612 345 678" not in dump
    assert PERSONAL_DATA_PLACEHOLDER in dump
    assert counts == {"message": 1, "messages": 1, "safety_flags": 1, "events": 2}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT content, metadata FROM messages WHERE message_id = $1", mid)
        prompt_event = await conn.fetchrow(
            "SELECT data FROM events WHERE session_id = $1 AND event_type = 'llm_call'", SESSION
        )
    assert row["content"] == PERSONAL_DATA_PLACEHOLDER
    assert json.loads(row["metadata"])["personal_data_redacted"] is True
    # Structure and keys survive; only the string value changed.
    assert json.loads(prompt_event["data"]) == {
        "prompt": "Chat:\n" + json.dumps({"latest": PERSONAL_DATA_PLACEHOLDER}, ensure_ascii=False)
    }
    assert await count_personal_data_copies(
        db_pool, session_id=SESSION, data_filter=_filter(SECRET), since=now - timedelta(seconds=5),
    ) == {"messages": 0, "safety_flags": 0, "events": 0}


@pytest.mark.asyncio(loop_scope="session")
async def test_erasure_leaves_other_sessions_earlier_rows_and_clean_rows_alone(db_pool, seed):
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(minutes=10)
    other_mid = await _message(db_pool, OTHER_SESSION, SECRET, sent_at=now)
    earlier_mid = await _message(db_pool, SESSION, SECRET + " (antes)", sent_at=earlier)
    clean_mid = await _message(db_pool, SESSION, "nada que ver", sent_at=now)
    mid = await _message(db_pool, SESSION, SECRET, sent_at=now)

    await erase_personal_data(
        db_pool, session_id=SESSION, data_filter=_filter(SECRET),
        since=now - timedelta(seconds=5), message_id=mid,
    )

    async with db_pool.acquire() as conn:
        other = await conn.fetchval("SELECT content FROM messages WHERE message_id = $1", other_mid)
        before = await conn.fetchval("SELECT content FROM messages WHERE message_id = $1", earlier_mid)
        clean = await conn.fetchrow("SELECT content, metadata FROM messages WHERE message_id = $1", clean_mid)
    assert other == SECRET
    assert before == SECRET + " (antes)"
    assert clean["content"] == "nada que ver"
    assert "personal_data_redacted" not in json.loads(clean["metadata"])


@pytest.mark.asyncio(loop_scope="session")
async def test_a_short_text_is_replaced_only_where_a_whole_value_equals_it(db_pool, seed):
    now = datetime.now(timezone.utc)
    short = "Ana Gil"  # below MIN_SUBSTRING_LENGTH
    mid = await _message(db_pool, SESSION, short, sent_at=now)
    reply = await _message(db_pool, SESSION, "Hola", sent_at=now, reply_to=mid,
                           quoted_text=short, sender="Carlos")
    unrelated = await _message(db_pool, SESSION, "Ana Gil y otros dicen algo", sent_at=now,
                               sender="Diego")

    await erase_personal_data(
        db_pool, session_id=SESSION, data_filter=_filter(short),
        since=now - timedelta(seconds=5), message_id=mid,
    )

    async with db_pool.acquire() as conn:
        quoted = await conn.fetchval("SELECT quoted_text FROM messages WHERE message_id = $1", reply)
        other = await conn.fetchval("SELECT content FROM messages WHERE message_id = $1", unrelated)
    assert quoted == PERSONAL_DATA_PLACEHOLDER
    assert other == "Ana Gil y otros dicen algo"


@pytest.mark.asyncio(loop_scope="session")
async def test_inactive_filter_changes_nothing(db_pool, seed):
    now = datetime.now(timezone.utc)
    mid = await _message(db_pool, SESSION, SECRET, sent_at=now)

    counts = await erase_personal_data(
        db_pool, session_id=SESSION, data_filter=PersonalDataFilter(),
        since=now - timedelta(seconds=5), message_id=mid,
    )

    assert counts == {"message": 0, "messages": 0, "safety_flags": 0, "events": 0}
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT content FROM messages WHERE message_id = $1", mid) == SECRET
