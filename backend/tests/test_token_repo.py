"""Tests for db/repositories/token_repo.py"""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")
from db.repositories import token_repo

GROUPS = {
    "civil_support":   ["tok_cs_001", "tok_cs_002"],
    "civil_oppose":    ["tok_co_001"],
    "uncivil_support": ["tok_us_001"],
}


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def seed(db_pool, clean_tables, experiment_id, ensure_experiment):
    """Clean DB and seed tokens before each test."""
    await ensure_experiment(experiment_id)
    await token_repo.seed_tokens(db_pool, experiment_id, GROUPS)


async def test_seed_tokens_creates_rows(db_pool, experiment_id):
    rows = await token_repo.list_tokens(db_pool, experiment_id)
    tokens = [r["token"] for r in rows]
    assert "tok_cs_001" in tokens
    assert "tok_co_001" in tokens
    assert len(rows) == 4


async def test_consume_token_returns_group_and_experiment(db_pool, experiment_id):
    result = await token_repo.consume_token(db_pool, "tok_cs_001", "aaaaaaaa-0000-0000-0000-000000000001")
    assert result == ("civil_support", experiment_id)


async def test_consumed_token_is_marked_used(db_pool, experiment_id):
    await token_repo.consume_token(db_pool, "tok_cs_001", "aaaaaaaa-0000-0000-0000-000000000001")
    status = await token_repo.get_token_status(db_pool, "tok_cs_001")
    assert status["used"] is True
    assert str(status["session_id"]) == "aaaaaaaa-0000-0000-0000-000000000001"


async def test_double_consume_returns_none(db_pool, experiment_id):
    await token_repo.consume_token(db_pool, "tok_cs_001", "aaaaaaaa-0000-0000-0000-000000000001")
    result = await token_repo.consume_token(db_pool, "tok_cs_001", "bbbbbbbb-0000-0000-0000-000000000002")
    assert result is None


async def test_nonexistent_token_returns_none(db_pool, experiment_id):
    result = await token_repo.consume_token(db_pool, "INVALID_TOKEN", "cccccccc-0000-0000-0000-000000000003")
    assert result is None


async def test_concurrent_consumption_only_one_succeeds(db_pool, experiment_id):
    """Simulate two workers racing to consume the same token."""
    token = "tok_co_001"

    results = await asyncio.gather(
        token_repo.consume_token(db_pool, token, "dddddddd-0000-0000-0000-000000000001"),
        token_repo.consume_token(db_pool, token, "dddddddd-0000-0000-0000-000000000002"),
    )
    # Exactly one should succeed (return a tuple), one should return None.
    successes = [r for r in results if r is not None]
    failures  = [r for r in results if r is None]
    assert len(successes) == 1
    assert len(failures)  == 1
    assert successes[0] == ("civil_oppose", experiment_id)


async def test_seed_idempotent(db_pool, experiment_id):
    """Re-seeding the same tokens must not raise or duplicate rows."""
    await token_repo.seed_tokens(db_pool, experiment_id, GROUPS)
    rows = await token_repo.list_tokens(db_pool, experiment_id)
    assert len(rows) == 4  # same as after first seed


async def test_reopen_token_only_by_the_session_that_consumed_it(db_pool, experiment_id):
    sid = "aaaaaaaa-0000-0000-0000-000000000001"
    await token_repo.consume_token(db_pool, "tok_cs_001", sid)

    assert await token_repo.reopen_token(db_pool, "tok_cs_001", "bbbbbbbb-0000-0000-0000-000000000002") is False
    assert (await token_repo.get_token_status(db_pool, "tok_cs_001"))["used"] is True

    assert await token_repo.reopen_token(db_pool, "tok_cs_001", sid) is True
    status = await token_repo.get_token_status(db_pool, "tok_cs_001")
    assert status["used"] is False and status["session_id"] is None and status["used_at"] is None

    # Reopened: a second session can consume it; the first can no longer reopen it.
    assert await token_repo.consume_token(db_pool, "tok_cs_001", "bbbbbbbb-0000-0000-0000-000000000002") is not None
    assert await token_repo.reopen_token(db_pool, "tok_cs_001", sid) is False


async def test_reopen_unused_token_is_a_noop(db_pool, experiment_id):
    assert await token_repo.reopen_token(db_pool, "tok_cs_001", "aaaaaaaa-0000-0000-0000-000000000001") is False
