import random
from agents.STAGE.orchestrator import select_incivility_dimensions


def test_select_incivility_dimensions_probabilities():
    """Verify that select_incivility_dimensions has the correct probabilities over 10000 trials."""
    rng = random.Random(42)  # Seed for reproducibility
    
    trials = 10000
    impoliteness_count = 0
    hate_speech_count = 0
    democratic_threats_count = 0
    empty_runs = 0
    
    for _ in range(trials):
        selected = select_incivility_dimensions(rng)
        if not selected:
            empty_runs += 1
            
        if "impoliteness" in selected:
            impoliteness_count += 1
        if "hate_speech" in selected:
            hate_speech_count += 1
        if "democratic_threats" in selected:
            democratic_threats_count += 1
            
    # No empty runs should happen because of fallback
    assert empty_runs == 0
    
    # Expected probabilities including fallback:
    # impoliteness: ~84.3%
    # hate_speech: ~52.7%
    # democratic_threats: ~21.1%
    
    impoliteness_rate = impoliteness_count / trials
    hate_speech_rate = hate_speech_count / trials
    democratic_threats_rate = democratic_threats_count / trials
    
    assert 0.82 <= impoliteness_rate <= 0.87
    assert 0.50 <= hate_speech_rate <= 0.55
    assert 0.18 <= democratic_threats_rate <= 0.24


def test_uncivil_agent_ideology_balancing():
    """Verify that _filter_candidate_agents_for_targets balances ideology for uncivil turns."""
    from unittest.mock import AsyncMock, MagicMock
    from models.message import Message
    from models.agent import Agent
    from models.session import SessionState
    from agents.STAGE.orchestrator import Orchestrator

    agents = [
        Agent(name="LeftUncivil1"),
        Agent(name="LeftUncivil2"),
        Agent(name="RightUncivil1"),
        Agent(name="RightUncivil2"),
        Agent(name="CenterCivil"),
    ]
    agent_traits = {
        "LeftUncivil1": {"incivility": "uncivil", "ideology": "left"},
        "LeftUncivil2": {"incivility": "uncivil", "ideology": "left"},
        "RightUncivil1": {"incivility": "uncivil", "ideology": "right"},
        "RightUncivil2": {"incivility": "uncivil", "ideology": "right"},
        "CenterCivil": {"incivility": "civil", "ideology": "center"},
    }

    state = SessionState(
        session_id="test-session",
        agents=agents,
        duration_minutes=30,
        experimental_config={},
        treatment_group="control",
        simulation_config={},
        user_name="participant",
    )

    logger = MagicMock()
    orch = Orchestrator(
        director_llm=AsyncMock(),
        performer_llm=AsyncMock(),
        moderator_llm=AsyncMock(),
        classifier_llm=AsyncMock(),
        state=state,
        logger=logger,
        agent_traits=agent_traits,
        rng=random.Random(42),
    )

    # Initially, no messages. If we evaluate, counts are 0/0.
    # Simulate a history of messages:
    # Let's say LeftUncivil1 has sent an uncivil message.
    # So left=1, right=0. Preferred ideology should be 'right'.
    state.add_message(Message.create(sender="LeftUncivil1", content="Left Uncivil Msg", is_incivil=True))

    filtered = orch._filter_candidate_agents_for_targets(
        "INCIVILITY_TARGET = 50",
        {"LeftUncivil1", "LeftUncivil2", "RightUncivil1", "RightUncivil2", "CenterCivil"}
    )
    # RightUncivil1 and RightUncivil2 should be prioritized over LeftUncivil1 (who has spoken and is wrong ideology)
    # and CenterCivil (who is civil).
    # Since we select top 4 out of 5:
    assert "RightUncivil1" in filtered
    assert "RightUncivil2" in filtered
    assert "LeftUncivil2" in filtered
    # "LeftUncivil1" (the wrong ideology who already spoke) is the one filtered out.
    assert "LeftUncivil1" not in filtered

    # Now let's simulate RightUncivil1 sending an uncivil message.
    # Now left=1, right=1. Balance is equal.
    # Let's add another uncivil message from RightUncivil2.
    # Now left=1, right=2. Preferred ideology should be 'left'.
    state.add_message(Message.create(sender="RightUncivil1", content="Right Uncivil Msg 1", is_incivil=True))
    state.add_message(Message.create(sender="RightUncivil2", content="Right Uncivil Msg 2", is_incivil=True))

    filtered = orch._filter_candidate_agents_for_targets(
        "INCIVILITY_TARGET = 50",
        {"LeftUncivil1", "LeftUncivil2", "RightUncivil1", "RightUncivil2", "CenterCivil"}
    )
    # LeftUncivil2 (left, hasn't spoken yet) and LeftUncivil1 (left, spoke) should be prioritized
    # because preferred ideology is left.
    # RightUncivil1 and RightUncivil2 are the wrong ideology and have spoken.
    # Let's make sure LeftUncivil2 and LeftUncivil1 are in filtered.
    assert "LeftUncivil2" in filtered
    assert "LeftUncivil1" in filtered


def test_ten_messages_mode_hard_targets():
    """Verify that _filter_candidate_agents_for_targets applies hard quotas in ten_messages_mode."""
    from unittest.mock import AsyncMock, MagicMock
    from models.message import Message
    from models.agent import Agent
    from models.session import SessionState
    from agents.STAGE.orchestrator import Orchestrator

    # 12 agents pool representing combinations of stance, civility, and left/right ideology
    agents = [
        Agent(name="L_Civ_Pro"), Agent(name="R_Civ_Pro"), Agent(name="C_Civ_Pro"),
        Agent(name="L_Unciv_Pro"), Agent(name="R_Unciv_Pro"), Agent(name="C_Unciv_Pro"),
        Agent(name="L_Civ_Anti"), Agent(name="R_Civ_Anti"), Agent(name="C_Civ_Anti"),
        Agent(name="L_Unciv_Anti"), Agent(name="R_Unciv_Anti"), Agent(name="C_Unciv_Anti"),
    ]
    agent_traits = {
        # Pro-topic (like-minded)
        "L_Civ_Pro": {"incivility": "civil", "ideology": "left", "alignment_cell": "pro_topic"},
        "R_Civ_Pro": {"incivility": "civil", "ideology": "right", "alignment_cell": "pro_topic"},
        "C_Civ_Pro": {"incivility": "civil", "ideology": "center", "alignment_cell": "pro_topic"},
        "L_Unciv_Pro": {"incivility": "uncivil", "ideology": "left", "alignment_cell": "pro_topic"},
        "R_Unciv_Pro": {"incivility": "uncivil", "ideology": "right", "alignment_cell": "pro_topic"},
        "C_Unciv_Pro": {"incivility": "uncivil", "ideology": "center", "alignment_cell": "pro_topic"},
        # Anti-topic (not-like-minded)
        "L_Civ_Anti": {"incivility": "civil", "ideology": "left", "alignment_cell": "anti_topic"},
        "R_Civ_Anti": {"incivility": "civil", "ideology": "right", "alignment_cell": "anti_topic"},
        "C_Civ_Anti": {"incivility": "civil", "ideology": "center", "alignment_cell": "anti_topic"},
        "L_Unciv_Anti": {"incivility": "uncivil", "ideology": "left", "alignment_cell": "anti_topic"},
        "R_Unciv_Anti": {"incivility": "uncivil", "ideology": "right", "alignment_cell": "anti_topic"},
        "C_Unciv_Anti": {"incivility": "uncivil", "ideology": "center", "alignment_cell": "anti_topic"},
    }

    state = SessionState(
        session_id="test-session",
        agents=agents,
        duration_minutes=30,
        experimental_config={},
        treatment_group="control",
        simulation_config={"ten_messages_mode": True},
        user_name="participant",
        participant_stance_hint="pro_topic",
    )

    logger = MagicMock()
    orch = Orchestrator(
        director_llm=AsyncMock(),
        performer_llm=AsyncMock(),
        moderator_llm=AsyncMock(),
        classifier_llm=AsyncMock(),
        state=state,
        logger=logger,
        agent_traits=agent_traits,
        ten_messages_mode=True,
        rng=random.Random(42),
    )

    all_candidates = set(agent_traits.keys())

    # --- SCENARIO A: 20% INCIVILITY TARGET ---
    # Target counts: 2 uncivil (1 left, 1 right), 8 civil (4 pro, 4 anti). Stance split: 5 pro, 5 anti.
    criteria_20 = "INCIVILITY_TARGET = 20\nLIKEMINDED_TARGET = 50\nNOT_LIKEMINDED_TARGET = 50"

    # Turn 1: No messages yet. All targets are open.
    filtered = orch._filter_candidate_agents_for_targets(criteria_20, all_candidates)
    # Check that center uncivil agents (e.g. C_Unciv_Pro) are filtered out because only left/right uncivil allowed
    assert "C_Unciv_Pro" not in filtered
    assert "C_Unciv_Anti" not in filtered
    # Civil agents of all ideologies and stance-aligned/opposed uncivil left/right are allowed
    assert "L_Civ_Pro" in filtered
    assert "L_Unciv_Pro" in filtered or "R_Unciv_Pro" in filtered

    # Simulating 8 civil messages (4 pro, 4 anti).
    # This means needed_civil reaches 0. Now only uncivil agents are allowed!
    for i in range(4):
        state.add_message(Message.create(sender="L_Civ_Pro", content=f"pro civil {i}", is_incivil=False))
        state.add_message(Message.create(sender="R_Civ_Anti", content=f"anti civil {i}", is_incivil=False))

    filtered = orch._filter_candidate_agents_for_targets(criteria_20, all_candidates)
    # Only uncivil agents are allowed now!
    for name in filtered:
        assert agent_traits[name]["incivility"] == "uncivil"

    # Let's say one left uncivil message is sent
    state.add_message(Message.create(sender="L_Unciv_Pro", content="left uncivil", is_incivil=True))

    filtered = orch._filter_candidate_agents_for_targets(criteria_20, all_candidates)
    # Left uncivil is now maxed out (target=1). Only right uncivil should be allowed!
    assert len(filtered) > 0
    for name in filtered:
        assert agent_traits[name]["incivility"] == "uncivil"
        assert agent_traits[name]["ideology"] == "right"

    # --- SCENARIO B: 80% INCIVILITY TARGET ---
    # Clean up the state
    state.messages.clear()
    orch = Orchestrator(
        director_llm=AsyncMock(),
        performer_llm=AsyncMock(),
        moderator_llm=AsyncMock(),
        classifier_llm=AsyncMock(),
        state=state,
        logger=logger,
        agent_traits=agent_traits,
        ten_messages_mode=True,
        rng=random.Random(42),
    )
    # Target counts: 8 uncivil (4 left, 4 right), 2 civil (1 pro, 1 anti).
    criteria_80 = "INCIVILITY_TARGET = 80\nLIKEMINDED_TARGET = 50\nNOT_LIKEMINDED_TARGET = 50"

    # Simulating 2 civil messages (1 pro, 1 anti)
    state.add_message(Message.create(sender="L_Civ_Pro", content="pro civil", is_incivil=False))
    state.add_message(Message.create(sender="R_Civ_Anti", content="anti civil", is_incivil=False))

    # Civil target is reached (2/2). Only uncivil agents are allowed!
    filtered = orch._filter_candidate_agents_for_targets(criteria_80, all_candidates)
    for name in filtered:
        assert agent_traits[name]["incivility"] == "uncivil"

    # Simulating 4 right uncivil messages
    for i in range(4):
        state.add_message(Message.create(sender="R_Unciv_Pro", content=f"right uncivil {i}", is_incivil=True))

    # Right uncivil is maxed out (4/4). Only left uncivil is allowed!
    filtered = orch._filter_candidate_agents_for_targets(criteria_80, all_candidates)
    assert len(filtered) > 0
    for name in filtered:
        assert agent_traits[name]["incivility"] == "uncivil"
        assert agent_traits[name]["ideology"] == "left"



