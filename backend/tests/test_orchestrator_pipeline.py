"""Tests for the full Orchestrator pipeline (Director Update â†’ Evaluate â†’ Act â†’ Performer â†’ Moderator).

Uses mock LLM clients to test the orchestration logic without external API calls.
Anonymization helpers are tested separately in test_anonymization.py â€” these tests
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
    TARGET_ELIGIBLE_SPEAKER_COUNT,
    anonymize_message,
)


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    Note: next_performer/target_user should use the exact stable labels visible
    to the Director for this session.
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


# â”€â”€ Orchestrator construction â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestOrchestratorInit:

    def test_name_map_includes_all(self):
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        assert "Alice" in orch._name_map
        assert "Bob" in orch._name_map
        assert "participant" in orch._name_map
        assert orch._name_map["Alice"] == "Alice"
        assert orch._name_map["Bob"] == "Bob"
        assert orch._name_map["participant"] == "participant"

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

    def test_first_participant_message_can_refine_alignment_cell(self):
        state = _make_state(participant_stance_hint="against")
        state.add_message(Message.create(
            sender="participant",
            content="La inmigracion es un derecho pero este plan esta mal planteado",
        ))
        orch, _ = _make_orchestrator(state=state)
        assert orch._participant_alignment_cell_live() == "anti_policy_pro_topic"

    def test_unclear_first_participant_message_keeps_self_report_cell(self):
        state = _make_state(participant_stance_hint="against")
        state.add_message(Message.create(
            sender="participant",
            content="No se, tengo dudas todavia",
        ))
        orch, _ = _make_orchestrator(state=state)
        assert orch._participant_alignment_cell_live() == "anti_policy_anti_topic"

    def test_treatment_fidelity_summary_includes_alignment_cell_counts(self):
        state = _make_state()
        state.add_message(Message.create(sender="Alice", content="m1"))
        state.add_message(Message.create(sender="Bob", content="m2"))
        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "pro_policy_pro_topic"},
                "Bob": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )

        summary = orch._format_treatment_fidelity_summary()
        assert "Messages by alignment cell so far:" in summary
        assert "pro_policy_pro_topic=1/2" in summary
        assert "anti_policy_anti_topic=1/2" in summary

    @pytest.mark.asyncio
    async def test_director_evaluate_prompt_includes_global_speaker_memory(self):
        state = _make_state()
        state.add_message(Message.create(sender="Alice", content="m1"))
        orch, logger = _make_orchestrator(state=state)
        orch.director_llm.generate_response = AsyncMock(return_value=_evaluate_json())

        await orch._director_evaluate("LIKEMINDED_TARGET = 80", [])

        evaluate_prompt = next(
            kwargs["prompt"]
            for _, kwargs in logger.log_llm_call.call_args_list
            if kwargs.get("agent_name") == "__director_evaluate__"
        )
        assert "Global speaker memory:" in evaluate_prompt
        assert "spoken=yes, messages=1, last_spoke=latest agent message" in evaluate_prompt
        assert "spoken=no, messages=0, last_spoke=never" in evaluate_prompt

    @pytest.mark.asyncio
    async def test_director_action_prompt_includes_global_and_eligible_speaker_memory(self):
        state = _make_state()
        state.add_message(Message.create(sender="Alice", content="m1"))
        state.add_message(Message.create(sender="Bob", content="m2"))
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "pro_policy_pro_topic"},
                "Bob": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]
        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )

        await orch._director_action(
            anon_recent=[],
            override_profiles={anon_alice: "", orch._anon_user: ""},
            override_perf_counts={anon_alice: 1, orch._anon_user: 0},
        )

        action_prompt = next(
            kwargs["prompt"]
            for _, kwargs in logger.log_llm_call.call_args_list
            if kwargs.get("agent_name") == "__director_action__"
        )
        assert "Global speaker memory:" in action_prompt
        assert f"- {anon_alice}: spoken=yes, messages=1, last_spoke=1 agent message ago" in action_prompt
        assert f"- {anon_bob}: spoken=yes, messages=1, last_spoke=latest agent message" in action_prompt
        assert "Eligible speakers this turn:" in action_prompt
        eligible_section = action_prompt.split("Eligible speakers this turn:", 1)[1]
        assert f"- {anon_alice}: spoken=yes, messages=1, last_spoke=1 agent message ago" in eligible_section
        assert f"- {anon_bob}:" not in eligible_section
        assert "Target constraints by speaker:" in action_prompt
        assert f"- {anon_alice}: valid direct agent targets={anon_bob};" in action_prompt
        assert "participant target=allowed;" in action_prompt
        assert f"best recent anchor={anon_bob} [{state.messages[-1].message_id}]" in action_prompt

    @pytest.mark.asyncio
    async def test_director_action_allows_noneligible_but_valid_target_user(self):
        state = _make_state()
        state.add_message(Message.create(sender="Bob", content="m1"))
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "pro_policy_pro_topic"},
                "Bob": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]
        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(
                next_performer=anon_alice,
                action_type="@mention",
                target_user=anon_bob,
            )
        )

        action = await orch._director_action(
            anon_recent=[],
            override_profiles={anon_alice: "", orch._anon_user: ""},
            override_perf_counts={anon_alice: 0, orch._anon_user: 0},
        )

        assert action is not None
        assert action["next_performer"] == anon_alice
        assert action["target_user"] == anon_bob
        assert not any(
            call.args and call.args[0] == "director_action_unknown_target_label"
            for call in logger.log_error.call_args_list
        )

    def test_candidate_filter_prioritizes_like_minded_when_like_target_is_behind(self):
        state = _make_state(
            participant_stance_hint="qualified_against",
            agents=[Agent(name="Alice"), Agent(name="Bob"), Agent(name="Carol"), Agent(name="Dora"), Agent(name="Eve")],
        )
        state.add_message(Message.create(sender="Bob", content="x", is_incivil=True))
        state.add_message(Message.create(sender="Carol", content="y", is_incivil=False))
        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "anti_policy_pro_topic", "incivility": "civil"},
                "Bob": {"alignment_cell": "pro_policy_pro_topic", "incivility": "uncivil"},
                "Carol": {"alignment_cell": "anti_policy_anti_topic", "incivility": "civil"},
                "Dora": {"alignment_cell": "anti_policy_pro_topic", "incivility": "uncivil"},
                "Eve": {"alignment_cell": "pro_policy_pro_topic", "incivility": "civil"},
            },
        )
        filtered = orch._filter_candidate_agents_for_targets(
            "LIKEMINDED_TARGET = 80\nNOT_LIKEMINDED_TARGET = 20\nINCIVILITY_TARGET = 50",
            {"Alice", "Bob", "Carol", "Dora", "Eve"},
        )
        assert len(filtered) == TARGET_ELIGIBLE_SPEAKER_COUNT
        assert "Alice" in filtered
        assert "Dora" in filtered

    def test_candidate_filter_intersects_alignment_and_uncivility_targets(self):
        state = _make_state(
            participant_stance_hint="qualified_against",
            agents=[Agent(name="Alice"), Agent(name="Bob"), Agent(name="Carol"), Agent(name="Dora"), Agent(name="Eve")],
        )
        state.add_message(Message.create(sender="Bob", content="x", is_incivil=False))
        state.add_message(Message.create(sender="Carol", content="y", is_incivil=False))
        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "anti_policy_pro_topic", "incivility": "uncivil"},
                "Bob": {"alignment_cell": "pro_policy_pro_topic", "incivility": "civil"},
                "Carol": {"alignment_cell": "anti_policy_anti_topic", "incivility": "civil"},
                "Dora": {"alignment_cell": "anti_policy_pro_topic", "incivility": "civil"},
                "Eve": {"alignment_cell": "pro_policy_pro_topic", "incivility": "uncivil"},
            },
        )
        filtered = orch._filter_candidate_agents_for_targets(
            "LIKEMINDED_TARGET = 80\nNOT_LIKEMINDED_TARGET = 20\nINCIVILITY_TARGET = 80",
            {"Alice", "Bob", "Carol", "Dora", "Eve"},
        )
        assert len(filtered) == TARGET_ELIGIBLE_SPEAKER_COUNT
        assert "Alice" in filtered
        assert "Dora" in filtered

    def test_sanitize_summary_for_eligible_agents_rewrites_noneligible_names(self):
        state = _make_state(agents=[Agent(name="Alice"), Agent(name="Bob"), Agent(name="Carol")])
        orch, _ = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]
        anon_carol = orch._name_map["Carol"]
        sanitized = orch._sanitize_summary_for_eligible_agents(
            f"Alignment is close; introduce {anon_bob} and {anon_carol} soon to rebalance.",
            {anon_alice, orch._anon_user},
        )
        assert anon_bob not in sanitized
        assert anon_carol not in sanitized
        assert "eligible agent" in sanitized

    def test_same_cell_guard_does_not_trigger_for_same_ideology_different_cells(self):
        state = _make_state(
            agents=[Agent(name="Alice"), Agent(name="Bob")],
        )
        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "pro_policy_pro_topic", "ideology": "left"},
                "Bob": {"alignment_cell": "anti_policy_pro_topic", "ideology": "left"},
            },
        )
        assert orch._agents_share_alignment_cell("Alice", "Bob") is False
        assert orch._agents_have_different_alignment_cells("Alice", "Bob") is True

    def test_validation_detector_catches_explicit_agreement_language(self):
        assert Orchestrator._looks_like_agent_validation("Totalmente de acuerdo contigo.") is True
        assert Orchestrator._looks_like_agent_validation("Exacto, eso mismo digo yo.") is True
        assert Orchestrator._looks_like_agent_validation("No, eso no funciona.") is False


# â”€â”€ execute_turn: first turn (skip Update, warm-up Evaluate) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ execute_turn: Update + Evaluate + Act (second turn onwards) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ execute_turn: message action â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    @pytest.mark.asyncio
    async def test_cross_cell_validation_reply_retries_and_rewrites(self):
        state = _make_state(agents=[Agent(name="Alice"), Agent(name="Bob")])
        target = Message.create(sender="Bob", content="Esto es una farsa total.")
        state.add_message(target)
        state.add_message(Message.create(sender="Alice", content="Dummy message from Alice"))
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "anti_policy_pro_topic"},
                "Bob": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )
        anon_alice = orch._name_map["Alice"]

        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(
                next_performer=anon_alice,
                action_type="reply",
                target_message_id=target.message_id,
            )
        )
        orch.performer_llm.generate_response = AsyncMock(
            side_effect=[
                "Totalmente de acuerdo contigo.",
                "No, eso no arregla nada y lo planteas desde otro marco.",
            ]
        )
        orch.moderator_llm.generate_response = AsyncMock(
            side_effect=[
                "Totalmente de acuerdo contigo.",
                "No, eso no arregla nada y lo planteas desde otro marco.",
            ]
        )

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.message is not None
        assert result.message.content == "No, eso no arregla nada y lo planteas desde otro marco."
        assert orch.performer_llm.generate_response.call_count == 2
        logger.log_error.assert_any_call(
            "performer_cross_cell_validation_retry",
            "Generated message for 'Alice' validated 'Bob' across alignment cells; retrying",
            context={"action_type": "reply"},
        )

    @pytest.mark.asyncio
    async def test_like_minded_reply_to_participant_retries_if_it_turns_against_them(self):
        state = _make_state(
            participant_stance_hint="qualified_against",
            agents=[Agent(name="Alice"), Agent(name="Bob")],
        )
        participant_msg = Message.create(
            sender="participant",
            content="Esto ayuda a empresarios y deja tirados a los migrantes",
        )
        state.add_message(participant_msg)
        state.add_message(Message.create(sender="Alice", content="Dummy message from Alice"))
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "anti_policy_pro_topic"},
                "Bob": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )
        anon_alice = orch._name_map["Alice"]

        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(
                next_performer=anon_alice,
                action_type="reply",
                target_message_id=participant_msg.message_id,
            )
        )
        orch.performer_llm.generate_response = AsyncMock(
            side_effect=[
                "Martin, deja de decir estupideces, no todo es racismo.",
                "Lo de fondo que dices es verdad: esto deja demasiada mano al empresario y no protege bien a la gente migrante.",
            ]
        )
        orch.moderator_llm.generate_response = AsyncMock(
            side_effect=[
                "Martin, deja de decir estupideces, no todo es racismo.",
                "Lo de fondo que dices es verdad: esto deja demasiada mano al empresario y no protege bien a la gente migrante.",
            ]
        )

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.message is not None
        assert result.message.reply_to == participant_msg.message_id
        assert result.message.content == (
            "Lo de fondo que dices es verdad: esto deja demasiada mano al empresario y no protege bien a la gente migrante."
        )
        assert orch.performer_llm.generate_response.call_count == 2
        logger.log_error.assert_any_call(
            "performer_like_minded_participant_attack_retry",
            "Generated message for 'Alice' attacked same-cell participant 'participant'; retrying",
            context={"action_type": "reply"},
        )


# â”€â”€ execute_turn: like action â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    @pytest.mark.asyncio
    async def test_auto_like_does_not_validate_cross_cell_agent(self):
        state = _make_state(
            participant_stance_hint="qualified_against",
            agents=[Agent(name="Alice"), Agent(name="Bob"), Agent(name="Carol")],
        )
        cross_cell_msg = Message.create(sender="Carol", content="Coincido plenamente")
        same_cell_msg = Message.create(sender="Bob", content="No arregla el problema de fondo")
        state.add_message(cross_cell_msg)
        state.add_message(same_cell_msg)
        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "anti_policy_pro_topic"},
                "Bob": {"alignment_cell": "anti_policy_pro_topic"},
                "Carol": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )
        orch.auto_like_probability = 1.0

        result = orch._try_auto_like({"Alice"}, random.Random(0))

        assert result is not None
        assert result.action_type == "like"
        assert result.target_message_id == same_cell_msg.message_id


# â”€â”€ execute_turn: reply action â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestExecuteTurnReply:

    @pytest.mark.asyncio
    async def test_reply_sets_reply_to_and_quoted_text(self):
        state = _make_state()
        state.add_message(Message.create(sender="Bob", content="What do you think?"))
        target_msg = state.messages[0]
        state.add_message(Message.create(sender="Charlie", content="Dummy message to prevent downgrade"))

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
        state.add_message(Message.create(sender="Charlie", content="Dummy message to prevent downgrade"))

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
        state.add_message(Message.create(sender="Charlie", content="Dummy message to prevent downgrade"))

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
        orch.performer_llm.generate_response = AsyncMock(return_value="mensaje: Texto base del performer")
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


# â”€â”€ execute_turn: mention action â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestExecuteTurnMention:

    @pytest.mark.asyncio
    async def test_mention_prepends_at_tag(self):
        state = _make_state()
        state.add_message(Message.create(sender="Bob", content="Hello"))
        state.add_message(Message.create(sender="Alice", content="Hi Bob"))
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
        assert "Recent Messages From Other People In The Room" in captured["user_prompt"]
        assert "- Pilar: Esto es una idea nefasta." in captured["user_prompt"]
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
            "Director targeted same-cell agents 'Alice' -> 'Bob'; converting to a non-targeted message",
        )

    @pytest.mark.asyncio
    async def test_same_side_target_redirects_to_valid_reply_when_available(self):
        state = _make_state(agents=[Agent(name="Alice"), Agent(name="Bob"), Agent(name="Carol")])
        state.add_message(Message.create(sender="Bob", content="Aliado same-cell"))
        state.add_message(Message.create(sender="participant", content="Yo lo apoyo"))
        participant_msg = state.messages[-1]
        state.add_message(Message.create(sender="Bob", content="Dummy message from Bob"))

        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "pro_policy_pro_topic"},
                "Bob": {"alignment_cell": "pro_policy_pro_topic"},
                "Carol": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(
            next_performer=anon_alice,
            action_type="reply",
            target_message_id=state.messages[0].message_id,
        )
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="Yo tambien lo apoyo.")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Yo tambien lo apoyo.")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "reply"
        assert result.target_message_id == participant_msg.message_id
        assert result.message.reply_to == participant_msg.message_id
        logger.log_error.assert_any_call(
            "director_same_side_target",
            "Director targeted same-cell agents 'Alice' -> 'Bob'; redirecting to reply to 'participant'",
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
            "Director targeted same-cell agents 'Alice' -> 'Bob'; converting to a non-targeted message",
        )


# â”€â”€ execute_turn: wait (yield to participant) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TestExecuteTurnWait:
    """Director selects the human participant â†’ turn short-circuits as 'wait'.

    The Director is blind to who is human â€” it just picks a performer.
    The orchestrator detects that the chosen performer is the participant
    and converts this into a wait (skip Performer/Moderator).
    """

    @pytest.mark.asyncio
    async def test_selecting_participant_returns_wait(self):
        """Director selects participant's anonymous name â†’ treated as wait."""
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


class TestConsecutiveSpeakerLimit:

    @pytest.mark.asyncio
    async def test_third_consecutive_speaking_turn_becomes_wait(self):
        state = _make_state()
        state.add_message(Message.create(sender="Alice", content="Primera"))
        state.add_message(Message.create(sender="Alice", content="Segunda"))

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )

        result = await orch.execute_turn("criteria_A")

        assert result is None
        orch.performer_llm.generate_response.assert_not_called()
        orch.moderator_llm.generate_response.assert_not_called()
        logger.log_error.assert_any_call(
            "director_action_unknown_performer_label",
            "attempt 1/3: Director returned next_performer 'Alice', which is not one of the visible performer labels in AGENT_PROFILES",
        )


class TestRoomWideOpeners:

    @pytest.mark.asyncio
    async def test_first_room_wide_opener_for_agent_is_allowed(self):
        state = _make_state()
        state.add_message(Message.create(sender="participant", content="Arrancamos el debate"))

        orch, _ = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="Pues a mi me parece fatal.")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Pues a mi me parece fatal.")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.message.reply_to is None

    @pytest.mark.asyncio
    async def test_message_to_latest_valid_speaker_is_allowed_without_redirect(self):
        state = _make_state()
        first_opener = Message.create(sender="Bob", content="Esto es un desastre")
        participant_msg = Message.create(sender="participant", content="Yo no lo veo igual")
        state.add_message(first_opener)
        state.add_message(participant_msg)

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="Y ademas nos lo venden fatal.")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Y ademas nos lo venden fatal.")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.message.reply_to is None
        assert not any(
            call.args[0] == "director_room_wide_opener_redirected"
            for call in logger.log_error.call_args_list
        )

    @pytest.mark.asyncio
    async def test_true_room_wide_opener_still_redirects_when_no_latest_valid_anchor(self):
        state = _make_state()
        participant_msg = Message.create(sender="participant", content="Explica eso")
        ally_msg = Message.create(sender="Bob", content="Estoy de acuerdo contigo")
        state.add_message(participant_msg)
        state.add_message(ally_msg)

        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "pro_policy_pro_topic"},
                "Bob": {"alignment_cell": "pro_policy_pro_topic"},
            },
        )
        anon_alice = orch._name_map["Alice"]
        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )
        orch.performer_llm.generate_response = AsyncMock(return_value="No compro ese cuento.")
        orch.moderator_llm.generate_response = AsyncMock(return_value="No compro ese cuento.")

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "reply"
        assert result.message.reply_to == participant_msg.message_id
        logger.log_error.assert_any_call(
            "director_room_wide_opener_redirected",
            "Redirected room-wide opener for 'Alice' to reply to 'participant'",
        )


class TestFixedStanceGuard:

    def test_expected_like_minded_requires_same_alignment_cell(self):
        state = _make_state(participant_stance_hint="qualified_against")
        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {
                    "alignment_cell": "anti_policy_pro_topic",
                    "ideology": "left",
                },
                "Bob": {
                    "alignment_cell": "anti_policy_anti_topic",
                    "ideology": "right",
                },
            },
        )

        assert orch._expected_like_minded_for_agent("Alice") is True
        assert orch._expected_like_minded_for_agent("Bob") is False

    def test_treatment_fidelity_summary_reports_structural_alignment(self):
        state = _make_state(
            participant_stance_hint="qualified_against",
            agents=[Agent(name="Alice"), Agent(name="Bob")],
        )
        state.add_message(Message.create(sender="Alice", content="No me convence", is_incivil=False))
        state.add_message(Message.create(sender="Bob", content="Es una locura", is_incivil=True))
        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "anti_policy_pro_topic"},
                "Bob": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )

        summary = orch._format_treatment_fidelity_summary()
        assert "Like-minded messages so far: 1/2 (50%)" in summary
        assert "Not-like-minded messages so far: 1/2 (50%)" in summary
        assert "Incivil messages so far: 1/2 (50%)" in summary
        assert "Civil messages so far: 1/2 (50%)" in summary

    def test_detects_direct_attack_language_on_participant(self):
        assert Orchestrator._looks_like_attack_on_participant("Martin, deja de decir estupideces.") is True
        assert Orchestrator._looks_like_attack_on_participant(
            "Lo de fondo que dices es verdad y habría que ir más lejos."
        ) is False

    @pytest.mark.asyncio
    async def legacy_mismatched_fixed_stance_retries_once_and_keeps_second_draft(self):
        state = _make_state(participant_stance_hint="against")
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={"Alice": {"stance": "disagree"}},
        )
        anon_alice = orch._name_map["Alice"]

        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )
        orch.performer_llm.generate_response = AsyncMock(
            side_effect=[
                "Este plan es necesario y justo.",
                "Este plan es una vergÃ¼enza total.",
            ]
        )
        orch.moderator_llm.generate_response = AsyncMock(
            side_effect=[
                "Este plan es necesario y justo.",
                "Este plan es una vergÃ¼enza total.",
            ]
        )
        orch.classifier_llm.generate_response = AsyncMock(
            side_effect=[
                json.dumps({
                    "is_incivil": False,
                    "is_like_minded": False,
                    "stance_confidence": "high",
                    "inferred_participant_stance": "against",
                    "rationale": "Mismatch",
                }),
                json.dumps({
                    "is_incivil": True,
                    "is_like_minded": True,
                    "stance_confidence": "high",
                    "inferred_participant_stance": "against",
                    "rationale": "Aligned",
                }),
                json.dumps({
                    "is_incivil": True,
                    "is_like_minded": True,
                    "stance_confidence": "high",
                    "inferred_participant_stance": "against",
                    "rationale": "Aligned",
                }),
            ]
        )

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.message.content == "Este plan es una vergÃ¼enza total."
        assert result.message.is_like_minded is True
        assert orch.performer_llm.generate_response.call_count == 2
        logger.log_error.assert_any_call(
            "performer_stance_mismatch_retry",
            "Generated message contradicted fixed stance for 'Alice'; retrying once",
            context={"expected_like_minded": True, "actual_like_minded": False, "action_type": "message"},
        )

    @pytest.mark.asyncio
    async def test_classifier_runs_once_on_final_message(self):
        state = _make_state(participant_stance_hint="against")
        orch, _ = _make_orchestrator(
            state=state,
            agent_traits={"Alice": {"stance": "disagree"}},
        )
        anon_alice = orch._name_map["Alice"]

        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )
        orch.performer_llm.generate_response = AsyncMock(
            return_value="Este plan es una vergÃ¼enza total."
        )
        orch.moderator_llm.generate_response = AsyncMock(
            return_value="Este plan es una vergÃ¼enza total."
        )
        orch.classifier_llm.generate_response = AsyncMock(
            return_value=json.dumps({
                "is_incivil": True,
                "is_like_minded": True,
                "stance_confidence": "high",
                "inferred_participant_stance": "against",
                "rationale": "Aligned",
            })
        )

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.message is not None
        assert result.message.content == "Este plan es una vergÃ¼enza total."
        assert orch.classifier_llm.generate_response.call_count == 1

    @pytest.mark.asyncio
    async def legacy_repeated_fixed_stance_mismatch_becomes_wait(self):
        state = _make_state(participant_stance_hint="against")
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={"Alice": {"stance": "disagree"}},
        )
        anon_alice = orch._name_map["Alice"]

        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )
        orch.performer_llm.generate_response = AsyncMock(
            side_effect=[
                "Este plan es necesario y justo.",
                "Es lo unico sensato que puede hacer el Govern.",
            ]
        )
        orch.moderator_llm.generate_response = AsyncMock(
            side_effect=[
                "Este plan es necesario y justo.",
                "Es lo unico sensato que puede hacer el Govern.",
            ]
        )
        orch.classifier_llm.generate_response = AsyncMock(
            side_effect=[
                json.dumps({
                    "is_incivil": False,
                    "is_like_minded": False,
                    "stance_confidence": "high",
                    "inferred_participant_stance": "against",
                    "rationale": "Mismatch",
                }),
                json.dumps({
                    "is_incivil": False,
                    "is_like_minded": False,
                    "stance_confidence": "high",
                    "inferred_participant_stance": "against",
                    "rationale": "Mismatch again",
                }),
            ]
        )

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "wait"
        assert result.message is None
        assert orch.performer_llm.generate_response.call_count == 2
        logger.log_error.assert_any_call(
            "performer_stance_mismatch_exhausted",
            "Generated message for 'Alice' still contradicted fixed stance after retry; skipping turn",
            context={"expected_like_minded": True, "actual_like_minded": False, "action_type": "message"},
        )

    @pytest.mark.asyncio
    async def legacy_low_confidence_stance_mismatch_does_not_trigger_retry(self):
        state = _make_state(participant_stance_hint="against")
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={"Alice": {"stance": "disagree"}},
        )
        anon_alice = orch._name_map["Alice"]

        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )
        orch.performer_llm.generate_response = AsyncMock(
            return_value="Este plan es necesario y justo."
        )
        orch.moderator_llm.generate_response = AsyncMock(
            return_value="Este plan es necesario y justo."
        )
        orch.classifier_llm.generate_response = AsyncMock(
            return_value=json.dumps({
                "is_incivil": False,
                "is_like_minded": False,
                "stance_confidence": "low",
                "inferred_participant_stance": "against",
                "rationale": "Unclear but maybe mismatch",
            })
        )

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.message.content == "Este plan es necesario y justo."
        assert orch.performer_llm.generate_response.call_count == 1
        assert not any(
            call.args and call.args[0] == "performer_stance_mismatch_retry"
            for call in logger.log_error.call_args_list
        )

    @pytest.mark.asyncio
    async def legacy_free_text_classifier_stance_disagreement_does_not_trigger_retry(self):
        state = _make_state(participant_stance_hint="qualified_against")
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={"Alice": {"stance": "disagree", "ideology": "right"}},
        )
        anon_alice = orch._name_map["Alice"]

        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer=anon_alice, action_type="message")
        )
        orch.performer_llm.generate_response = AsyncMock(
            return_value="Este plan es una vergÃ¼enza y hay que frenarlo."
        )
        orch.moderator_llm.generate_response = AsyncMock(
            return_value="Este plan es una vergÃ¼enza y hay que frenarlo."
        )
        orch.classifier_llm.generate_response = AsyncMock(
            return_value=json.dumps({
                "is_incivil": True,
                "is_like_minded": False,
                "stance_confidence": "high",
                "inferred_participant_stance": "Supports regularization but concerned about racist implementation.",
                "rationale": "The agent rejects the plan while the participant supports it with reservations.",
            })
        )

        result = await orch.execute_turn("criteria_A")

        assert result is not None
        assert result.action_type == "message"
        assert result.message is not None
        assert result.message.is_like_minded is False
        assert orch.performer_llm.generate_response.call_count == 1
        assert not any(
            call.args and call.args[0] == "performer_stance_mismatch_retry"
            for call in logger.log_error.call_args_list
        )


# â”€â”€ execute_turn: error handling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    async def test_director_action_retries_when_performer_label_is_not_visible(self):
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        orch.director_llm.generate_response = AsyncMock(
            side_effect=[
                _action_json(next_performer="Performer 99", action_type="message"),
                _action_json(next_performer=anon_alice, action_type="message"),
            ]
        )

        result = await orch._director_action(anon_recent=[])

        assert result is not None
        assert result["next_performer"] == anon_alice
        logger.log_error.assert_any_call(
            "director_action_unknown_performer_label",
            "attempt 1/3: Director returned next_performer 'Performer 99', which is not one of the visible performer labels in AGENT_PROFILES",
        )

    @pytest.mark.asyncio
    async def test_director_action_retries_when_target_user_label_is_not_visible(self):
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]
        orch.director_llm.generate_response = AsyncMock(
            side_effect=[
                _action_json(next_performer=anon_alice, action_type="@mention", target_user="Performer 99"),
                _action_json(next_performer=anon_alice, action_type="@mention", target_user=anon_bob),
            ]
        )

        result = await orch._director_action(anon_recent=[])

        assert result is not None
        assert result["target_user"] == anon_bob
        logger.log_error.assert_any_call(
            "director_action_unknown_target_label",
            "attempt 1/3: Director returned target_user 'Performer 99', which is not one of the visible session-member labels for this turn",
        )

    @pytest.mark.asyncio
    async def test_director_action_retries_when_reply_target_is_invalid_for_speaker(self):
        state = _make_state(agents=[Agent(name="Alice"), Agent(name="Bob"), Agent(name="Carol")])
        same_cell_msg = Message.create(sender="Bob", content="Aliado")
        valid_target_msg = Message.create(sender="Carol", content="Oponente")
        state.add_message(same_cell_msg)
        state.add_message(valid_target_msg)
        orch, logger = _make_orchestrator(
            state=state,
            agent_traits={
                "Alice": {"alignment_cell": "pro_policy_pro_topic"},
                "Bob": {"alignment_cell": "pro_policy_pro_topic"},
                "Carol": {"alignment_cell": "anti_policy_anti_topic"},
            },
        )
        anon_alice = orch._name_map["Alice"]

        orch.director_llm.generate_response = AsyncMock(
            side_effect=[
                _action_json(
                    next_performer=anon_alice,
                    action_type="reply",
                    target_message_id=same_cell_msg.message_id,
                ),
                _action_json(
                    next_performer=anon_alice,
                    action_type="reply",
                    target_message_id=valid_target_msg.message_id,
                ),
            ]
        )

        result = await orch._director_action(
            anon_recent=[anonymize_message(m, orch._name_map) for m in state.messages],
            real_recent=state.messages,
        )

        assert result is not None
        assert result["target_message_id"] == valid_target_msg.message_id
        logger.log_error.assert_any_call(
            "director_action_invalid_reply_target",
            f"attempt 1/3: Director returned reply target '{same_cell_msg.message_id}' for '{anon_alice}', but that message is not a valid reply target for the chosen speaker",
        )

    @pytest.mark.asyncio
    async def test_no_agents_returns_wait(self):
        """With no agents, only the participant is available â€” Director must yield."""
        state = _make_state(agents=[])
        orch, logger = _make_orchestrator(state=state)
        orch.director_llm.generate_response = AsyncMock(
            return_value=_action_json(next_performer="participant")
        )

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.action_type == "wait"

    @pytest.mark.asyncio
    async def test_unknown_agent_falls_back(self):
        """Director picks a non-visible name â†’ action retries and the turn is skipped if it never recovers."""
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)

        action_resp = _action_json(next_performer="UnknownAgent", action_type="message")
        orch.director_llm.generate_response = AsyncMock(side_effect=[action_resp, action_resp, action_resp])
        orch.performer_llm.generate_response = AsyncMock(return_value="Hi")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hi")

        result = await orch.execute_turn("criteria_A")
        assert result is None
        logger.log_error.assert_any_call(
            "director_action_unknown_performer_label",
            "attempt 1/3: Director returned next_performer 'UnknownAgent', which is not one of the visible performer labels in AGENT_PROFILES",
        )


# â”€â”€ Performer retry logic â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        """Moderator returns NO_CONTENT â†’ triggers performer retry."""
        state = _make_state()
        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = _action_json(next_performer=anon_alice, action_type="message")
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)

        orch.performer_llm.generate_response = AsyncMock(
            side_effect=["mensaje: bad output", "mensaje: good output"]
        )
        orch.moderator_llm.generate_response = AsyncMock(
            side_effect=["NO_CONTENT", "Cleaned output"]
        )

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.message.content == "Cleaned output"


# â”€â”€ Deanonymization in output â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        assert result.message.content == "I agree with Bob!"


# â”€â”€ TurnResult dataclass â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


class TestUpgradeAndStripping:

    @pytest.mark.asyncio
    async def test_upgrade_out_of_turn_targeted_message(self):
        state = _make_state()
        m1 = Message.create(sender="Alice", content="Hello")
        m2 = Message.create(sender="participant", content="Hi")
        # Alice is the target, but her message is not the last one in the chat (m2 is)
        state.add_message(m1)
        state.add_message(m2)

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]

        action_resp = json.dumps({
            "next_performer": anon_bob,
            "action_type": "message",
            "target_user": anon_alice,
            "priority": "normal",
            "performer_rationale": "bob rational",
            "action_rationale": "act rational",
            "performer_instruction": {
                "objective": "obj",
                "motivation": "mot",
                "directive": "dir"
            }
        })
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="Hola!")
        orch.moderator_llm.generate_response = AsyncMock(return_value="Hola!")

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.action_type == "reply"
        assert result.target_message_id == m1.message_id
        assert result.message.reply_to == m1.message_id

    def test_strip_vocative_prefixes(self):
        state = _make_state()
        orch, _ = _make_orchestrator(state=state)
        
        orch._name_map = {"Alice": "Performer 1", "Bob": "Performer 2"}
        orch._reverse_map = {"Performer 1": "Alice", "Performer 2": "Bob"}

        assert orch._strip_vocative_prefix("Alice, hola!") == "Hola!"
        assert orch._strip_vocative_prefix("Bob: Qué tal?") == "Qué tal?"
        assert orch._strip_vocative_prefix("¿Alice... qué dices?") == "¿Qué dices?"
        assert orch._strip_vocative_prefix("¡Bob - no hagas eso!") == "¡No hagas eso!"
        
        orch._name_map["Lucía"] = "Performer 3"
        orch._reverse_map["Performer 3"] = "Lucía"
        assert orch._strip_vocative_prefix("Lucia, cómo estás?") == "Cómo estás?"
        assert orch._strip_vocative_prefix("¿Lucía: dónde vas?") == "¿Dónde vas?"
        
        assert orch._strip_vocative_prefix("Charlie, hello") == "Charlie, hello"


class TestDowngradePrecedingTarget:

    @pytest.mark.asyncio
    async def test_reply_to_last_message_downgrades_to_plain_message(self):
        state = _make_state()
        m1 = Message.create(sender="Bob", content="Hello")
        state.add_message(m1)

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]

        action_resp = json.dumps({
            "next_performer": anon_alice,
            "action_type": "reply",
            "target_message_id": m1.message_id,
            "priority": "normal",
            "performer_rationale": "alice rational",
            "action_rationale": "act rational",
            "performer_instruction": {
                "objective": "original objective",
                "motivation": "original motivation",
                "directive": "original directive"
            }
        })
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="My reply response")
        orch.moderator_llm.generate_response = AsyncMock(return_value="My reply response")

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.action_type == "message"
        assert result.target_message_id is None
        assert result.target_user is None
        assert result.message.reply_to is None
        assert result.message.quoted_text is None
        assert result.message.content == "My reply response"
        logger.log_error.assert_any_call(
            "downgrade_immediate_reply",
            f"Downgrading reply for 'Alice' to message because it targets the immediately preceding message {m1.message_id}"
        )

    @pytest.mark.asyncio
    async def test_mention_to_last_sender_downgrades_to_plain_message(self):
        state = _make_state()
        m1 = Message.create(sender="Bob", content="Hello")
        state.add_message(m1)

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]

        action_resp = json.dumps({
            "next_performer": anon_alice,
            "action_type": "@mention",
            "target_user": anon_bob,
            "priority": "normal",
            "performer_rationale": "alice rational",
            "action_rationale": "act rational",
            "performer_instruction": {
                "objective": "original objective",
                "motivation": "original motivation",
                "directive": "original directive"
            }
        })
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="My mention response")
        orch.moderator_llm.generate_response = AsyncMock(return_value="My mention response")

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.action_type == "message"
        assert result.target_user is None
        assert result.target_message_id is None
        assert result.message.content == "My mention response"
        logger.log_error.assert_any_call(
            "downgrade_immediate_mention",
            "Downgrading mention for 'Alice' to message because it targets the sender of the immediately preceding message 'Bob'"
        )

    @pytest.mark.asyncio
    async def test_targeted_message_to_last_sender_clears_target(self):
        state = _make_state()
        m1 = Message.create(sender="Bob", content="Hello")
        state.add_message(m1)

        orch, logger = _make_orchestrator(state=state)
        anon_alice = orch._name_map["Alice"]
        anon_bob = orch._name_map["Bob"]

        action_resp = json.dumps({
            "next_performer": anon_alice,
            "action_type": "message",
            "target_user": anon_bob,
            "priority": "normal",
            "performer_rationale": "alice rational",
            "action_rationale": "act rational",
            "performer_instruction": {
                "objective": "original objective",
                "motivation": "original motivation",
                "directive": "original directive"
            }
        })
        orch.director_llm.generate_response = AsyncMock(return_value=action_resp)
        orch.performer_llm.generate_response = AsyncMock(return_value="My message response")
        orch.moderator_llm.generate_response = AsyncMock(return_value="My message response")

        result = await orch.execute_turn("criteria_A")
        assert result is not None
        assert result.action_type == "message"
        assert result.target_user is None
        assert result.target_message_id is None
        logger.log_error.assert_any_call(
            "downgrade_immediate_targeted_message",
            "Removing target_user for 'Alice' because it targets the sender of the immediately preceding message 'Bob'"
        )





