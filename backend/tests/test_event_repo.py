"""Tests for event_repo — append-only event logging.

Requires a live PostgreSQL instance (like other DB tests).
Skips gracefully when PostgreSQL is unavailable.
"""

import json
import pytest
import pytest_asyncio

from db.repositories import event_repo

TEST_SESSION_ID = "00000000-0000-0000-0000-000000000001"
NONEXISTENT_SESSION_ID = "00000000-0000-0000-0000-000000000002"
ANOTHER_NONEXISTENT_ID = "00000000-0000-0000-0000-000000000003"


# ── Setup ────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="session")
async def seed_experiment(db_pool):
    """Ensure an experiment row exists for FK constraints."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO experiments(experiment_id, config) VALUES($1, $2::jsonb) ON CONFLICT DO NOTHING",
            "evt_test_exp",
            json.dumps({"simulation": {}, "experimental": {}}),
        )
    yield
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM experiments WHERE experiment_id = 'evt_test_exp'")


@pytest_asyncio.fixture(loop_scope="session")
async def seed_session(db_pool, seed_experiment):
    """Insert a session row for FK constraints."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tokens(token, experiment_id, treatment_group) VALUES($1, $2, $3) ON CONFLICT DO NOTHING",
            "token123",
            "evt_test_exp",
            "control",
        )
        await conn.execute(
            """INSERT INTO sessions(session_id, experiment_id, token, treatment_group, user_name)
               VALUES($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING""",
            TEST_SESSION_ID,
            "evt_test_exp",
            "token123",
            "control",
            "participant",
        )
    yield
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM events WHERE session_id = $1", TEST_SESSION_ID)
        await conn.execute("DELETE FROM sessions WHERE session_id = $1", TEST_SESSION_ID)
        await conn.execute("DELETE FROM tokens WHERE token = 'token123'")


# ── insert_event ─────────────────────────────────────────────────────────────

class TestInsertEvent:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_insert_basic_event(self, db_pool, seed_session):
        await event_repo.insert_event(
            db_pool,
            session_id=TEST_SESSION_ID,
            experiment_id="evt_test_exp",
            event_type="test_event",
            data={"key": "value"},
        )
        # Verify it was inserted
        events = await event_repo.get_session_events(db_pool, TEST_SESSION_ID)
        assert any(e["event_type"] == "test_event" for e in events)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_insert_multiple_events(self, db_pool, seed_session):
        for i in range(3):
            await event_repo.insert_event(
                db_pool,
                session_id=TEST_SESSION_ID,
                experiment_id="evt_test_exp",
                event_type=f"multi_event_{i}",
                data={"index": i},
            )
        events = await event_repo.get_session_events(db_pool, TEST_SESSION_ID)
        multi = [e for e in events if e["event_type"].startswith("multi_event_")]
        assert len(multi) >= 3

    @pytest.mark.asyncio(loop_scope="session")
    async def test_insert_swallows_exceptions(self, db_pool, seed_session):
        """insert_event should never raise, even with bad data."""
        # Use a nonexistent session_id to violate FK constraint
        # This should print to stderr but not raise
        await event_repo.insert_event(
            db_pool,
            session_id=NONEXISTENT_SESSION_ID,
            experiment_id="evt_test_exp",
            event_type="bad_event",
            data={"should": "fail silently"},
        )
        # If we get here, the exception was swallowed


# ── get_session_events ───────────────────────────────────────────────────────

class TestGetSessionEvents:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_returns_ordered_events(self, db_pool, seed_session):
        # Insert events with known types
        for etype in ["alpha", "beta", "gamma"]:
            await event_repo.insert_event(
                db_pool,
                session_id=TEST_SESSION_ID,
                experiment_id="evt_test_exp",
                event_type=etype,
                data={},
            )
        events = await event_repo.get_session_events(db_pool, TEST_SESSION_ID)
        # Should be ordered by occurred_at
        timestamps = [e["occurred_at"] for e in events]
        assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_filter_by_event_type(self, db_pool, seed_session):
        await event_repo.insert_event(
            db_pool,
            session_id=TEST_SESSION_ID,
            experiment_id="evt_test_exp",
            event_type="filter_target",
            data={"found": True},
        )
        await event_repo.insert_event(
            db_pool,
            session_id=TEST_SESSION_ID,
            experiment_id="evt_test_exp",
            event_type="other_type",
            data={"found": False},
        )

        filtered = await event_repo.get_session_events(
            db_pool, TEST_SESSION_ID, event_types=["filter_target"]
        )
        assert all(e["event_type"] == "filter_target" for e in filtered)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_empty_session_returns_empty(self, db_pool, seed_session):
        events = await event_repo.get_session_events(db_pool, ANOTHER_NONEXISTENT_ID)
        assert events == []

    @pytest.mark.asyncio(loop_scope="session")
    async def test_event_data_is_dict(self, db_pool, seed_session):
        await event_repo.insert_event(
            db_pool,
            session_id=TEST_SESSION_ID,
            experiment_id="evt_test_exp",
            event_type="dict_check",
            data={"nested": {"key": "value"}, "list": [1, 2, 3]},
        )
        events = await event_repo.get_session_events(
            db_pool, TEST_SESSION_ID, event_types=["dict_check"]
        )
        assert len(events) >= 1
        data = events[-1]["data"]
        assert isinstance(data, dict)
        assert data["nested"]["key"] == "value"
