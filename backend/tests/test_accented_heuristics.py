"""Accented Spanish must trigger the orchestrator's text heuristics.

The file once suffered an encoding round-trip that corrupted the accented
characters inside these regexes, so "patético" passed guards that caught
"patetico". These tests pin the accented and unaccented forms side by side
so the corruption cannot silently return.
"""
from __future__ import annotations

import pytest

from agents.STAGE.orchestrator import Orchestrator, _looks_truncated_response


LONG = "x" * 210  # past the 200-char threshold of the truncation heuristic


@pytest.mark.parametrize("text", [
    "que patético",
    "que patetico",
    "cuantas tonterías",
    "cuantas tonterias",
    "menudo imbécil",
    "menudo imbecil",
])
def test_attack_detection_handles_accents(text):
    assert Orchestrator._looks_like_attack_on_participant(text) is True


@pytest.mark.parametrize("text", [
    "tienes razón",
    "tienes razon",
    "llevas razón en eso",
])
def test_agreement_detection_handles_accents(text):
    assert Orchestrator._looks_like_agent_validation(text) is True


@pytest.mark.parametrize("text", [
    "la inmigración es un derecho pero está mal planteado",
    "la inmigracion es un derecho pero esta mal planteado",
])
def test_stance_inference_handles_accents(text):
    cell = Orchestrator._participant_alignment_cell_from_message(text)
    assert cell == "pro_topic"


def test_substantive_message_accepts_pure_accented_text():
    assert Orchestrator._is_substantive_participant_message("áéíóú ñÑ ÁÉÍ ÓÚ") is True


class TestTruncationHeuristics:
    def test_em_dash_ending_is_truncated(self):
        assert _looks_truncated_response(LONG + " y luego—") is True

    def test_open_question_mark_ending_is_truncated(self):
        assert _looks_truncated_response(LONG + " pero ¿") is True

    def test_sentence_ending_is_not_truncated(self):
        assert _looks_truncated_response(LONG + " fin.") is False

    def test_ellipsis_ending_is_not_truncated(self):
        assert _looks_truncated_response(LONG + " bueno…") is False

    def test_emoji_ending_is_not_truncated(self):
        assert _looks_truncated_response(LONG + " jaja 😂") is False


def test_no_mojibake_in_source():
    """The tell-tale byte sequences of the original corruption must never
    reappear anywhere in the module."""
    import agents.STAGE.orchestrator as module
    source = open(module.__file__, encoding="utf-8").read()
    for marker in ("Ã", "â€", "ðŸ", "Â¿"):
        assert marker not in source, f"mojibake marker {marker!r} found in orchestrator.py"
