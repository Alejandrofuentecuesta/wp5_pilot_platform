"""Conservative, one-shot correction of the survey side from the first post using classifier LLM."""
import asyncio
import json
import re
from typing import Any, Optional


RESOLUTION_KEY = "participant_alignment_resolution"

# ── LLM Classifier Prompts ───────────────────────────────────────────────────

_IMMIGRATION_GUIDANCE = """Topic: Immigration in Spain.
Discusses a news article about foreign residents and immigration policy in Spain."""

_IMMIGRATION_PRO = """favourable to immigration or immigrants. Examples: stresses economic contribution, pensions, labour shortages or rights; calls for regularisation, papers, integration or welcome; rejects blaming immigrants; attacks anti-immigration discourse or parties as racist or scaremongering."""

_IMMIGRATION_ANTI = """restrictive or negative towards immigration. Examples: stresses pressure on services and housing, crime, insecurity, cultural threat, 'paguitas', or 'efecto llamada'; asks for more control, limits, border enforcement, deportations, or cleaning streets; attacks 'buenismo', pro-immigration positions, or the government for letting people in."""

_IMMIGRATION_INSULTS = """calling opponents 'fachas'/'racistas' → pro; calling opponents 'buenistas'/'progres' or 'parásitos' → anti"""

_IMMIGRATION_EXAMPLES = """Examples:
- Target: "Es muy bueno para la productividad del país y deberian regularizarlos" → {"stance":"pro","confidence":"high","rationale":"Stresses economic contribution and calls for regularisation."}
- Target: "Hay que tener una inmigración más regulada y controlada" → {"stance":"anti","confidence":"medium","rationale":"Asks for more control of immigration."}
- Target: "Debemos limpiar ya las calles de estos parasitos, delinquen y les dan paguitas" → {"stance":"anti","confidence":"high","rationale":"Dehumanizing anti-immigrant language and crime allegations."}
- Target: "Hola a todos, acabo de leer la noticia" → {"stance":"off_topic","confidence":"high","rationale":"Simple greeting without political stance."}
- Target: "XD" → {"stance":"unclear","confidence":"high","rationale":"No stance content."}"""

_CLIMATE_GUIDANCE = """Topic: Climate change and energy transition in Spain.
Discusses renewable energy, emissions cuts, and environmental regulations."""

_CLIMATE_PRO = """favourable to ambitious climate policy, renewable energy, reducing CO2 emissions, green transition, and environmental regulations."""

_CLIMATE_ANTI = """opposed to strict climate policy or green regulations; prioritizes fossil fuels (gas, coal), opposes emissions limits, or stresses economic costs of environmental transition."""

_CLIMATE_INSULTS = """calling opponents climate deniers or polluters → pro; calling environmentalists 'ecologistas de salón' or Agenda 2030 puppets → anti"""

_CLIMATE_EXAMPLES = """Examples:
- Target: "Debemos priorizar las energias renovables y reducir emisiones ya" → {"stance":"pro","confidence":"high","rationale":"Advocates prioritizing renewables and emissions reduction."}
- Target: "Las regulaciones ecologicas van a arruinar el pais, hay que priorizar el gas" → {"stance":"anti","confidence":"high","rationale":"Opposes environmental regulations and prioritizes fossil fuels."}
- Target: "Hola a todos" → {"stance":"off_topic","confidence":"high","rationale":"Greeting with no stance."}"""

PARTICIPANT_ALIGNMENT_SYSTEM_PROMPT = """You are a careful annotator for a social-science study. People in Spain discuss a news article in a Telegram-style group chat. The messages are in Spanish and informal (slang, typos, abbreviations such as "q", "pq", "xq", "tb", etc.).

Your task: classify the stance or position expressed in the participant's FIRST message in the chat.

{TOPIC_GUIDANCE}

Labels:
- "pro": {PRO_LABEL}
- "anti": {ANTI_LABEL}
- "neutral": on topic but balanced, both sides, or no discernible direction (e.g. a genuine question, or "hay que gestionarlo mejor" without saying in which direction).
- "off_topic": not about the topic (greetings like "hola a todos", comments about the chat interface, other politics with no topic angle).
- "unclear": too short or ambiguous to decide even with the context.

Rules:
1. Classify the TARGET message only.
2. Short replies or single-word reactions ("exacto", "totalmente", "eso es mentira", "estoy de acuerdo", "xd") take the position of what they endorse/reject if clear; otherwise use "unclear".
3. Read sarcasm and irony for their intended meaning.
4. Insulting or attacking one side counts as taking the other side only if the direction is clear (e.g. {INSULT_EXAMPLES}).
5. Do not use any information about who wrote the message.
6. Conservative override requirement: This classification is used to verify if the participant clearly and unambiguously contradicts their pre-chat survey response. When the message is a greeting ("hola"), an expression of uncertainty or doubt ("no sé", "depende", "tengo dudas"), neutral, or off-topic, you MUST assign "neutral", "off_topic", or "unclear". Only assign "pro" or "anti" if the message expresses an explicit, definite stance.

Return ONLY a single valid JSON object, no extra text or markdown formatting:
{{"stance": "pro|anti|neutral|off_topic|unclear", "confidence": "high|medium|low", "rationale": "max 25 words"}}

{EXAMPLES}
"""


def build_alignment_classifier_prompt(
    *,
    content: str,
    topic: str,
    survey_cell: Optional[str] = None,
    headline: Optional[str] = None,
) -> tuple[str, str]:
    if topic == "climate_change":
        guidance = _CLIMATE_GUIDANCE
        pro_label = _CLIMATE_PRO
        anti_label = _CLIMATE_ANTI
        insults = _CLIMATE_INSULTS
        examples = _CLIMATE_EXAMPLES
    else:
        guidance = _IMMIGRATION_GUIDANCE
        pro_label = _IMMIGRATION_PRO
        anti_label = _IMMIGRATION_ANTI
        insults = _IMMIGRATION_INSULTS
        examples = _IMMIGRATION_EXAMPLES

    system_prompt = PARTICIPANT_ALIGNMENT_SYSTEM_PROMPT.format(
        TOPIC_GUIDANCE=guidance,
        PRO_LABEL=pro_label,
        ANTI_LABEL=anti_label,
        INSULT_EXAMPLES=insults,
        EXAMPLES=examples,
    )

    user_parts = []
    if headline:
        user_parts.append(f"News article headline: {headline}")
    if survey_cell:
        user_parts.append(f"Participant pre-chat survey side: {survey_cell} (provided for context only; classify target message objectively)")
    user_parts.append(f"\nTARGET message to classify: {content}")

    return system_prompt, "\n".join(user_parts)


def parse_alignment_classifier_response(raw: str) -> dict:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Empty classifier response")
    text = raw.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Classifier response is not a JSON object")
    return data


# ── Primary Resolution via LLM ────────────────────────────────────────────────

async def infer_topic_stance_llm(
    *,
    content: str,
    topic: str,
    survey_cell: Optional[str] = None,
    headline: Optional[str] = None,
    classifier_llm: Optional[Any] = None,
    logger: Optional[Any] = None,
) -> tuple[Optional[str], list[str], dict]:
    """Classify the first message stance using the fast classifier LLM.
    
    If the LLM is unavailable or fails, returns (None, [], ...) so the survey stance is preserved.
    """
    if classifier_llm is None:
        return None, [], {"source": "no_llm_provided"}

    system_prompt, user_prompt = build_alignment_classifier_prompt(
        content=content,
        topic=topic,
        survey_cell=survey_cell,
        headline=headline,
    )
    raw = None
    try:
        raw = await asyncio.wait_for(
            classifier_llm.generate_response(
                user_prompt,
                max_retries=1,
                system_prompt=system_prompt,
            ),
            timeout=5.0,
        )
    except Exception as exc:
        if logger:
            try:
                logger.log_error("participant_alignment_classifier_call", str(exc))
            except Exception:
                pass
        return None, [], {"error": str(exc), "fallback": "keep_survey"}

    if logger:
        try:
            logger.log_llm_call(
                agent_name="__participant_alignment_classifier__",
                prompt=f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}",
                response=raw if isinstance(raw, str) else str(raw),
                error=None if (isinstance(raw, str) and raw.strip()) else "Participant alignment classifier returned no valid text response",
            )
        except Exception:
            pass

    if not isinstance(raw, str) or not raw.strip():
        return None, [], {"error": "empty_response", "fallback": "keep_survey"}

    try:
        data = parse_alignment_classifier_response(raw)
    except Exception as exc:
        if logger:
            try:
                logger.log_error("participant_alignment_classifier_parse", str(exc))
            except Exception:
                pass
        return None, [], {"error": f"parse_error: {exc}", "raw": raw, "fallback": "keep_survey"}

    stance = str(data.get("stance", "")).strip().lower()
    confidence = str(data.get("confidence", "")).strip().lower()
    rationale = str(data.get("rationale", "")).strip()

    inferred_cell: Optional[str] = None
    evidence: list[str] = []
    # Conservative rule: only high or medium confidence explicit stance infers a cell.
    if confidence in ("high", "medium"):
        if stance == "pro":
            inferred_cell = "pro_topic"
            evidence.append(f"{topic}:pro_topic:llm_{confidence}")
        elif stance == "anti":
            inferred_cell = "anti_topic"
            evidence.append(f"{topic}:anti_topic:llm_{confidence}")

    if rationale:
        evidence.append(rationale[:120])

    return inferred_cell, evidence, {
        "stance": stance,
        "confidence": confidence,
        "rationale": rationale,
        "source": "classifier_llm",
    }


def resolve_alignment_decision(
    *,
    survey_stance: Optional[str],
    survey_cell: Optional[str],
    inferred_cell: Optional[str],
    topic: str,
    message_id: str,
    evidence: list[str],
    details: Optional[dict] = None,
) -> dict:
    corrected = bool(survey_cell and inferred_cell and survey_cell != inferred_cell)
    effective_cell = inferred_cell if (corrected or not survey_cell) else survey_cell
    source = (
        "first_message_correction" if corrected else (
            "survey" if survey_cell else (
                "first_message" if inferred_cell else "unresolved"
            )
        )
    )
    result = {
        "version": 1,
        "survey_stance": survey_stance,
        "survey_cell": survey_cell,
        "first_message_id": message_id,
        "topic": topic,
        "inferred_cell": inferred_cell,
        "effective_cell": effective_cell,
        "source": source,
        "evidence": evidence,
        "locked": True,
    }
    if details:
        result["classification_details"] = details
    return result


async def resolve_first_message_alignment(
    *,
    survey_stance: Optional[str],
    survey_cell: Optional[str],
    content: str,
    topic: str,
    message_id: str,
    classifier_llm: Optional[Any] = None,
    headline: Optional[str] = None,
    logger: Optional[Any] = None,
) -> dict:
    inferred_cell, evidence, details = await infer_topic_stance_llm(
        content=content,
        topic=topic,
        survey_cell=survey_cell,
        headline=headline,
        classifier_llm=classifier_llm,
        logger=logger,
    )
    return resolve_alignment_decision(
        survey_stance=survey_stance,
        survey_cell=survey_cell,
        inferred_cell=inferred_cell,
        topic=topic,
        message_id=message_id,
        evidence=evidence,
        details=details,
    )


def resolve_first_message_alignment_sync(
    *,
    survey_stance: Optional[str],
    survey_cell: Optional[str],
    content: str,
    topic: str,
    message_id: str,
) -> dict:
    """Synchronous fallback when no async loop or LLM is present; preserves survey."""
    return resolve_alignment_decision(
        survey_stance=survey_stance,
        survey_cell=survey_cell,
        inferred_cell=None,
        topic=topic,
        message_id=message_id,
        evidence=[],
        details={"source": "sync_fallback"},
    )
