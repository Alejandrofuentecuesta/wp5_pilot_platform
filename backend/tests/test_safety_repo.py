"""safety_repo against a live PostgreSQL (skips without one, like other DB tests)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from db.repositories import message_repo, safety_repo

EXP = "safety_test_exp"
SESSION = "00000000-0000-0000-0000-00000000aa01"


@pytest_asyncio.fixture(loop_scope="session")
async def seed(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO experiments(experiment_id, config) VALUES($1, $2::jsonb) ON CONFLICT DO NOTHING",
            EXP, json.dumps({"simulation": {}, "experimental": {"safety": {"enabled": True}}}),
        )
        await conn.execute(
            "INSERT INTO tokens(token, experiment_id, treatment_group) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            "safety-tok", EXP, "control",
        )
        await conn.execute(
            """INSERT INTO sessions(session_id, experiment_id, token, treatment_group, user_name, status)
               VALUES($1,$2,$3,$4,$5,'active') ON CONFLICT DO NOTHING""",
            SESSION, EXP, "safety-tok", "control", "Paula",
        )
    yield
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM safety_flags WHERE session_id = $1", SESSION)
        await conn.execute("DELETE FROM messages WHERE session_id = $1", SESSION)
        await conn.execute("DELETE FROM sessions WHERE session_id = $1", SESSION)
        await conn.execute("DELETE FROM tokens WHERE token = 'safety-tok'")
        await conn.execute("DELETE FROM experiments WHERE experiment_id = $1", EXP)


async def _insert_message(db_pool, content="hola"):
    mid = str(uuid.uuid4())
    await message_repo.insert_message(
        db_pool, message_id=mid, session_id=SESSION, experiment_id=EXP,
        sender="Carlos", content=content, sent_at=datetime.now(timezone.utc),
    )
    return mid


@pytest.mark.asyncio(loop_scope="session")
async def test_flag_lifecycle(db_pool, seed):
    mid = await _insert_message(db_pool)
    fid = str(uuid.uuid4())
    await safety_repo.insert_flag(
        db_pool, flag_id=fid, session_id=SESSION, experiment_id=EXP,
        message_id=mid, sender_type="agent", sender="Carlos", content="hola",
        context_user_turn="ctx", verdict="unsafe", categories=["S10"],
        raw_output="unsafe\nS10", model="g", prompt_hash="h",
        displayed_at=datetime.now(timezone.utc),
    )
    await safety_repo.set_flag_seq(db_pool, fid, mid)
    await safety_repo.set_message_safety_verdict(db_pool, mid, "unsafe")

    open_flags = await safety_repo.list_flags(db_pool, status="open")
    mine = [f for f in open_flags if f["flag_id"] == fid]
    assert len(mine) == 1
    f = mine[0]
    assert f["seq"] is not None
    assert f["user_name"] == "Paula" and f["treatment_group"] == "control"
    assert f["categories"] == ["S10"]
    assert f["session_status"] == "active"

    summary = await safety_repo.summary(db_pool)
    assert summary["open_flags"] >= 1
    assert summary["live_sessions"] >= 1

    assert await safety_repo.review_flag(db_pool, flag_id=fid, verdict="no_concern", reviewer="Laia") is True
    assert not [x for x in await safety_repo.list_flags(db_pool, status="open") if x["flag_id"] == fid]
    reviewed = [x for x in await safety_repo.list_flags(db_pool, status="reviewed") if x["flag_id"] == fid]
    assert reviewed[0]["reviewed_by"] == "Laia" and reviewed[0]["review_verdict"] == "no_concern"

    verdicts = await safety_repo.verdicts_for_session(db_pool, SESSION)
    assert verdicts[mid] == "unsafe"
    # The participant-facing replay query must not carry the verdict.
    replay = await message_repo.get_session_messages(db_pool, SESSION)
    assert all("safety_verdict" not in m for m in replay)


@pytest.mark.asyncio(loop_scope="session")
async def test_review_unknown_flag_false(db_pool, seed):
    assert await safety_repo.review_flag(
        db_pool, flag_id=str(uuid.uuid4()), verdict="concern", reviewer="x"
    ) is False


@pytest.mark.asyncio(loop_scope="session")
async def test_withheld_flag_has_no_message(db_pool, seed):
    fid = str(uuid.uuid4())
    await safety_repo.insert_flag(
        db_pool, flag_id=fid, session_id=SESSION, experiment_id=EXP,
        sender_type="agent", sender="Carlos", content="retenido", verdict="unavailable",
        error="timeout",
    )
    f = [x for x in await safety_repo.list_flags(db_pool, session_id=SESSION, status="all") if x["flag_id"] == fid][0]
    assert f["message_id"] is None and f["displayed_at"] is None and f["error"] == "timeout"


@pytest.mark.asyncio(loop_scope="session")
async def test_safety_pause_persists(db_pool, seed):
    now = datetime.now(timezone.utc)
    await safety_repo.set_safety_paused(db_pool, SESSION, now)
    assert (await safety_repo.summary(db_pool))["paused_sessions"] >= 1
    await safety_repo.set_safety_paused(db_pool, SESSION, None)
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT safety_paused_at FROM sessions WHERE session_id = $1", SESSION) is None
