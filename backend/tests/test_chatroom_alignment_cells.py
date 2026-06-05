from platforms.chatroom import (
    _participant_alignment_cell,
    _agent_alignment_cell,
    _participant_cell_preferences,
)


def test_participant_alignment_cell_mapping():
    assert _participant_alignment_cell("favor") == "pro_topic"
    assert _participant_alignment_cell("qualified_favor") == "pro_topic"
    assert _participant_alignment_cell("qualified_against") == "pro_topic"
    assert _participant_alignment_cell("against") == "anti_topic"
    assert _participant_alignment_cell("skeptical") is None


def test_agent_alignment_cell_prefers_explicit_value():
    agent = {
        "alignment_cell": "anti_policy_pro_topic",
        "ideology": "left",
        "policy_stance": "pro_policy",
        "topic_stance": "pro_topic",
    }
    assert _agent_alignment_cell(agent) == "pro_topic"


def test_agent_alignment_cell_can_be_derived_from_policy_and_topic():
    assert _agent_alignment_cell({"policy_stance": "pro_policy", "topic_stance": "pro_topic"}) == "pro_topic"
    assert _agent_alignment_cell({"policy_stance": "anti_policy", "topic_stance": "pro_topic"}) == "pro_topic"
    assert _agent_alignment_cell({"policy_stance": "anti_policy", "topic_stance": "anti_topic"}) == "anti_topic"


def test_participant_cell_preferences_follow_same_cell_logic():
    like_cells, opposite_cells = _participant_cell_preferences("qualified_against")
    assert like_cells == ["pro_topic"]
    assert opposite_cells == ["anti_topic"]
