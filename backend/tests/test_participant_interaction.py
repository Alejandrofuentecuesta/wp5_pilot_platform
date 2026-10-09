import pytest
from unittest.mock import AsyncMock

from models.message import Message
from utils.participant_message import is_valid_participant_message
from tests.test_orchestrator_pipeline import _make_state, _make_orchestrator, _action_json
from tests.test_chatroom import _patch_externals, _create_session


@pytest.mark.parametrize("content", ["", " ", "a", "?", "!!!", "a!", "\U0001f600"])
def test_rejects_single_letter_or_symbol_only(content):
    assert not is_valid_participant_message(content)


@pytest.mark.parametrize("content", ["hola", "s\u00ed", "no", "OK", "No estoy de acuerdo", "\u4f60\u597d"])
def test_accepts_short_meaningful_messages(content):
    assert is_valid_participant_message(content)


@pytest.mark.asyncio
async def test_invalid_input_does_not_start_or_persist_session():
    with _patch_externals() as mocks:
        session, _ = _create_session()
        session.running = True
        await session.handle_user_message("!")
        assert session.state.messages == []
        assert not getattr(session, "_first_user_message_received", False)
        mocks["message_repo"].insert_message.assert_not_called()


@pytest.mark.asyncio
async def test_greeting_receives_early_reply_and_guidance():
    state = _make_state()
    greeting = Message.create(sender="participant", content="hola")
    state.add_message(greeting)
    orch, _ = _make_orchestrator(state=state)
    orch.director_llm.generate_response = AsyncMock(return_value=_action_json())
    orch.performer_llm.generate_response = AsyncMock(
        return_value="Hola, yo creo que la vivienda es lo que deberiamos discutir. Tu que opinas?"
    )
    result = await orch.execute_turn("criteria_A")
    assert result.message is not None
    assert result.message.metadata["participant_response_to"] == greeting.message_id
    prompt = orch.performer_llm.generate_response.call_args.args[0]
    assert "only a greeting" in prompt
    assert "not the person" in prompt


def test_answered_participant_does_not_trigger_another_forced_reply():
    state = _make_state()
    message = Message.create(sender="participant", content="hola")
    state.add_message(message)
    state.add_message(Message.create(sender="Alice", content="Hola", reply_to=message.message_id))
    orch, _ = _make_orchestrator(state=state)
    assert orch._unanswered_participant_message() is None


def test_immediate_plain_response_is_not_repeated():
    state = _make_state()
    message = Message.create(sender="participant", content="hola")
    state.add_message(message)
    answer = Message.create(sender="Alice", content="Hola, que opinas?")
    answer.metadata["participant_response_to"] = message.message_id
    state.add_message(answer)
    orch, _ = _make_orchestrator(state=state)
    assert orch._unanswered_participant_message() is None


def test_early_response_window_expires_after_two_messages():
    state = _make_state()
    state.add_message(Message.create(sender="participant", content="hola"))
    state.add_message(Message.create(sender="Alice", content="Una opinion"))
    state.add_message(Message.create(sender="Bob", content="Otra opinion"))
    orch, _ = _make_orchestrator(state=state)
    assert orch._unanswered_participant_message() is None
