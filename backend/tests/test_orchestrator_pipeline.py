"""Tests for the full Orchestrator pipeline (Director Update → Evaluate → Act → Performer → Moderator).

Uses mock LLM clients to test the orchestration logic without external API calls.
Anonymization helpers are tested separately in test_anonymization.py — these tests
focus on execute_turn() flow, the three-call Director, agent profile accumulation,
retry logic, and action routing.
"""

import json
import random
import pytest
from unittest.mock import AsyncMock, MagicMock

from models.message import Message
from models.agent import Agent
from models.session import SessionState
from agents.STAGE.orchestrator import (
    Orchestrator,
    TurnResult,
    MAX_PERFORMER_RETRIES,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_state(**overrides) -> SessionState:
    defaults = dict(
        session_id="test-session",
        agents=[Agent(name="Alice"), Agent(name="Bob")],
        duration_minutes=30,
        experimental_config={},
        treatment_group="control",
        simulation_config={},
        user_name="participant",
    )
    defaults.update(overrides)
    return SessionState(**defaults)


def _make_logger():
    logger = MagicMock()
    logger.log_error = MagicMock()
    logger.log_llm_call = MagicMock()
    logger.log_event = MagicMock()
    return logger


def _make_orchestrator(
    state=None,
    rng=None,
    agent_traits=None,
):
    """Create an Orchestrator with mock LLM clients."""
    if state is None:
        state = _make_state()

    director_llm = AsyncMock()
    performer_llm = AsyncMock()
    moderator_llm = AsyncMock()
    classifier_llm = AsyncMock()
    classifier_llm.generate_response = AsyncMock(return_value=json.dumps({
        "is_incivil": False,
        "is_like_minded": None,
        "inferred_participant_stance": None,
        "rationale": "ok",
    }))

    logger = _make_logger()

    orch = Orchestrator(
        director_llm=director_llm,
        performer_llm=performer_llm,
        moderator_llm=moderator_llm,
        classifier_llm=classifier_llm,
        state=state,
        logger=logger,
        evaluate_interval=10,
        chatroom_context="A test chatroom",
        ecological_criteria="Informal Reddit-like chat with short messages.",
        agent_traits=agent_traits,
        rng=rng or random.Random(42),
    )
    return orch, logger


def _update_json(profile_update="Active participant with neutral stance."):
    """Build a valid Director Update JSON response."""
    return json.dumps({"performer_profile_update": profile_update})


def _evaluate_json(
    internal="Treatment is on track.",
    ecological="Conversation looks natural.",
):
    """Build a valid Director Evaluate JSON response."""
    return json.dumps({
        "internal_validity_evaluation": internal,
        "ecological_validity_evaluation": ecological,
    })


def _action_json(
    next_performer="Alice",
    action_type="message",
    priority="test priority",
    performer_rationale="test performer rationale",
    action_rationale="test action rationale",
    performer_instruction=None,
    target_user=None,
    target_message_id=None,
):
    """Build a valid Director Action JSON response.

    Note: next_performer/target_user should use anonymized names (Performer N)
    since the Director operates in the anonymized space.
    """
    data = {
        "next_performer": next_performer,
        "action_type": action_type,
        "priority": priority,
        "performer_rationale": performer_rationale,
        "action_rationale": action_rationale,
    }
    if action_type != "like":
        data["performer_instruction"] = performer_instruction or {
            "objective": "Engage the room",
            "motivation": "Wants to contribute",
            "directive": "Keep it short and friendly",
        }
    if target_user:
        data["target_user"] = target_user
    if target_message_id:
        data["target_message_id"] = target_message_id
    return json.dumps(data)


# ── Orchestrator construction ────────────────────────────────────────────────

class TestOrchestratorInit:

    def test_name_map_includes_all(self):
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        assert "Alice" in orch._name_map
        assert "Bob" in orch._name_map
        assert "participant" in orch._name_map
        for v in orch._name_map.values():
            assert v.startswith("Performer ")

    def test_reverse_map(self):
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        for real, anon in orch._name_map.items():
            assert orch._reverse_map[anon] == real

    def test_deterministic_with_seed(self):
        state = _make_state()
        orch1, _ = _make_orchestrator(state=state, rng=random.Random(42))
        orch2, _ = _make_orchestrator(state=state, rng=random.Random(42))
        assert orch1._name_map == orch2._name_map

    def test_agent_profiles_initialized_empty(self):
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        assert len(orch.agent_profiles) == 3  # 2 agents + 1 human
        for profile in orch.agent_profiles.values():
            assert profile == ""

    def test_ecological_criteria_stored(self):
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        assert "Reddit" in orch.ecological_criteria


# ── execute_turn: first turn (skip Update, warm-up Evaluate) ─────────────────

class TestFirstTurn:

    @pytest.mark.asyncio
    async def test_first_turn_skips_update_but_runs_evaluate(self):
        """On the first turn (no messages, no last_agent), Update is skipped.

        Evaluate fires because of warm-up mode (every turn until the first
        full interval completes).
        """
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)

        anon_alice = orch._name_map["Alice"]

        evaluate_resp = _evaluate_json()
        action_resp = _action_json(next_performer=anon_alice, action_type="message")
        orch.director_llm.generate_response = AsyncMock(
            side_effect=[evaluate_resp, action_resp]
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="Hello everyone!")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hello everyone!")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.agent_name == "Alice"
        assert result.message.content == "Hello everyone!"

        # Director LLM called twice (Evaluate + Act; no Update)
        assert orch.director_llm.generate_response.call_count == 2

        # Validity evaluations updated from warm-up Evaluate
        assert orch._internal_validity_summary == "Treatment is on track."
        assert orch._ecological_validity_summary == "Conversation looks natural."


# ── execute_turn: Update + Evaluate + Act (second turn onwards) ──────────────

class TestUpdateEvaluateAndAct:

    @pytest.mark.asyncio
    async def test_all_three_calls_run_on_second_turn(self):
        """After the first turn, Update + Evaluate + Act should all run."""
        state = _make_state()
        state.add_message(Message.create(sender="Alice", content="First message"))

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]

        orch._last_agent = anon_alice
        # Force Evaluate to fire on this turn
        orch._turns_since_evaluate = orch.evaluate_interval - 1

        update_resp = _update_json(profile_update="Alice opened with a friendly greeting.")
        evaluate_resp = _evaluate_json()
        action_resp = _action_json(next_performer=anon_bob, action_type="message")

        orch.director_llm.generate_response = AsyncMock(
            side_effect=[update_resp, evaluate_resp, action_resp]
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="Hey there!")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hey there!")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.agent_name == "Bob"

        # Director called three times (Update + Evaluate + Act)
        assert orch.director_llm.generate_response.call_count == 3

        # Validity evaluations updated
        assert orch._internal_validity_summary == "Treatment is on track."
        assert orch._ecological_validity_summary == "Conversation looks natural."

        # Counter reset after Evaluate fires
        assert orch._turns_since_evaluate == 0

        # Alice's profile updated
        assert orch.agent_profiles[anon_alice] == "Alice opened with a friendly greeting."

    @pytest.mark.asyncio
    async def test_update_failure_does_not_block_evaluate_and_act(self):
        """If Update fails, Evaluate and Act should still proceed."""
        state = _make_state()
        state.add_message(Message.create(sender="Alice", content="Something"))

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        orch._last_agent = anon_alice
        # Force Evaluate to fire on this turn
        orch._turns_since_evaluate = orch.evaluate_interval - 1

        evaluate_resp = _evaluate_json()
        action_resp = _action_json(next_performer=anon_alice, action_type="message")

        orch.director_llm.generate_response = AsyncMock(
            side_effect=["not valid json", evaluate_resp, action_resp]
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="Hi")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hi")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        # Profile unchanged after failed Update
        assert orch.agent_profiles[anon_alice] == ""

    @pytest.mark.asyncio
    async def test_evaluate_failure_does_not_block_act(self):
        """If Evaluate fails, Act should still proceed with previous summaries."""
        state = _make_state()
        state.add_message(Message.create(sender="Alice", content="Something"))

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        orch._last_agent = anon_alice
        orch._internal_validity_summary = "Previous summary"
        # Force Evaluate to fire on this turn
        orch._turns_since_evaluate = orch.evaluate_interval - 1

        update_resp = _update_json()
        action_resp = _action_json(next_performer=anon_alice, action_type="message")

        orch.director_llm.generate_response = AsyncMock(
            side_effect=[update_resp, "not valid json", action_resp]
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="Hi")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hi")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert orch._internal_validity_summary == "Previous summary"

    @pytest.mark.asyncio
    async def test_profile_accumulation_across_turns(self):
        """Agent profiles should accumulate across multiple turns."""
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]

        # --- Turn 1: no Update, warm-up Evaluate + Act ---
        evaluate_resp_1 = _evaluate_json()
        action_resp_1 = _action_json(next_performer=anon_alice, action_type="message")
        orch.director_llm.generate_response = AsyncMock(
            side_effect=[evaluate_resp_1, action_resp_1]
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="Hello!")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hello!")

        result1 = await orch.execute_turn("criteria_A")
        assert result1 is not None
        state.add_message(result1.message)

        assert orch.agent_profiles[anon_alice] == ""

        # --- Turn 2: Update + warm-up Evaluate + Act ---
        update_resp = _update_json(profile_update="Alice greeted the room warmly.")
        evaluate_resp_2 = _evaluate_json()
        action_resp_2 = _action_json(next_performer=anon_bob, action_type="message")

        orch.director_llm.generate_response = AsyncMock(
            side_effect=[update_resp, evaluate_resp_2, action_resp_2]
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="Hey!")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hey!")

        result2 = await orch.execute_turn("criteria_A")
        assert result2 is not None

        assert orch.agent_profiles[anon_alice] == "Alice greeted the room warmly."
        assert orch.agent_profiles[anon_bob] == ""


# ── execute_turn: message action ─────────────────────────────────────────────

class TestExecuteTurnMessage:

    @pytest.mark.asyncio
    async def test_basic_message_action(self):
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(next_performer=anon_alice, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="Hello everyone!")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hello everyone!")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.agent_name == "Alice"
        assert result.message is not None
        assert result.message.sender == "Alice"
        assert result.message.content == "Hello everyone!"


# ── execute_turn: like action ────────────────────────────────────────────────

class TestExecuteTurnLike:

    @pytest.mark.asyncio
    async def test_like_action_no_performer_call(self):
        state = _make_state()
        state.add_message(Message.create(sender="Bob", content="Great point"))
        msg_id = state.messages[0].message_id

        orch, _ = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(
            next_performer=anon_alice,
            action_type="like",
            target_message_id=msg_id,
        )
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "like"
        assert result.agent_name == "Alice"
        assert result.target_message_id == msg_id
        assert result.message is None
        orch.performer_llm.generate_response.assert_not_called()


# ── execute_turn: reply action ───────────────────────────────────────────────

class TestExecuteTurnReply:

    @pytest.mark.asyncio
    async def test_reply_sets_reply_to_and_quoted_text(self):
        state = _make_state()
        state.add_message(Message.create(sender="Bob", content="What do you think?"))
        target_msg = state.messages[0]

        orch, _ = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(
            next_performer=anon_alice,
            action_type="reply",
            target_message_id=target_msg.message_id,
        )
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="I agree!")
        orch.moderator_llm.generate_response = AsyncMock(return_value="I agree!")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "reply"
        assert result.message.reply_to == target_msg.message_id
        assert result.message.quoted_text == "What do you think?"

    @pytest.mark.asyncio
    async def test_reply_strips_quoted_prefix_echoed_by_moderator(self):
        state = _make_state()
        state.add_message(Message.create(sender="Bob", content="What do you think?"))
        target_msg = state.messages[0]

        orch, _ = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(
            next_performer=anon_alice,
            action_type="reply",
            target_message_id=target_msg.message_id,
        )
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="I agree!")
        orch.moderator_llm.generate_response = AsyncMock(
            return_value="What do you think?\nI agree!"
        )

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "reply"
        assert result.message.reply_to == target_msg.message_id
        assert result.message.quoted_text == "What do you think?"
        assert result.message.content == "I agree!"

    @pytest.mark.asyncio
    async def test_reply_retries_when_moderator_output_looks_truncated(self):
        state = _make_state()
        state.add_message(Message.create(sender="Bob", content="What do you think?"))
        target_msg = state.messages[0]

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(
            next_performer=anon_alice,
            action_type="reply",
            target_message_id=target_msg.message_id,
        )
        truncated = (
            "Primera frase completa. Segunda frase completa. "
            "Tercera frase completa y de repente se queda en convivencia"
        ) * 2
        fixed = "Primera frase completa. Segunda frase completa. Tercera frase completa y cierre final."

        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="Texto base del performer")
        orch.moderator_llm.generate_response = AsyncMock(side_effect=[truncated, fixed])

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.message.content == fixed
        assert orch.moderator_llm.generate_response.await_count == 2
        logger.log_error.assert_any_call(
            "moderator_output_truncated",
            "Moderator output appears truncated (attempt 1/3)",
            context={"agent_name": "Alice", "action_type": "reply"},
        )


# ── execute_turn: mention action ─────────────────────────────────────────────

class TestExecuteTurnMention:

    @pytest.mark.asyncio
    async def test_mention_prepends_at_tag(self):
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]

        action_resp = _action_json(
            next_performer=anon_alice,
            action_type="@mention",
            target_user=anon_bob,
        )
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="what do you think?")
        orch.moderator_llm.generate_response = AsyncMock(return_value="what do you think?")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "@mention"
        assert result.target_user == "Bob"
        assert result.message.content.startswith("@Bob")
        assert result.message.mentions == ["Bob"]


class TestPerformerPromptNames:

    @pytest.mark.asyncio
    async def test_performer_sees_real_names_for_agents_and_targets(self):
        state = _make_state(
            agents=[
                Agent(name="Lucia", persona="Lucia, 32, apoya el plan con calma."),
                Agent(name="Pilar", persona="Pilar, 44, se opone con dureza."),
            ]
        )
        state.add_message(Message.create(sender="Pilar", content="Esto es una idea nefasta."))
        target_msg = state.messages[0]

        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={
                "Lucia": {"stance": "agree", "incivility": "civil", "ideology": "left"},
                "Pilar": {"stance": "disagree", "incivility": "uncivil", "ideology": "right"},
            },
        )
        anon_lucia = orch._name_map["Lucia"]
        orch.agent_profiles[anon_lucia] = "Lucia ha defendido a Martin frente a Pilar sin perder la calma."

        captured = {}

        async def _capture_performer(prompt, **kwargs):
            captured["user_prompt"] = prompt
            captured["system_prompt"] = kwargs.get("system_prompt")
            return "Creo que hace falta una respuesta mas sensata."

        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(
                next_performer=anon_lucia,
                action_type="reply",
                target_message_id=target_msg.message_id,
            )
        )
        orch.performer_llm.generate_response = AsyncMock(side_effect=_capture_performer)
        orch.moderator_llm.generate_response = AsyncMock(return_value="Creo que hace falta una respuesta mas sensata.")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert "Your name in this chatroom is **Lucia**" in captured["system_prompt"]
        assert "The human participant's name is **participant**" in captured["system_prompt"]
        assert "Pilar: Esto es una idea nefasta." in captured["user_prompt"]
        assert "Lucia ha defendido a Martin frente a Pilar sin perder la calma." in captured["user_prompt"]
        assert "Performer " not in captured["user_prompt"]


class TestSameSideGuard:

    @pytest.mark.asyncio
    async def test_reply_to_same_side_agent_becomes_room_message(self):
        state = _make_state()
        state.add_message(Message.create(sender="Bob", content="We should push this policy harder."))
        target_msg = state.messages[0]

        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"stance": "agree"},
                "Bob": {"stance": "agree"},
            },
        )
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(
            next_performer=anon_alice,
            action_type="reply",
            target_message_id=target_msg.message_id,
        )
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="Exactly, we need to make that case clearly.")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Exactly, we need to make that case clearly.")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.target_message_id is None
        assert result.target_user is None
        assert result.message.reply_to is None
        assert result.message.quoted_text is None
        logger.log_error.assert_any_call(
            "director_same_side_target",
            "Director targeted same-side agents 'Alice' -> 'Bob'; converting to a non-targeted message",
        )

    @pytest.mark.asyncio
    async def test_mention_to_same_side_agent_becomes_room_message(self):
        state = _make_state()
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"stance": "disagree"},
                "Bob": {"stance": "disagree"},
            },
        )
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]

        action_resp = _action_json(
            next_performer=anon_alice,
            action_type="@mention",
            target_user=anon_bob,
        )
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="The bigger issue is whether the plan even works.")
        orch.moderator_llm.generate_response = AsyncMock(return_value="The bigger issue is whether the plan even works.")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.target_user is None
        assert result.message.mentions is None
        assert not result.message.content.startswith("@Bob")
        logger.log_error.assert_any_call(
            "director_same_side_target",
            "Director targeted same-side agents 'Alice' -> 'Bob'; converting to a non-targeted message",
        )


# ── execute_turn: wait (yield to participant) ────────────────────────────────

class TestExecuteTurnWait:
    """Director selects the human participant → turn short-circuits as 'wait'.

    The Director is blind to who is human — it just picks a performer.
    The orchestrator detects that the chosen performer is the participant
    and converts this into a wait (skip Performer/Moderator).
    """

    @pytest.mark.asyncio
    async def test_selecting_participant_returns_wait(self):
        """Director selects participant's anonymous name → treated as wait."""
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)

        anon_user = orch._name_map[state.user_name]
        action_resp = _action_json(next_performer=anon_user, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.action_type == "wait"
        assert result.agent_name == "participant"
        assert result.message is None
        # Performer/Moderator should NOT have been called.
        orch.performer_llm.generate_response.assert_not_called()
        orch.moderator_llm.generate_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_does_not_advance_evaluate_counter(self):
        """Wait turns should not count toward the evaluate cadence."""
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)

        anon_user = orch._name_map[state.user_name]
        action_resp = _action_json(next_performer=anon_user, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        counter_before = orch._turns_since_evaluate
        await orch.execute_turn("criteria_A")
        assert orch._turns_since_evaluate == counter_before

    @pytest.mark.asyncio
    async def test_wait_does_not_update_last_agent(self):
        """Wait turns should not change _last_agent tracking."""
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)

        anon_user = orch._name_map[state.user_name]
        action_resp = _action_json(next_performer=anon_user, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        last_agent_before = orch._last_agent
        await orch.execute_turn("criteria_A")
        assert orch._last_agent == last_agent_before


# ── execute_turn: error handling ─────────────────────────────────────────────

class TestExecuteTurnErrors:

    @pytest.mark.asyncio
    async def test_director_action_exception_returns_none(self):
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        orch.director_llm.generate_response = AsyncMock(side_effect=RuntimeError("API error"))

        result = await orch.execute_turn("criteria_A")
        assert result is None
        logger.log_error.assert_called()

    @pytest.mark.asyncio
    async def test_director_action_returns_none_response(self):
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        orch.director_llm.generate_response = AsyncMock(return_value=None)

        result = await orch.execute_turn("criteria_A")
        assert result is None

    @pytest.mark.asyncio
    async def test_director_action_returns_invalid_json(self):
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        orch.director_llm.generate_response = AsyncMock(return_value="not valid json at all")

        result = await orch.execute_turn("criteria_A")
        assert result is None
        logger.log_error.assert_called()

    @pytest.mark.asyncio
    async def test_no_agents_returns_wait(self):
        """With no agents, only the participant is available — Director must yield."""
        state = _make_state(agents=[])
        orch, logger = _make_orchestrator(state=state)
        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer="Performer 1")
        )

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.action_type == "wait"

    @pytest.mark.asyncio
    async def test_unknown_agent_falls_back(self):
        """Director picks a name not in agents list → falls back to random valid agent."""
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)

        action_resp = _action_json(next_performer="UnknownAgent", action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="Hi")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hi")

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.agent_name in ("Alice", "Bob")
        logger.log_error.assert_called()


# ── Performer retry logic ────────────────────────────────────────────────────

class TestPerformerRetry:

    @pytest.mark.asyncio
    async def test_performer_retries_on_failure(self):
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(next_performer=anon_alice, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        orch.performer_llm.generate_response = AsyncMock(
            side_effect=[None, None, "Third time's the charm"]
        )
        orch.moderator_llm.generate_response = AsyncMock(return_value="Third time's the charm")

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.message.content == "Third time's the charm"
        assert orch.performer_llm.generate_response.call_count == 3

    @pytest.mark.asyncio
    async def test_performer_retries_exhausted(self):
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(next_performer=anon_alice, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        orch.performer_llm.generate_response = AsyncMock(return_value=None)
        orch.moderator_llm.generate_response = AsyncMock(return_value=None)

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.action_type == "wait"
        assert result.agent_name == "Alice"
        assert orch.performer_llm.generate_response.call_count == MAX_PERFORMER_RETRIES

    @pytest.mark.asyncio
    async def test_moderator_no_content_triggers_retry(self):
        """Moderator returns NO_CONTENT → triggers performer retry."""
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(next_performer=anon_alice, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        orch.performer_llm.generate_response = AsyncMock(
            side_effect=["bad output", "good output"]
        )
        orch.moderator_llm.generate_response = AsyncMock(
            side_effect=["NO_CONTENT", "Cleaned output"]
        )

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.message.content == "Cleaned output"


# ── Deanonymization in output ────────────────────────────────────────────────

class TestOutputDeanonymization:

    @pytest.mark.asyncio
    async def test_content_deanonymized(self):
        """Anonymous labels in performer output should be replaced with real names."""
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]

        action_resp = _action_json(next_performer=anon_alice, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        performer_output = f"I agree with {anon_bob}!"
        orch.performer_llm.generate_response = AsyncMock(return_value=performer_output)
        orch.moderator_llm.generate_response = AsyncMock(return_value=performer_output)

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert "Bob" in result.message.content
        assert anon_bob not in result.message.content


# ── TurnResult dataclass ────────────────────────────────────────────────────

class TestTurnResult:

    def test_message_action_result(self):
        msg = Message.create(sender="Alice", content="Hello")
        result = TurnResult(
            action_type="message",
            agent_name="Alice",
            message=msg,
            priority="Greet the room",
            performer_rationale="Alice is friendly",
            action_rationale="Opening message needed",
        )
        assert result.action_type == "message"
        assert result.agent_name == "Alice"
        assert result.message is msg
        assert result.priority == "Greet the room"
        assert result.target_message_id is None
        assert result.target_user is None

    def test_like_action_result(self):
        result = TurnResult(
            action_type="like",
            agent_name="Bob",
            target_message_id="msg-123",
        )
        assert result.action_type == "like"
        assert result.message is None
        assert result.target_message_id == "msg-123"

    def test_defaults(self):
        result = TurnResult(action_type="message", agent_name="Alice")
        assert result.message is None
        assert result.target_message_id is None
        assert result.target_user is None
        assert result.priority is None
        assert result.performer_rationale is None
        assert result.action_rationale is None
