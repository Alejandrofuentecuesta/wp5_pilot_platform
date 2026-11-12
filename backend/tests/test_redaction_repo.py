"""redaction_repo against a live PostgreSQL (skips without one, like other DB tests)."""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio

from db.repositories import event_repo, message_repo, safety_repo
from db.repositories.redaction_repo import PERSONAL_DATA_PLACEHOLDER, redact_participant_message

EXP = "redaction_test_exp"
SESSION = "00000000-0000-0000-0000-00000000ab01"
SECRET = 'Mi tlf es 612 345 678 y vivo en "Calle Falsa 1"'


@pytest_asyncio.fixture(loop_scope="session")
async def seed(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO experiments(experiment_id, config) VALUES($1, $2::jsonb) ON CONFLICT DO NOTHING",
            EXP, json.dumps({"simulation": {}, "experimental": {}}),
        )
        await conn.execute(
            "INSERT INTO tokens(token, experiment_id, treatment_group) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            "redaction-tok", EXP, "control",
        )
        await conn.execute(
            """INSERT INTO sessions(session_id, experiment_id, token, treatment_group, user_name, status)
               VALUES($1,$2,$3,$4,$5,'active') ON CONFLICT DO NOTHING""",
            SESSION, EXP, "redaction-tok", "control", "Paula",
        )
    yield
    async with db_pool.acquire() as conn:
        for table in ("events", "safety_flags", "messages"):
            await conn.execute(f"DELETE FROM {table} WHERE session_id = $1", SESSION)
        await conn.execute("DELETE FROM sessions WHERE session_id = $1", SESSION)
        await conn.execute("DELETE FROM tokens WHERE token = 'redaction-tok'")
        await conn.execute("DELETE FROM experiments WHERE experiment_id = $1", EXP)


@pytest.mark.asyncio(loop_scope="session")
async def test_redaction_removes_text_everywhere(db_pool, seed):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    mid, reply_id = str(uuid.uuid4()), str(uuid.uuid4())
    await message_repo.insert_message(db_pool, message_id=mid, session_id=SESSION, experiment_id=EXP,
                                      sender="Paula", content=SECRET, sent_at=now)
    await message_repo.insert_message(db_pool, message_id=reply_id, session_id=SESSION, experiment_id=EXP,
                                      sender="Carlos", content="respuesta", sent_at=now,
                                      reply_to=mid, quoted_text=SECRET)
    await event_repo.insert_event(db_pool, session_id=SESSION, experiment_id=EXP,
                                  event_type="message", data={"content": SECRET})
    # The safety prompt JSON-encodes the message before it is logged.
    await event_repo.insert_event(db_pool, session_id=SESSION, experiment_id=EXP, event_type="llm_call",
                                  data={"prompt": json.dumps({"latest": SECRET}, ensure_ascii=False)})

    await redact_participant_message(db_pool, session_id=SESSION, message_id=mid, content=SECRET)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT content, quoted_text, metadata FROM messages WHERE session_id = $1", SESSION)
        events = await conn.fetch("SELECT data::text AS d FROM events WHERE session_id = $1", SESSION)
    dump = json.dumps([dict(r) for r in rows], default=str) + "".join(e["d"] for e in events)
    assert "612 345 678" not in dump
    assert dump.count(PERSONAL_DATA_PLACEHOLDER) >= 4
    assert any(json.loads(r["metadata"]).get("personal_data_redacted") for r in rows)
