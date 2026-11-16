"""Personal data: a privacy pause instead of ending the session, and no stored copy.

When the participant safety classifier finds personal data in a participant
message, the session goes on: the participant is paused and reminded, and the
text is kept out of the database. What must hold:

- self-harm and severe distress still end the session as before;
- the privacy pause is the same participant pause as the idle reminder: it
  freezes the countdown and the silence clock, credits the frozen time back
  exactly once, is lifted only by the participant's button (not by a
  reconnect, an idle resume or a new message), is shown again on rejoin, and
  ends as ``privacy_timeout`` (r=2) after the rejoin window;
- the filter is registered before the classifier call itself is logged, and
  every later write of the session (events, messages, safety flags) goes
  through it; the room and the agents' context are not changed;
- the copies written before the verdict are erased, even if the session ended
  meanwhile, and the end-of-session check writes nothing when none remain.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.STAGE.orchestrator import TurnResult
from models.message import Message
from platforms.chatroom import REJOIN_WINDOW_MINUTES, build_return_url
from platforms.safety_screen import SafetyScreen
from utils.logger import Logger
from utils.personal_data_filter import PERSONAL_DATA_PLACEHOLDER, PersonalDataFilter
from utils.safety import SafetyVerdict
from tests.test_agent_manager import _make_agent_manager
from tests.test_chatroom import _create_session, _patch_externals

SECRET = "Me llamo Ana García Pérez y vivo en la calle Mayor 3"


def _verdict(category, should_stop=True, rationale="explicación"):
    return json.dumps({
        "should_stop": should_stop,
        "category": category,
        "confidence": "high",
        "rationale": rationale,
    })


def _session_config(ws):
    return [
        c.args[0] for c in ws.call_args_list
        if c.args[0].get("event_type") == "session_config"
    ][-1]


def _running_session():
    session, _ = _create_session()
    session.running = True
    session._first_user_message_received = True
    return session


# ── The classifier's verdict ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_personal_data_pauses_and_erases_instead_of_ending():
    with _patch_externals(), \
         patch("platforms.chatroom.redaction_repo") as repo:
        repo.erase_personal_data = AsyncMock(return_value={"message": 1})
        session = _running_session()
        session.classifier_llm.generate_response = AsyncMock(return_value=_verdict("personal_data"))
        session._trigger_safety_intervention = AsyncMock()
        message = Message.create(sender=session.state.user_name, content=SECRET)

        await session._run_participant_safety_check(message, [message])

        session._trigger_safety_intervention.assert_not_awaited()
        assert session.running is True
        assert session._pause_trigger == "privacy"
        assert session.frozen is True
        assert session._personal_data_filter.texts == [SECRET]
        kwargs = repo.erase_personal_data.await_args.kwargs
        assert kwargs["message_id"] == message.message_id
        assert kwargs["since"] < message.timestamp
        assert kwargs["data_filter"] is session._personal_data_filter
        # The room is unchanged: the message keeps its text in memory.
        assert message.content == SECRET


@pytest.mark.asyncio
async def test_filter_is_registered_before_the_classifier_call_is_logged():
    with _patch_externals(), \
         patch("platforms.chatroom.redaction_repo") as repo:
        repo.erase_personal_data = AsyncMock(return_value={})
        session = _running_session()
        session.classifier_llm.generate_response = AsyncMock(
            return_value=_verdict("personal_data", rationale=f"Nombre completo: {SECRET}")
        )
        seen = {}

        def capture(**kwargs):
            seen["active"] = session._personal_data_filter.active
            seen["response"] = kwargs["response"]

        session.logger.log_llm_call = MagicMock(side_effect=capture)
        message = Message.create(sender=session.state.user_name, content=SECRET)

        await session._run_participant_safety_check(message, [message])

        assert seen["active"] is True
        logged = json.loads(seen["response"])
        assert "rationale" not in logged
        assert logged["category"] == "personal_data"


@pytest.mark.asyncio
async def test_self_harm_still_ends_the_session_and_registers_nothing():
    with _patch_externals():
        session = _running_session()
        session.classifier_llm.generate_response = AsyncMock(return_value=_verdict("self_harm"))
        session._trigger_safety_intervention = AsyncMock()
        message = Message.create(sender=session.state.user_name, content="No puedo más")

        await session._run_participant_safety_check(message, [message])

        session._trigger_safety_intervention.assert_awaited_once()
        assert session._personal_data_filter.active is False
        assert session._pause_trigger is None


@pytest.mark.asyncio
async def test_a_synthetic_participant_is_neither_paused_nor_erased_nor_ended():
    with _patch_externals(), \
         patch("platforms.chatroom.redaction_repo") as repo:
        repo.erase_personal_data = AsyncMock()
        session = _running_session()
        # A copy: the shared test config must not change for later tests.
        session.simulation_config = {**session.simulation_config, "synthetic_participant": True}
        session.classifier_llm.generate_response = AsyncMock(return_value=_verdict("personal_data"))
        session._trigger_safety_intervention = AsyncMock()
        message = Message.create(sender=session.state.user_name, content=SECRET)

        await session._run_participant_safety_check(message, [message])

        session._trigger_safety_intervention.assert_not_awaited()
        repo.erase_personal_data.assert_not_awaited()
        assert session._pause_trigger is None
        assert session._personal_data_filter.active is False


@pytest.mark.asyncio
async def test_a_verdict_after_the_session_ended_still_erases_but_does_not_pause():
    with _patch_externals(), \
         patch("platforms.chatroom.redaction_repo") as repo:
        repo.erase_personal_data = AsyncMock(return_value={})
        session = _running_session()
        session.running = False
        session.classifier_llm.generate_response = AsyncMock(return_value=_verdict("personal_data"))
        message = Message.create(sender=session.state.user_name, content=SECRET)

        await session._run_participant_safety_check(message, [message])

        repo.erase_personal_data.assert_awaited_once()
        assert session._pause_trigger is None


@pytest.mark.asyncio
async def test_a_failed_erasure_is_logged_and_the_pause_stands():
    with _patch_externals(), \
         patch("platforms.chatroom.redaction_repo") as repo:
        repo.erase_personal_data = AsyncMock(side_effect=RuntimeError("db down"))
        session = _running_session()
        session.logger.log_error = MagicMock()
        session.classifier_llm.generate_response = AsyncMock(return_value=_verdict("personal_data"))
        message = Message.create(sender=session.state.user_name, content=SECRET)

        await session._run_participant_safety_check(message, [message])

        assert session._pause_trigger == "privacy"
        session.logger.log_error.assert_any_call("personal_data_erasure", "db down")


# ── The pause and the clocks ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_privacy_pause_freezes_and_tells_the_client():
    with _patch_externals() as mocks:
        session = _running_session()

        await session.pause_for_privacy()

        assert session.frozen is True
        assert session._pause_trigger == "privacy"
        event = mocks["redis"].publish_event.await_args.args[2]
        assert event["event_type"] == "session_paused"
        assert event["trigger"] == "privacy"


@pytest.mark.asyncio
async def test_privacy_pause_stops_the_silence_clock():
    with _patch_externals():
        session = _running_session()
        assert session._silence_clock_runs() is True

        await session.pause_for_privacy()

        assert session._silence_clock_runs() is False


@pytest.mark.asyncio
async def test_resume_credits_the_frozen_time_once_and_persists_it():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session = _running_session()

        await session.pause_for_privacy()
        # Thirty seconds pass behind the reminder.
        session._pause_started_monotonic -= 30
        session._frozen_since -= 30
        await session.resume_from_privacy()
        await session.resume_from_privacy()  # a repeated click changes nothing

        assert session.frozen is False
        assert session.state.paused_seconds == pytest.approx(30, abs=0.5)
        mocks["session_repo"].add_paused_seconds.assert_awaited_once()
        credited = mocks["session_repo"].add_paused_seconds.await_args.args[2]
        assert credited == pytest.approx(30, abs=0.5)


@pytest.mark.asyncio
async def test_only_the_privacy_button_lifts_a_privacy_pause():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session = _running_session()

        await session.pause_for_privacy()
        stamp = session._pause_started_monotonic
        await session.resume_from_idle()
        ws = AsyncMock()
        await session.attach_websocket(ws)
        await session.handle_user_message("sigo aquí")
        await asyncio.gather(*session._safety_tasks, *session._participant_screen_tasks)

        assert session._pause_trigger == "privacy"
        assert session._pause_started_monotonic == stamp
        mocks["session_repo"].add_paused_seconds.assert_not_awaited()
        # A reloaded page shows the reminder again.
        assert _session_config(ws)["privacy_paused"] is True
        assert _session_config(ws)["idle_paused"] is False


@pytest.mark.asyncio
async def test_a_disconnect_pause_becomes_a_privacy_pause_and_keeps_its_start():
    with _patch_externals() as mocks:
        mocks["session_repo"].add_paused_seconds = AsyncMock()
        session = _running_session()

        session.pause_for_disconnect()
        stamp = session._pause_started_monotonic
        await session.pause_for_privacy()
        await session.attach_websocket(AsyncMock())

        assert session._pause_trigger == "privacy"
        assert session._pause_started_monotonic == stamp
        mocks["session_repo"].add_paused_seconds.assert_not_awaited()


@pytest.mark.asyncio
async def test_privacy_pause_ends_as_privacy_timeout_after_the_rejoin_window():
    with _patch_externals():
        session = _running_session()

        await session.pause_for_privacy()
        session._pause_started_monotonic -= REJOIN_WINDOW_MINUTES * 60 + 1
        session._publish_session_end = AsyncMock()
        session.stop = AsyncMock()
        session._guarded_turn = AsyncMock()

        with patch("platforms.chatroom.asyncio.sleep", new=AsyncMock()):
            await session._clock_loop()

        session.stop.assert_awaited_once_with(reason="privacy_timeout")
        session._publish_session_end.assert_awaited_once_with("privacy_timeout")
        session._guarded_turn.assert_not_awaited()


def test_privacy_timeout_returns_r2():
    url = build_return_url("https://panel.example/return", "tok", "privacy_timeout")
    assert url.endswith("r=2")


# ── Writes after the verdict ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_later_participant_writes_go_through_the_filter():
    with _patch_externals() as mocks:
        session = _running_session()
        flagged = Message.create(sender=session.state.user_name, content=SECRET)
        session.state.add_message(flagged)
        session._personal_data_filter.add(SECRET)

        await session.handle_user_message(SECRET + " otra vez", reply_to=flagged.message_id)
        await asyncio.gather(*session._safety_tasks, *session._participant_screen_tasks)

        kwargs = mocks["message_repo"].insert_message.await_args.kwargs
        assert "García" not in kwargs["content"]
        assert kwargs["quoted_text"] == PERSONAL_DATA_PLACEHOLDER
        # What the room shows is unchanged.
        assert session.state.messages[-1].content == SECRET + " otra vez"


@pytest.mark.asyncio
async def test_logger_applies_the_filter_when_the_row_is_written():
    data_filter = PersonalDataFilter()
    logger = Logger("sess", "exp")
    logger.redact = data_filter.apply
    with patch("db.repositories.event_repo.insert_event", new=AsyncMock()) as insert, \
         patch("db.connection.get_pool", return_value=MagicMock()):
        logger.log_event("llm_call", {"prompt": f"Chat: {SECRET}"})
        data_filter.add(SECRET)  # registered after queueing, before the write runs
        await logger.drain()

    assert insert.await_args.kwargs["data"] == {"prompt": f"Chat: {PERSONAL_DATA_PLACEHOLDER}"}


@pytest.mark.asyncio
async def test_agent_messages_are_stored_through_the_filter():
    am = _make_agent_manager()
    am.persist_filter = PersonalDataFilter()
    am.persist_filter.add(SECRET)
    msg = Message.create(sender="Alice", content="Respuesta", quoted_text=SECRET)
    result = TurnResult(action_type="message", agent_name="Alice", message=msg)
    with patch("agents.agent_manager.db_conn") as db, \
         patch("agents.agent_manager.redis_client") as redis, \
         patch("agents.agent_manager.message_repo") as repo:
        db.get_pool.return_value = MagicMock()
        repo.insert_message = AsyncMock()
        redis.get_redis.return_value = MagicMock()
        redis.push_to_window = AsyncMock()
        redis.publish_event = AsyncMock()
        await am._handle_message(result)

    kwargs = repo.insert_message.await_args.kwargs
    assert kwargs["quoted_text"] == PERSONAL_DATA_PLACEHOLDER
    assert kwargs["content"] == "Respuesta"
    assert msg.quoted_text == SECRET  # the room keeps the quote


@pytest.mark.asyncio
async def test_safety_flags_are_stored_through_the_filter():
    class Client:
        async def classify(self, policy, excerpt):
            return SafetyVerdict(status="unsafe", categories=["S7"], raw=f"quote: {SECRET}")

    screen = SafetyScreen(
        session_id="sess", experiment_id="exp", logger=MagicMock(),
        client=Client(), enabled=True, user_name="participante",
    )
    screen.persist_filter = PersonalDataFilter()
    screen.persist_filter.add(SECRET)
    message = Message.create(sender="participante", content=SECRET)
    with patch("platforms.safety_screen.db_conn") as db, \
         patch("platforms.safety_screen.safety_repo") as repo:
        db.get_pool.return_value = MagicMock()
        repo.insert_flag = AsyncMock()
        repo.set_message_safety_verdict = AsyncMock()
        repo.set_flag_seq = AsyncMock()
        await screen.screen_participant(message, SimpleNamespace(messages=[message], user_name="participante"))

    kwargs = repo.insert_flag.await_args.kwargs
    assert kwargs["content"] == PERSONAL_DATA_PLACEHOLDER
    assert "García" not in (kwargs["raw_output"] or "")
    assert "García" not in kwargs["context_user_turn"]


def test_the_session_wires_one_filter_into_every_write_path():
    with _patch_externals():
        session, _ = _create_session()
        data_filter = session._personal_data_filter
        assert session.agent_manager.persist_filter is data_filter
        assert session.safety_screen.persist_filter is data_filter
        assert session.logger.redact == data_filter.apply


# ── End of session ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_final_check_does_nothing_without_a_flag():
    with _patch_externals(), patch("platforms.chatroom.redaction_repo") as repo:
        repo.count_personal_data_copies = AsyncMock()
        session = _running_session()

        await session._final_personal_data_check()

        repo.count_personal_data_copies.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_check_writes_nothing_when_no_copy_remains():
    with _patch_externals(), patch("platforms.chatroom.redaction_repo") as repo:
        repo.count_personal_data_copies = AsyncMock(
            return_value={"messages": 0, "safety_flags": 0, "events": 0}
        )
        repo.erase_personal_data = AsyncMock()
        session = _running_session()
        session.logger.log_event = MagicMock()
        message = Message.create(sender=session.state.user_name, content=SECRET)
        session._personal_data_filter.add(SECRET)
        session._personal_data_since = message.timestamp

        await session._final_personal_data_check()

        repo.erase_personal_data.assert_not_awaited()
        session.logger.log_event.assert_not_called()


@pytest.mark.asyncio
async def test_final_check_erases_and_logs_a_remaining_copy():
    with _patch_externals(), patch("platforms.chatroom.redaction_repo") as repo:
        repo.count_personal_data_copies = AsyncMock(
            return_value={"messages": 1, "safety_flags": 0, "events": 0}
        )
        repo.erase_personal_data = AsyncMock(return_value={"messages": 1})
        session = _running_session()
        session.logger.log_event = MagicMock()
        message = Message.create(sender=session.state.user_name, content=SECRET)
        session._personal_data_filter.add(SECRET)
        session._personal_data_since = message.timestamp

        await session._final_personal_data_check()

        repo.erase_personal_data.assert_awaited_once()
        assert "message_id" not in repo.erase_personal_data.await_args.kwargs
        session.logger.log_event.assert_called_once_with(
            "personal_data_redaction_anomaly", {"rows_changed": {"messages": 1}}
        )


@pytest.mark.asyncio
async def test_stop_runs_the_final_check():
    with _patch_externals():
        session = _running_session()
        session._final_personal_data_check = AsyncMock()

        await session.stop(reason="duration_expired")

        session._final_personal_data_check.assert_awaited_once()
