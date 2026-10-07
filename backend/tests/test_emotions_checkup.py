"""Tests for the emotions check-up endpoint (mid-session and final check-ups)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import main


SESSION_ID = "68e45b42-0905-4233-8f07-054d1110864d"


def _payload(is_final: bool) -> main.EmotionsCheckupRequest:
    return main.EmotionsCheckupRequest(
        emotions=[main.EmotionRatingRequest(emotion="Enfado", intensity=3)],
        emotion_explanation=" Me molestó un comentario. ",
        is_short=not is_final,
        is_final=is_final,
    )


def _patch_db(monkeypatch, insert_event):
    monkeypatch.setattr(main, "_get_pool", lambda: object())
    monkeypatch.setattr(
        main.session_repo,
        "get_session",
        AsyncMock(return_value={"experiment_id": "final", "status": "active"}),
    )
    monkeypatch.setattr(main.event_repo, "insert_event", insert_event)


@pytest.mark.asyncio
async def test_checkup_for_live_session_goes_to_the_session(monkeypatch):
    insert_event = AsyncMock()
    _patch_db(monkeypatch, insert_event)
    live_session = MagicMock()
    live_session.handle_emotions_checkup_response = AsyncMock()
    # SessionManager.get_session is a coroutine function, so the stub must be too.
    monkeypatch.setattr(main.session_manager, "get_session", AsyncMock(return_value=live_session))

    await main.submit_emotions_checkup_api(SESSION_ID, _payload(is_final=False))

    data = live_session.handle_emotions_checkup_response.await_args.args[0]
    assert data["emotions"] == [{"emotion": "Enfado", "intensity": 3}]
    assert data["emotion_explanation"] == "Me molestó un comentario."
    assert data["is_short"] is True
    assert data["is_final"] is False
    insert_event.assert_not_called()


@pytest.mark.asyncio
async def test_final_checkup_after_session_ended_is_stored_directly(monkeypatch):
    insert_event = AsyncMock()
    _patch_db(monkeypatch, insert_event)
    monkeypatch.setattr(main.session_manager, "get_session", AsyncMock(return_value=None))

    await main.submit_emotions_checkup_api(SESSION_ID, _payload(is_final=True))

    call = insert_event.await_args.kwargs
    assert call["event_type"] == "emotions_checkup_response"
    assert call["experiment_id"] == "final"
    assert call["data"]["is_final"] is True
