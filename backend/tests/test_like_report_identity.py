"""Likes, reports, and blocks carry the server-stamped participant identity.

The client-supplied `user` field is legacy and ignored: it could otherwise
forge agent likes or act under arbitrary names. Reporting is one-way — a
reported message cannot be un-reported by calling the endpoint again.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from models import Message
from models.session import SessionState


SESSION_ID = "11111111-2222-3333-4444-555555555555"


def _fake_session():
    state = SessionState(session_id=SESSION_ID, agents=[], user_name="Alba")
    agent_message = Message.create(sender="Lucía", content="hola")
    state.add_message(agent_message)
    session = SimpleNamespace(
        state=state,
        logger=MagicMock(),
        experiment_id="exp",
        replace_blocked_agent=AsyncMock(return_value="Marina"),
    )
    return session, agent_message


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def _patched(session):
    return patch.multiple(
        main,
        session_manager=MagicMock(get_session=AsyncMock(return_value=session)),
        _get_pool=MagicMock(side_effect=RuntimeError("no pool in tests")),
    )


class TestLikeIdentity:
    def test_like_is_stamped_as_participant_even_with_forged_user(self, client):
        session, message = _fake_session()
        with _patched(session):
            response = client.post(
                f"/session/{SESSION_ID}/message/{message.message_id}/like",
                json={"user": "Lucía"},
            )
        assert response.status_code == 200
        assert message.liked_by == {"participant"}

    def test_like_works_without_user_field(self, client):
        session, message = _fake_session()
        with _patched(session):
            response = client.post(
                f"/session/{SESSION_ID}/message/{message.message_id}/like",
                json={},
            )
        assert response.status_code == 200
        assert message.liked_by == {"participant"}


class TestReportOneWay:
    def test_report_sets_the_flag(self, client):
        session, message = _fake_session()
        with _patched(session):
            response = client.post(
                f"/session/{SESSION_ID}/message/{message.message_id}/report",
                json={},
            )
        assert response.status_code == 200
        assert message.reported is True

    def test_second_report_does_not_unreport(self, client):
        session, message = _fake_session()
        with _patched(session):
            for _ in range(2):
                response = client.post(
                    f"/session/{SESSION_ID}/message/{message.message_id}/report",
                    json={},
                )
        assert response.status_code == 200
        assert message.reported is True
        assert response.json()["message"]["reported"] is True

    def test_block_is_recorded_as_participant(self, client):
        session, message = _fake_session()
        with _patched(session):
            response = client.post(
                f"/session/{SESSION_ID}/message/{message.message_id}/report",
                json={"user": "Diego", "block": True},
            )
        assert response.status_code == 200
        assert "Lucía" in session.state.blocked_agents
        session.replace_blocked_agent.assert_awaited_once_with("Lucía")
        # The forged actor name never reaches the block log.
        block_events = [
            call.args for call in session.logger.log_event.call_args_list
            if call.args and call.args[0] == "user_block"
        ]
        assert block_events and block_events[0][1]["by"] == "participant"
