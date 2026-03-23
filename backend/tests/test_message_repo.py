"""Tests for db/repositories/message_repo.py"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")
from db.repositories import message_repo, session_repo, token_repo

SESSION_ID = "bbbbbbbb-0000-0000-0000-000000000001"
MSG_A = "00000aaa-0000-0000-0000-000000000001"
MSG_B = "00000bbb-0000-0000-0000-000000000002"
TOKEN = "test_token_msg_001"


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def seed_session(db_pool, clean_tables, experiment_id, ensure_experiment):
    await ensure_experiment(experiment_id)
    await token_repo.seed_tokens(db_pool, experiment_id, {"civil_support": [TOKEN]})
    await session_repo.create_session(
        db_pool,
        session_id=SESSION_ID,
        token=TOKEN,
        experiment_id=experiment_id,
        treatment_group="civil_support",
        user_name="alice",
    )


async def _insert_msg(pool, msg_id, sender, content, experiment_id, **kwargs):
    await message_repo.insert_message(
        pool,
        message_id=msg_id,
        session_id=SESSION_ID,
        experiment_id=experiment_id,
        sender=sender,
        content=content,
        sent_at=datetime.now(timezone.utc),
        **kwargs,
    )


async def test_insert_and_retrieve_messages(db_pool, experiment_id):
    await _insert_msg(db_pool, MSG_A, "alice", "Hello!", experiment_id)
    await _insert_msg(db_pool, MSG_B, "Carlos", "Hi there.", experiment_id)

    rows = await message_repo.get_session_messages(db_pool, SESSION_ID)
    assert len(rows) == 2
    assert rows[0]["sender"] == "alice"
    assert rows[1]["sender"] == "Carlos"


async def test_messages_ordered_by_seq(db_pool, experiment_id):
    # Insert in deliberate order; seq should preserve insertion order.
    for i, (sender, content) in enumerate([
        ("alice", "first"),
        ("Carlos", "second"),
        ("María", "third"),
    ]):
        await _insert_msg(db_pool, f"00000000-0000-0000-0000-0000000{i:05d}", sender, content, experiment_id)

    rows = await message_repo.get_session_messages(db_pool, SESSION_ID)
    assert [r["content"] for r in rows] == ["first", "second", "third"]


async def test_insert_idempotent(db_pool, experiment_id):
    """Inserting the same message_id twice must not raise or duplicate."""
    await _insert_msg(db_pool, MSG_A, "alice", "Hello!", experiment_id)
    await _insert_msg(db_pool, MSG_A, "alice", "Hello!", experiment_id)
    rows = await message_repo.get_session_messages(db_pool, SESSION_ID)
    assert len(rows) == 1


async def test_update_likes(db_pool, experiment_id):
    await _insert_msg(db_pool, MSG_A, "alice", "Hello!", experiment_id)

    await message_repo.update_message_likes(db_pool, MSG_A, ["Carlos", "María"])
    rows = await message_repo.get_session_messages(db_pool, SESSION_ID)
    assert rows[0]["likes_count"] == 2
    assert set(rows[0]["liked_by"]) == {"Carlos", "María"}


async def test_update_reported(db_pool, experiment_id):
    await _insert_msg(db_pool, MSG_A, "Carlos", "Rude comment", experiment_id)

    await message_repo.update_message_reported(db_pool, MSG_A, True)
    rows = await message_repo.get_session_messages(db_pool, SESSION_ID)
    assert rows[0]["reported"] is True

    await message_repo.update_message_reported(db_pool, MSG_A, False)
    rows = await message_repo.get_session_messages(db_pool, SESSION_ID)
    assert rows[0]["reported"] is False


async def test_message_with_reply_metadata(db_pool, experiment_id):
    await _insert_msg(db_pool, MSG_A, "alice", "Original message", experiment_id)
    await _insert_msg(
        db_pool, MSG_B, "Carlos", "I agree!",
        experiment_id,
        reply_to=MSG_A,
        quoted_text="Original message",
    )
    rows = await message_repo.get_session_messages(db_pool, SESSION_ID)
    reply = rows[1]
    assert reply["reply_to"] == MSG_A
    assert reply["quoted_text"] == "Original message"


async def test_replace_and_load_manual_evaluations(db_pool, experiment_id):
    await _insert_msg(db_pool, MSG_A, "alice", "Hello!", experiment_id)
    await _insert_msg(db_pool, MSG_B, "Carlos", "Hi there.", experiment_id)

    await message_repo.replace_manual_evaluations(
        db_pool,
        session_id=SESSION_ID,
        experiment_id=experiment_id,
        evaluations=[
            {
                "message_id": MSG_A,
                "incivility": True,
                "hate_speech": False,
                "threats_to_dem_freedom": False,
                "impoliteness": True,
                "alignment": "like_minded",
                "human_like": "yes",
                "other": "note",
            },
            {
                "message_id": MSG_B,
                "incivility": False,
                "hate_speech": True,
                "threats_to_dem_freedom": True,
                "impoliteness": False,
                "alignment": "not_like_minded",
                "human_like": "no",
                "other": "",
            },
        ],
    )

    saved = await message_repo.get_manual_evaluations(db_pool, SESSION_ID)
    assert saved[MSG_A]["incivility"] is True
    assert saved[MSG_A]["impoliteness"] is True
    assert saved[MSG_A]["alignment"] == "like_minded"
    assert saved[MSG_A]["human_like"] == "yes"
    assert saved[MSG_B]["hate_speech"] is True
    assert saved[MSG_B]["threats_to_dem_freedom"] is True


async def test_replace_manual_evaluations_overwrites_previous_snapshot(db_pool, experiment_id):
    await _insert_msg(db_pool, MSG_A, "alice", "Hello!", experiment_id)
    await _insert_msg(db_pool, MSG_B, "Carlos", "Hi there.", experiment_id)

    await message_repo.replace_manual_evaluations(
        db_pool,
        session_id=SESSION_ID,
        experiment_id=experiment_id,
        evaluations=[
            {
                "message_id": MSG_A,
                "incivility": True,
                "hate_speech": False,
                "threats_to_dem_freedom": False,
                "impoliteness": False,
                "alignment": "",
                "human_like": "",
                "other": "",
            }
        ],
    )
    await message_repo.replace_manual_evaluations(
        db_pool,
        session_id=SESSION_ID,
        experiment_id=experiment_id,
        evaluations=[
            {
                "message_id": MSG_B,
                "incivility": False,
                "hate_speech": True,
                "threats_to_dem_freedom": False,
                "impoliteness": True,
                "alignment": "like_minded",
                "human_like": "yes",
                "other": "updated",
            }
        ],
    )

    saved = await message_repo.get_manual_evaluations(db_pool, SESSION_ID)
    assert MSG_A not in saved
    assert saved[MSG_B]["hate_speech"] is True
    assert saved[MSG_B]["other"] == "updated"
