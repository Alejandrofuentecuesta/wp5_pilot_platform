import json
import random
import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from models.message import Message
from models.agent import Agent
from models.session import SessionState
from agents.STAGE.orchestrator import Orchestrator
from agents.STAGE.director import _BOOSTED_ACTION_TEMPLATE, _ACTION_TEMPLATE


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


def _make_orchestrator(boost_replies_mentions=False, state=None):
    if state is None:
        state = _make_state()
    director_llm = AsyncMock()
    performer_llm = AsyncMock()
    moderator_llm = AsyncMock()
    classifier_llm = AsyncMock()

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
        ecological_criteria="Informal chat",
        boost_replies_mentions=boost_replies_mentions,
        rng=random.Random(42),
    )
    return orch, logger


def test_should_boost_replies_mentions_env_and_config():
    # Test case 1: config flag is True, env var is unset/False
    with patch.dict(os.environ, {}, clear=False):
        orch, _ = _make_orchestrator(boost_replies_mentions=True)
        assert orch._should_boost_replies_mentions() is True

    # Test case 2: config flag is False, env var is True
    with patch.dict(os.environ, {"BOOST_REPLIES_MENTIONS": "true"}):
        orch, _ = _make_orchestrator(boost_replies_mentions=False)
        assert orch._should_boost_replies_mentions() is True

    # Test case 3: config flag is False, env var is False
    with patch.dict(os.environ, {"BOOST_REPLIES_MENTIONS": "false"}):
        orch, _ = _make_orchestrator(boost_replies_mentions=False)
        assert orch._should_boost_replies_mentions() is False

    # Test case 4: config flag is True, env var is True
    with patch.dict(os.environ, {"BOOST_REPLIES_MENTIONS": "true"}):
        orch, _ = _make_orchestrator(boost_replies_mentions=True)
        assert orch._should_boost_replies_mentions() is True


@pytest.mark.asyncio
async def test_director_action_boosted_template_selection():
    # Test case 1: boost enabled -> should use boosted action template
    orch, _ = _make_orchestrator(boost_replies_mentions=True)
    orch.director_llm.generate_response = AsyncMock(return_value=json.dumps({
        "priority": "Keep civil",
        "performer_rationale": "ok",
        "action_rationale": "ok",
        "next_performer": "Bob",
        "action_type": "message",
        "performer_instruction": {
            "objective": "ok",
            "motivation": "ok",
            "directive": "ok"
        }
    }))

    # Trigger action call
    await orch._director_action(anon_recent=[])

    # Assert that the system prompt passed to LLM was built from the boosted template
    llm_call_args = orch.director_llm.generate_response.call_args
    system_prompt_used = llm_call_args[1]["system_prompt"]
    # Boosted prompt contains selective threaded interaction guidance
    assert "Selective threaded interaction" in system_prompt_used
    assert "Target approximately: 45% messages, 35% replies, 20% @mentions" in system_prompt_used


@pytest.mark.asyncio
async def test_director_action_default_template_selection():
    # Test case 2: boost disabled -> should use default action template
    orch, _ = _make_orchestrator(boost_replies_mentions=False)
    orch.director_llm.generate_response = AsyncMock(return_value=json.dumps({
        "priority": "Keep civil",
        "performer_rationale": "ok",
        "action_rationale": "ok",
        "next_performer": "Bob",
        "action_type": "message",
        "performer_instruction": {
            "objective": "ok",
            "motivation": "ok",
            "directive": "ok"
        }
    }))

    # Trigger action call
    await orch._director_action(anon_recent=[])

    # Assert that the system prompt passed to LLM was built from the default template
    llm_call_args = orch.director_llm.generate_response.call_args
    system_prompt_used = llm_call_args[1]["system_prompt"]
    assert "Active interaction is highly encouraged" not in system_prompt_used
    assert "Target approximately: 40% messages, 40% replies, 20% @mentions" not in system_prompt_used


def test_suggested_anchor_excludes_immediate_turns():
    # Setup state with 3 agents
    agents = [Agent(name="Alice"), Agent(name="Bob"), Agent(name="Charlie")]
    state = _make_state(agents=agents)
    
    # Charlie speaks first, then Bob speaks last
    m0 = Message.create(sender="Charlie", content="Charlie message")
    m1 = Message.create(sender="Bob", content="Bob message")
    state.messages = [m0, m1]

    # Under boost=False, Bob's message (immediately preceding) is the best anchor for Alice
    orch_normal, _ = _make_orchestrator(boost_replies_mentions=False, state=state)
    anchor_normal = orch_normal._find_best_direct_target_message("Alice", state.messages)
    assert anchor_normal is not None
    assert anchor_normal.message_id == m1.message_id

    # Now verify the constraint formatter recommendations:
    # When boost is False, the constraints text should recommend Bob's message
    constraints_normal = orch_normal._format_target_constraints_by_speaker({"Alice", "Bob", "Charlie"}, state.messages)
    assert f"Bob [{m1.message_id}]" in constraints_normal

    # Under boost=True, Bob's message and Bob must be excluded from target recommendations for Alice
    orch_boost, _ = _make_orchestrator(boost_replies_mentions=True, state=state)
    # The constraints formatting should automatically exclude msg-1 and Bob when querying the best anchor
    constraints_boost = orch_boost._format_target_constraints_by_speaker({"Alice", "Bob", "Charlie"}, state.messages)
    assert f"Charlie [{m0.message_id}]" in constraints_boost
    assert f"Bob [{m1.message_id}]" not in constraints_boost


def test_suggested_targets_exclude_inactive_agents():
    # Setup state with 4 agents
    agents = [Agent(name="Alice"), Agent(name="Bob"), Agent(name="Charlie"), Agent(name="Carlos")]
    state = _make_state(agents=agents)
    
    # Carlos has NOT spoken yet. Charlie has spoken.
    m0 = Message.create(sender="Charlie", content="Hello")
    state.messages = [m0]

    # Under boost=True or False, Carlos has not spoken, so he must not be in valid_targets/forbidden_targets
    orch, _ = _make_orchestrator(boost_replies_mentions=True, state=state)
    constraints = orch._format_target_constraints_by_speaker({"Alice"}, state.messages)
    
    # Carlos should not be visible in target list
    assert "Carlos" not in constraints
    # Charlie should be visible
    assert "Charlie" in constraints


@pytest.mark.asyncio
async def test_orchestrator_downgrades_inactive_targets():
    # Setup state
    agents = [Agent(name="Alice"), Agent(name="Bob"), Agent(name="Carlos")]
    state = _make_state(agents=agents)
    
    # Alice has spoken. Carlos has not.
    m0 = Message.create(sender="Alice", content="Hello")
    state.messages = [m0]

    orch, logger = _make_orchestrator(boost_replies_mentions=True, state=state)
    
    # Mock director choice: Bob replies to Carlos (who hasn't spoken yet)
    orch.director_llm.generate_response = AsyncMock(return_value=json.dumps({
        "priority": "Keep civil",
        "performer_rationale": "ok",
        "action_rationale": "ok",
        "next_performer": "Bob",
        "action_type": "reply",
        "target_user": "Carlos",
        "target_message_id": "dummy_id",
        "performer_instruction": {
            "objective": "ok",
            "motivation": "ok",
            "directive": "ok"
        }
    }))

    # We also mock performer_llm to avoid call errors
    orch.performer_llm.generate_response = AsyncMock(return_value="Bob message")
    orch.moderator_llm.generate_response = AsyncMock(return_value="Bob message")
    orch.classifier_llm.generate_response = AsyncMock(return_value='```json\n{"is_incivil": false, "is_like_minded": false}\n```')
    
    # Execute turn
    result = await orch.execute_turn("INCIVILITY_TARGET = 50")
    
    # It should have downgraded the action to "message" and cleared Carlos/dummy_id
    assert result is not None
    assert result.action_type == "message"
    assert result.target_user is None
    assert result.target_message_id is None
    # Check that it logged the inactive target downgrade error
    logger.log_error.assert_any_call(
        "downgrade_inactive_target",
        "Downgrading reply for 'Bob' to message because target_user 'Carlos' has not spoken yet"
    )


def test_suggested_anchor_randomization_boosted():
    # Setup state with several messages from different speakers
    agents = [Agent(name="Alice"), Agent(name="Bob"), Agent(name="Charlie"), Agent(name="David")]
    state = _make_state(agents=agents)
    
    # Let's create multiple eligible messages
    # All are eligible targets for Alice (different alignment cells)
    m0 = Message.create(sender="Bob", content="Bob msg 0")
    m1 = Message.create(sender="Charlie", content="Charlie msg 1")
    m2 = Message.create(sender="David", content="David msg 2")
    m3 = Message.create(sender="Bob", content="Bob msg 3")
    state.messages = [m0, m1, m2, m3]
    
    # For Alice, m3 is the last message (sender Bob).
    # Under boost=True, m3 and Bob are excluded. Eligible messages are m2 (David) and m1 (Charlie).
    # Since there is randomness, let's call _find_best_direct_target_message with different random seeds
    anchors = set()
    for seed in range(50):
        orch, _ = _make_orchestrator(boost_replies_mentions=True, state=state)
        orch._rng = random.Random(seed)
        anchor = orch._find_best_direct_target_message("Alice", state.messages)
        if anchor:
            anchors.add(anchor.message_id)
            
    # We should have selected both m1 and m2 across different seeds
    assert m1.message_id in anchors
    assert m2.message_id in anchors


