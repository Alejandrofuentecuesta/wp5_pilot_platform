"""Tests for db/repositories/session_repo.py"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")
from db.repositories import session_repo, token_repo

SESSION_ID = "aaaaaaaa-0000-0000-0000-000000000001"
TOKEN = "test_token_001"


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def seed_experiment(db_pool, clean_tables, experiment_id, ensure_experiment):
    """Clean DB, ensure experiment row and a token exist before each test."""
    await ensure_experiment(experiment_id)
    await token_repo.seed_tokens(
        db_pool, experiment_id, {"civil_support": [TOKEN]}
    )


async def test_create_session_pending(db_pool, experiment_id):
    await session_repo.create_session(
        db_pool,
        session_id=SESSION_ID,
        token=TOKEN,
        experiment_id=experiment_id,
        treatment_group="civil_support",
        user_name="alice",
        participant_stance="favor",
    )
    row = await session_repo.get_session(db_pool, SESSION_ID)
    assert row is not None
    assert row["status"] == "pending"
    assert row["user_name"] == "alice"
    assert row["participant_stance"] == "favor"


async def test_activate_session(db_pool, experiment_id):
    await session_repo.create_session(
        db_pool,
        session_id=SESSION_ID,
        token=TOKEN,
        experiment_id=experiment_id,
        treatment_group="civil_support",
        user_name="alice",
    )
    now = datetime.now(timezone.utc)
    await session_repo.activate_session(
        db_pool,
        session_id=SESSION_ID,
        started_at=now,
        random_seed=42,
        simulation_config={"key": "value"},
        experimental_config={"internal_validity_criteria": "be civil"},
    )
    row = await session_repo.get_session(db_pool, SESSION_ID)
    assert row["status"] == "active"
    assert row["random_seed"] == 42


async def test_end_session(db_pool, experiment_id):
    await session_repo.create_session(
        db_pool,
        session_id=SESSION_ID,
        token=TOKEN,
        experiment_id=experiment_id,
        treatment_group="civil_support",
        user_name="alice",
    )
    await session_repo.end_session(db_pool, session_id=SESSION_ID, reason="duration_expired")
    row = await session_repo.get_session(db_pool, SESSION_ID)
    assert row["status"] == "ended"
    assert row["end_reason"] == "duration_expired"


async def test_agent_block_upsert_and_retrieve(db_pool, experiment_id):
    await session_repo.create_session(
        db_pool,
        session_id=SESSION_ID,
        token=TOKEN,
        experiment_id=experiment_id,
        treatment_group="civil_support",
        user_name="alice",
    )
    blocked_at = datetime.now(timezone.utc)
    await session_repo.upsert_agent_block(
        db_pool,
        session_id=SESSION_ID,
        agent_name="Carlos",
        blocked_at=blocked_at,
        blocked_by="alice",
    )
    blocks = await session_repo.get_agent_blocks(db_pool, SESSION_ID)
    assert "Carlos" in blocks
    # ISO timestamp should be parseable.
    datetime.fromisoformat(blocks["Carlos"])


async def test_agent_block_update_on_conflict(db_pool, experiment_id):
    """Re-blocking the same agent should update the timestamp."""
    await session_repo.create_session(
        db_pool,
        session_id=SESSION_ID,
        token=TOKEN,
        experiment_id=experiment_id,
        treatment_group="civil_support",
        user_name="alice",
    )
    t1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)

    await session_repo.upsert_agent_block(
        db_pool, session_id=SESSION_ID, agent_name="Carlos",
        blocked_at=t1, blocked_by="alice",
    )
    await session_repo.upsert_agent_block(
        db_pool, session_id=SESSION_ID, agent_name="Carlos",
        blocked_at=t2, blocked_by="alice",
    )
    blocks = await session_repo.get_agent_blocks(db_pool, SESSION_ID)
    # Should reflect the later timestamp.
    assert "2026-01-02" in blocks["Carlos"]
