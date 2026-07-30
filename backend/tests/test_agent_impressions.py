"""Tests for the optional post-session agent impression survey."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import main


SESSION_ID = "68e45b42-0905-4233-8f07-054d1110864d"


def _ended_session():
    return {
        "experiment_id": "final",
        "status": "ended",
        "end_reason": "duration_expired",
        "user_name": "Laia",
    }


def _messages():
    return [
        {"sender": "[news]", "msg_type": "news_article"},
        {"sender": "Laia"},
        {"sender": "Candela"},
        {"sender": "Diego"},
    ]


@pytest.mark.asyncio
async def test_submit_agent_impressions_persists_selected_agents(monkeypatch):
    insert_event = AsyncMock()
    monkeypatch.setattr(main, "_get_pool", lambda: object())
    monkeypatch.setattr(main.session_repo, "get_session", AsyncMock(return_value=_ended_session()))
    monkeypatch.setattr(main.message_repo, "get_session_messages", AsyncMock(return_value=_messages()))
    monkeypatch.setattr(main.event_repo, "get_session_events", AsyncMock(return_value=[]))
    monkeypatch.setattr(main.event_repo, "insert_event_strict", insert_event)

    response = await main.submit_agent_impressions(
        SESSION_ID,
        main.AgentImpressionsRequest(
            ratings=[
                main.AgentImpressionRequest(
                    agent_name=" Candela ",
                    rating=5,
                    comment=" Me cayó muy bien. ",
                ),
            ],
        ),
    )

    assert response.status_code == 204
    call = insert_event.await_args.kwargs
    assert call["event_type"] == "agent_impressions"
    assert call["data"]["ratings"] == [
        {
            "agent_name": "Candela",
            "rating": 5,
            "comment": "Me cayó muy bien.",
        },
    ]
    assert call["data"]["skipped"] is False


@pytest.mark.asyncio
async def test_submit_agent_impressions_can_skip(monkeypatch):
    insert_event = AsyncMock()
    monkeypatch.setattr(main, "_get_pool", lambda: object())
    monkeypatch.setattr(main.session_repo, "get_session", AsyncMock(return_value=_ended_session()))
    monkeypatch.setattr(main.message_repo, "get_session_messages", AsyncMock(return_value=_messages()))
    monkeypatch.setattr(main.event_repo, "get_session_events", AsyncMock(return_value=[]))
    monkeypatch.setattr(main.event_repo, "insert_event_strict", insert_event)

    response = await main.submit_agent_impressions(
        SESSION_ID,
        main.AgentImpressionsRequest(ratings=[]),
    )

    assert response.status_code == 204
    assert insert_event.await_args.kwargs["data"]["skipped"] is True


@pytest.mark.asyncio
async def test_submit_agent_impressions_rejects_unseen_agent(monkeypatch):
    monkeypatch.setattr(main, "_get_pool", lambda: object())
    monkeypatch.setattr(main.session_repo, "get_session", AsyncMock(return_value=_ended_session()))
    monkeypatch.setattr(main.message_repo, "get_session_messages", AsyncMock(return_value=_messages()))

    with pytest.raises(HTTPException) as exc:
        await main.submit_agent_impressions(
            SESSION_ID,
            main.AgentImpressionsRequest(
                ratings=[
                    main.AgentImpressionRequest(
                        agent_name="No apareció",
                        rating=3,
                    ),
                ],
            ),
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_submit_agent_impressions_only_after_full_session(monkeypatch):
    active = {**_ended_session(), "status": "active", "end_reason": None}
    monkeypatch.setattr(main, "_get_pool", lambda: object())
    monkeypatch.setattr(main.session_repo, "get_session", AsyncMock(return_value=active))
    monkeypatch.setattr(main.event_repo, "get_session_events", AsyncMock(return_value=[]))

    with pytest.raises(HTTPException) as exc:
        await main.submit_agent_impressions(
            SESSION_ID,
            main.AgentImpressionsRequest(ratings=[]),
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_participant_cannot_report_own_message(monkeypatch):
    own_message = MagicMock(sender="Laia", message_id="own-message")
    session = SimpleNamespace(
        state=SimpleNamespace(user_name="Laia", messages=[own_message]),
    )
    monkeypatch.setattr(
        main.session_manager,
        "get_session",
        AsyncMock(return_value=session),
    )

    with pytest.raises(HTTPException) as exc:
        await main.report_message(
            SESSION_ID,
            "own-message",
            main.ReportRequest(user="participant", block=False),
        )

    assert exc.value.status_code == 400
    own_message.toggle_report.assert_not_called()
