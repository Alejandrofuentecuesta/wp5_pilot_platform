import json
from unittest.mock import AsyncMock

import pytest

from utils.participant_alignment import (
    build_alignment_classifier_prompt,
    parse_alignment_classifier_response,
    resolve_first_message_alignment,
    resolve_first_message_alignment_sync,
)


def test_build_prompts_contains_required_rules():
    sys_prompt, user_prompt = build_alignment_classifier_prompt(
        content="Creo que los inmigrantes aportan mucho a este país y deberian regularizarlos.",
        topic="immigration",
        survey_cell="anti_topic",
        headline="España supera los 6,9 millones de residentes extranjeros",
    )
    assert "Telegram-style group chat" in sys_prompt
    assert "Conservative override requirement" in sys_prompt
    assert '"pro"' in sys_prompt and '"anti"' in sys_prompt and '"neutral"' in sys_prompt
    assert "regularisation" in sys_prompt
    assert "España supera los 6,9 millones" in user_prompt
    assert "anti_topic" in user_prompt


def test_parse_classifier_response():
    raw_markdown = '```json\n{"stance": "pro", "confidence": "high", "rationale": "Economic contribution."}\n```'
    parsed = parse_alignment_classifier_response(raw_markdown)
    assert parsed["stance"] == "pro"
    assert parsed["confidence"] == "high"

    raw_plain = '{"stance": "anti", "confidence": "medium", "rationale": "Security concerns."}'
    parsed2 = parse_alignment_classifier_response(raw_plain)
    assert parsed2["stance"] == "anti"


def test_sync_resolution_fallback():
    result = resolve_first_message_alignment_sync(
        survey_stance="anti_topic",
        survey_cell="anti_topic",
        content="Estoy a favor de la inmigracion",
        topic="immigration",
        message_id="sync-1",
    )
    assert result["effective_cell"] == "anti_topic"
    assert result["source"] == "survey"
    assert result["locked"] is True


@pytest.mark.asyncio
async def test_llm_classifier_corrects_raul_message():
    """Test 1: Survey says anti_topic, but first message is clearly pro-immigration."""
    mock_llm = AsyncMock()
    mock_llm.generate_response.return_value = json.dumps({
        "stance": "pro",
        "confidence": "high",
        "rationale": "Stresses economic contribution and calls for regularisation.",
    })

    content = "Creo que los inmigrantes aportan mucho a este país y deberian regularizarlos. nuestra economia se va a pique sin ellos"
    result = await resolve_first_message_alignment(
        survey_stance="anti_topic",
        survey_cell="anti_topic",
        content=content,
        topic="immigration",
        message_id="msg-raul",
        classifier_llm=mock_llm,
    )
    assert result["inferred_cell"] == "pro_topic"
    assert result["effective_cell"] == "pro_topic"
    assert result["source"] == "first_message_correction"
    assert result["locked"] is True
    assert mock_llm.generate_response.call_count == 1


@pytest.mark.asyncio
async def test_llm_classifier_corrects_mario_message():
    """Test 2: Survey says pro_topic, but first message is violently anti-immigration."""
    mock_llm = AsyncMock()
    mock_llm.generate_response.return_value = json.dumps({
        "stance": "anti",
        "confidence": "high",
        "rationale": "Uses dehumanizing language ('parásitos') and demands cleaning the streets.",
    })

    content = "Debemos limpiar ya las calles de estos parasitos, delinquen, nos dejan sin vivienda i sin servicios y encima les dan paguitas"
    result = await resolve_first_message_alignment(
        survey_stance="pro_topic",
        survey_cell="pro_topic",
        content=content,
        topic="immigration",
        message_id="msg-mario",
        classifier_llm=mock_llm,
    )
    assert result["inferred_cell"] == "anti_topic"
    assert result["effective_cell"] == "anti_topic"
    assert result["source"] == "first_message_correction"
    assert result["locked"] is True


@pytest.mark.asyncio
async def test_llm_classifier_abstains_on_greeting_or_ambiguity():
    """Test 3: Greeting should NOT override the survey."""
    mock_llm = AsyncMock()
    mock_llm.generate_response.return_value = json.dumps({
        "stance": "off_topic",
        "confidence": "high",
        "rationale": "Just a greeting.",
    })

    result = await resolve_first_message_alignment(
        survey_stance="anti_topic",
        survey_cell="anti_topic",
        content="Hola a todos, acabo de leer la noticia.",
        topic="immigration",
        message_id="msg-greeting",
        classifier_llm=mock_llm,
    )
    assert result["inferred_cell"] is None
    assert result["effective_cell"] == "anti_topic"
    assert result["source"] == "survey"
    assert result["locked"] is True


@pytest.mark.asyncio
async def test_llm_classifier_abstains_on_low_confidence():
    """Test 4: Low confidence should not override the survey."""
    mock_llm = AsyncMock()
    mock_llm.generate_response.return_value = json.dumps({
        "stance": "pro",
        "confidence": "low",
        "rationale": "Vague mention of economy.",
    })

    result = await resolve_first_message_alignment(
        survey_stance="anti_topic",
        survey_cell="anti_topic",
        content="La economia es rara.",
        topic="immigration",
        message_id="msg-vague",
        classifier_llm=mock_llm,
    )
    assert result["inferred_cell"] is None
    assert result["effective_cell"] == "anti_topic"
    assert result["source"] == "survey"


@pytest.mark.asyncio
async def test_llm_classifier_abstains_when_llm_fails_or_times_out():
    """Test 5: If LLM call fails, the survey stance is preserved safely."""
    mock_llm = AsyncMock()
    mock_llm.generate_response.side_effect = TimeoutError("Anthropic timeout")

    result = await resolve_first_message_alignment(
        survey_stance="anti_topic",
        survey_cell="anti_topic",
        content="Estoy claramente a favor de la inmigracion",
        topic="immigration",
        message_id="msg-timeout",
        classifier_llm=mock_llm,
    )
    assert result["inferred_cell"] is None
    assert result["effective_cell"] == "anti_topic"
    assert result["source"] == "survey"
    assert result["locked"] is True


@pytest.mark.asyncio
async def test_climate_change_prompt():
    """Test 6: Climate change topic builds correct prompt and labels."""
    sys_prompt, user_prompt = build_alignment_classifier_prompt(
        content="Debemos priorizar las energias renovables",
        topic="climate_change",
        survey_cell="anti_topic",
    )
    assert "Climate change and energy transition" in sys_prompt
    assert "renewable energy" in sys_prompt
