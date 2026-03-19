"""Unit tests for agents/STAGE/classifier.py."""

from datetime import datetime, timezone

import pytest

from agents.STAGE.classifier import (
    build_classifier_system_prompt,
    build_classifier_user_prompt,
    parse_classifier_response,
)
from models.message import Message


def _participant_msg(content: str) -> Message:
    return Message(
        sender="participant",
        content=content,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        message_id="m1",
    )


class TestBuildClassifierSystemPrompt:
    def test_injects_chatroom_context(self):
        prompt = build_classifier_system_prompt(chatroom_context="Debate politico")
        assert "Debate politico" in prompt


class TestBuildClassifierUserPrompt:
    def test_injects_placeholders(self):
        prompt = build_classifier_user_prompt(
            participant_messages=[_participant_msg("Estoy a favor de subir impuestos.")],
            agent_message="Totalmente de acuerdo contigo.",
            prompt_template=(
                "CTX:{CHATROOM_CONTEXT}\n"
                "P:{PARTICIPANT_MESSAGES}\n"
                "A:{AGENT_MESSAGE}"
            ),
            chatroom_context="Contexto test",
        )
        assert "CTX:Contexto test" in prompt
        assert "Estoy a favor de subir impuestos." in prompt
        assert "Totalmente de acuerdo contigo." in prompt


class TestParseClassifierResponse:
    def test_parses_valid_json(self):
        raw = """
        {
          "is_incivil": true,
          "is_like_minded": false,
          "inferred_participant_stance": "pro redistribucion",
          "rationale": "Ataca con desprecio y contradice la postura."
        }
        """
        parsed = parse_classifier_response(raw)
        assert parsed["is_incivil"] is True
        assert parsed["is_like_minded"] is False
        assert parsed["inferred_participant_stance"] == "pro redistribucion"

    def test_accepts_markdown_fence(self):
        raw = """```json\n{"is_incivil": false, "is_like_minded": null}\n```"""
        parsed = parse_classifier_response(raw)
        assert parsed["is_incivil"] is False
        assert parsed["is_like_minded"] is None

    def test_raises_when_incivil_missing(self):
        with pytest.raises(ValueError, match="is_incivil"):
            parse_classifier_response('{"is_like_minded": true}')
