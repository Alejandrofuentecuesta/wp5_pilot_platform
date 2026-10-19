import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import main


@pytest.mark.asyncio
async def test_admin_experiment_compliance_filters_duration_expired():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    # Context manager for pool.acquire()
    class ConnContext:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_pool.acquire.return_value = ConnContext()

    rows = [
        # Session 1: completed with duration_expired
        {
            "session_id": "s1",
            "treatment_group": "group_a",
            "user_name": "Human",
            "participant_stance": "favor",
            "end_reason": "duration_expired",
            "sender": "Bot1",
            "content": "Hello",
            "is_incivil": False,
            "sent_at": "2026-10-19T10:00:00Z",
        },
        # Session 2: ended with user_exit
        {
            "session_id": "s2",
            "treatment_group": "group_a",
            "user_name": "Human",
            "participant_stance": "favor",
            "end_reason": "user_exit",
            "sender": "Bot1",
            "content": "Bye",
            "is_incivil": True,
            "sent_at": "2026-10-19T10:05:00Z",
        },
        # Session 3: group_b completed with duration_expired
        {
            "session_id": "s3",
            "treatment_group": "group_b",
            "user_name": "Human",
            "participant_stance": "favor",
            "end_reason": "duration_expired",
            "sender": "Bot2",
            "content": "Hi",
            "is_incivil": True,
            "sent_at": "2026-10-19T10:10:00Z",
        },
    ]

    mock_conn.fetch = AsyncMock(return_value=rows)

    with patch.object(main, "_require_admin", lambda key: None), \
         patch.object(main, "_get_pool", lambda: mock_pool), \
         patch.object(main.config_repo, "get_experiment", AsyncMock(return_value={"id": "exp1"})), \
         patch.object(main.config_repo, "get_experiment_config", AsyncMock(return_value={})):

        res = await main.admin_experiment_compliance("exp1", x_admin_key="test")

    assert res["experiment_id"] == "exp1"
    assert "groups" in res
    assert "completed_groups" in res

    # All sessions: group_a has 2 sessions, group_b has 1 session
    groups_by_name = {g["group"]: g for g in res["groups"]}
    assert groups_by_name["group_a"]["session_count"] == 2
    assert groups_by_name["group_b"]["session_count"] == 1

    # Completed sessions only (duration_expired): group_a has 1 session (s1), group_b has 1 session (s3)
    completed_by_name = {g["group"]: g for g in res["completed_groups"]}
    assert completed_by_name["group_a"]["session_count"] == 1
    assert completed_by_name["group_a"]["incivil_count"] == 0  # s1 had is_incivil=False
    assert completed_by_name["group_b"]["session_count"] == 1
    assert completed_by_name["group_b"]["incivil_count"] == 1  # s3 had is_incivil=True
