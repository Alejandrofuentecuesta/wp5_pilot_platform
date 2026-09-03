"""Recovery of 'pending' sessions after a worker restart.

/session/start consumes the token and writes a pending row; the WebSocket
then activates it. If the app restarts inside that gap the token is already
burned, so the WebSocket must be able to rebuild the session from the
pending row — otherwise the participant is locked out forever. Stale
pending rows (participant never showed up) are closed out instead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import utils.session_manager as sm_module
from utils.session_manager import SessionManager


SESSION_ID = "11111111-2222-3333-4444-555555555555"


def _pending_row(age_minutes: float = 1):
    return {
        "session_id": SESSION_ID,
        "status": "pending",
        "treatment_group": "civil_support",
        "user_name": "Alba",
        "participant_stance": "favor",
        "experiment_id": "exp",
        "started_at": None,
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    }


def _fake_session_cls():
    instance = MagicMock()
    instance.start = AsyncMock()
    instance.resume = AsyncMock()
    cls = MagicMock(return_value=instance)
    return cls, instance


def _patched(row, session_cls):
    return patch.multiple(
        sm_module,
        SimulationSession=session_cls,
        db_conn=MagicMock(get_pool=MagicMock(return_value="pool")),
        session_repo=MagicMock(
            get_session=AsyncMock(return_value=row),
            end_session=AsyncMock(),
            get_agent_blocks=AsyncMock(return_value={}),
        ),
        message_repo=MagicMock(get_session_messages=AsyncMock(return_value=[])),
        config_repo=MagicMock(
            get_experiment_config=AsyncMock(return_value={"simulation": {}, "experimental": {}})
        ),
        redis_client=MagicMock(
            get_redis=MagicMock(),
            cache_session=AsyncMock(),
            invalidate_session=AsyncMock(),
        ),
    )


@pytest.mark.asyncio
async def test_fresh_pending_row_is_rebuilt_and_started():
    manager = SessionManager()
    session_cls, instance = _fake_session_cls()
    with _patched(_pending_row(age_minutes=1), session_cls):
        session = await manager.get_or_reconstruct(SESSION_ID, AsyncMock())

    assert session is instance
    instance.start.assert_awaited_once()
    instance.resume.assert_not_awaited()
    # Rebuilt with a clean slate: no preloaded messages, no start time.
    kwargs = session_cls.call_args.kwargs
    assert kwargs["_preloaded_messages"] == []
    assert kwargs["_started_at"] is None
    assert kwargs["user_name"] == "Alba"


@pytest.mark.asyncio
async def test_stale_pending_row_is_closed_not_revived():
    manager = SessionManager()
    session_cls, instance = _fake_session_cls()
    with _patched(_pending_row(age_minutes=999), session_cls):
        session = await manager.get_or_reconstruct(SESSION_ID, AsyncMock())
        end_call = sm_module.session_repo.end_session.await_args

    assert session is None
    session_cls.assert_not_called()
    assert end_call.kwargs["reason"] == "no_first_message"


@pytest.mark.asyncio
async def test_ended_row_still_returns_none():
    manager = SessionManager()
    session_cls, _ = _fake_session_cls()
    row = {**_pending_row(), "status": "ended"}
    with _patched(row, session_cls):
        session = await manager.get_or_reconstruct(SESSION_ID, AsyncMock())
    assert session is None
    session_cls.assert_not_called()


@pytest.mark.asyncio
async def test_active_row_is_resumed_with_history():
    manager = SessionManager()
    session_cls, instance = _fake_session_cls()
    row = {
        **_pending_row(),
        "status": "active",
        "started_at": datetime.now(timezone.utc) - timedelta(minutes=2),
        "simulation_config": {"session_duration_minutes": 15},
    }
    with _patched(row, session_cls):
        session = await manager.get_or_reconstruct(SESSION_ID, AsyncMock())

    assert session is instance
    instance.resume.assert_awaited_once()
    instance.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_persisted_pause_credit_keeps_the_session_alive():
    """20 wall-clock minutes on a 15-minute session, but 10 of them were
    disconnected time — the session must resume, not end as expired."""
    manager = SessionManager()
    session_cls, instance = _fake_session_cls()
    row = {
        **_pending_row(),
        "status": "active",
        "started_at": datetime.now(timezone.utc) - timedelta(minutes=20),
        "paused_seconds": 600.0,
        "simulation_config": {"session_duration_minutes": 15},
    }
    with _patched(row, session_cls):
        session = await manager.get_or_reconstruct(SESSION_ID, AsyncMock())

    assert session is instance
    instance.resume.assert_awaited_once()
    # The credit is restored into the rebuilt session's clock.
    assert session_cls.call_args.kwargs["_paused_seconds"] == 600.0


@pytest.mark.asyncio
async def test_failed_start_leaves_no_zombie_in_the_registry():
    """A seed failure used to leave a registered running-but-clockless
    session that held a cap slot forever and blocked the retry."""
    manager = SessionManager()
    session_cls, instance = _fake_session_cls()
    instance.start = AsyncMock(side_effect=OSError("db hiccup during seed"))
    instance.clock_task = None
    with _patched(None, session_cls):
        with pytest.raises(RuntimeError):
            await manager.create_session(
                SESSION_ID,
                AsyncMock(),
                treatment_group="civil_support",
                experiment_id="exp",
            )

    assert await manager.get_session(SESSION_ID) is None
    assert instance.running is False


@pytest.mark.asyncio
async def test_failed_reconstruction_leaves_no_zombie_in_the_registry():
    manager = SessionManager()
    session_cls, instance = _fake_session_cls()
    instance.start = AsyncMock(side_effect=OSError("seed failed"))
    instance.clock_task = None
    with _patched(_pending_row(age_minutes=1), session_cls):
        with pytest.raises(RuntimeError):
            await manager.get_or_reconstruct(SESSION_ID, AsyncMock())

    assert await manager.get_session(SESSION_ID) is None


@pytest.mark.asyncio
async def test_stale_pending_reservations_are_reaped():
    """Reservations older than the rejoin window are dropped from memory
    and their DB rows closed as no_first_message; fresh ones survive."""
    import time as time_module

    manager = SessionManager()
    now = time_module.monotonic()
    manager._pending["stale-id"] = {
        "treatment_group": "g", "_reserved_at": now - 90 * 60,
    }
    manager._pending["fresh-id"] = {
        "treatment_group": "g", "_reserved_at": now - 60,
    }
    session_cls, _ = _fake_session_cls()
    with _patched(_pending_row(), session_cls):
        reaped = await manager.reap_stale_pending()
        end_call = sm_module.session_repo.end_session.await_args

    assert reaped == 1
    assert "stale-id" not in manager._pending
    assert "fresh-id" in manager._pending
    assert end_call.kwargs["session_id"] == "stale-id"
    assert end_call.kwargs["reason"] == "no_first_message"


@pytest.mark.asyncio
async def test_reaper_leaves_already_progressed_rows_alone():
    """If the row moved past 'pending' (e.g. the WebSocket arrived late),
    the reaper drops the memory entry but does not end the session."""
    import time as time_module

    manager = SessionManager()
    manager._pending["stale-id"] = {
        "treatment_group": "g", "_reserved_at": time_module.monotonic() - 90 * 60,
    }
    session_cls, _ = _fake_session_cls()
    active_row = {**_pending_row(), "status": "active"}
    with _patched(active_row, session_cls):
        reaped = await manager.reap_stale_pending()
        assert sm_module.session_repo.end_session.await_args is None

    assert reaped == 1
    assert manager._pending == {}


@pytest.mark.asyncio
async def test_expired_beyond_pause_credit_ends_as_recovery_expiry():
    manager = SessionManager()
    session_cls, _ = _fake_session_cls()
    row = {
        **_pending_row(),
        "status": "active",
        "started_at": datetime.now(timezone.utc) - timedelta(minutes=20),
        "paused_seconds": 60.0,
        "simulation_config": {"session_duration_minutes": 15},
    }
    with _patched(row, session_cls):
        session = await manager.get_or_reconstruct(SESSION_ID, AsyncMock())
        end_call = sm_module.session_repo.end_session.await_args

    assert session is None
    session_cls.assert_not_called()
    assert end_call.kwargs["reason"] == "duration_expired_on_recovery"
