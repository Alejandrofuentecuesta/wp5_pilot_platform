"""Tests for the post-session agent rating endpoint."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import main


@pytest.mark.asyncio
async def test_submit_agent_ratings_persists_normalized_event(monkeypatch):
    pool = object()
    insert_event = AsyncMock()
    monkeypatch.setattr(main, "_get_pool", lambda: pool)
    monkeypatch.setattr(
        main.session_repo,
        "get_session",
        AsyncMock(return_value={"experiment_id": "final"}),
    )
    monkeypatch.setattr(
        main.event_repo,
        "get_session_events",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(main.event_repo, "insert_event_strict", insert_event)

    response = await main.submit_agent_ratings(
        "68e45b42-0905-4233-8f07-054d1110864d",
        main.AgentRatingsRequest(
            ratings=[
                main.AgentRatingRequest(agent_name=" Candela ", rating=5),
                main.AgentRatingRequest(agent_name="Diego", no_opinion=True),
            ],
        ),
    )

    assert response.status_code == 204
    insert_event.assert_awaited_once()
    call = insert_event.await_args.kwargs
    assert call["event_type"] == "agent_ratings"
    assert call["data"]["ratings"] == [
        {"agent_name": "Candela", "rating": 5, "no_opinion": False},
        {"agent_name": "Diego", "rating": None, "no_opinion": True},
    ]


@pytest.mark.asyncio
async def test_submit_agent_ratings_is_idempotent(monkeypatch):
    insert_event = AsyncMock()
    monkeypatch.setattr(main, "_get_pool", lambda: object())
    monkeypatch.setattr(
        main.session_repo,
        "get_session",
        AsyncMock(return_value={"experiment_id": "final"}),
    )
    monkeypatch.setattr(
        main.event_repo,
        "get_session_events",
        AsyncMock(return_value=[{"event_type": "agent_ratings"}]),
    )
    monkeypatch.setattr(main.event_repo, "insert_event_strict", insert_event)

    response = await main.submit_agent_ratings(
        "68e45b42-0905-4233-8f07-054d1110864d",
        main.AgentRatingsRequest(
            ratings=[main.AgentRatingRequest(agent_name="Candela", rating=4)],
        ),
    )

    assert response.status_code == 204
    insert_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_agent_ratings_rejects_duplicate_names(monkeypatch):
    monkeypatch.setattr(main, "_get_pool", lambda: object())

    with pytest.raises(HTTPException) as exc:
        await main.submit_agent_ratings(
            "68e45b42-0905-4233-8f07-054d1110864d",
            main.AgentRatingsRequest(
                ratings=[
                    main.AgentRatingRequest(agent_name="Candela", rating=4),
                    main.AgentRatingRequest(agent_name=" Candela ", rating=2),
                ],
            ),
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rating",
    [
        main.AgentRatingRequest(agent_name="Candela"),
        main.AgentRatingRequest(agent_name="Candela", rating=3, no_opinion=True),
    ],
)
async def test_submit_agent_ratings_requires_one_response_kind(monkeypatch, rating):
    monkeypatch.setattr(main, "_get_pool", lambda: object())

    with pytest.raises(HTTPException) as exc:
        await main.submit_agent_ratings(
            "68e45b42-0905-4233-8f07-054d1110864d",
            main.AgentRatingsRequest(ratings=[rating]),
        )

    assert exc.value.status_code == 422
