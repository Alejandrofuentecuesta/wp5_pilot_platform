import pytest

from agents.STAGE.safety_classifier import (
    build_participant_safety_prompt,
    parse_participant_safety_response,
)
from models.message import Message


def test_prompt_marks_latest_message_and_labels_speakers():
    participant = Message.create(sender="Alias", content="Me siento realmente mal")
    agent = Message.create(sender="Alice", content="No era mi intención")

    prompt = build_participant_safety_prompt(
        latest_message=participant,
        recent_context=[agent, participant],
        participant_name="Alias",
    )

    assert '"speaker": "participant"' in prompt
    assert '"speaker": "other_user"' in prompt
    assert '"latest_participant_message": "Me siento realmente mal"' in prompt


@pytest.mark.parametrize("category", ["self_harm", "severe_distress"])
def test_parse_positive_safety_decision(category):
    result = parse_participant_safety_response(
        f'```json\n{{"should_stop": true, "category": "{category}", '
        '"confidence": "high", "rationale": "explicit statement"}\n```'
    )

    assert result["should_stop"] is True
    assert result["category"] == category
    assert result["confidence"] == "high"


def test_parse_continue_normalizes_category():
    result = parse_participant_safety_response(
        '{"should_stop": false, "category": "severe_distress", '
        '"confidence": "medium", "rationale": "only mild discomfort"}'
    )

    assert result["should_stop"] is False
    assert result["category"] == "none"


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"category": "none"}',
        '{"should_stop": true, "category": "none"}',
        '{"should_stop": true, "category": "other"}',
    ],
)
def test_parse_rejects_invalid_responses(raw):
    with pytest.raises(ValueError):
        parse_participant_safety_response(raw)
