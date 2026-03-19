import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from models import Message


_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SYSTEM_TEMPLATE = (_PROMPTS_DIR / "system" / "classifier_prompt.md").read_text(encoding="utf-8")
_DEFAULT_USER_TEMPLATE = (_PROMPTS_DIR / "user" / "classifier_prompt.md").read_text(encoding="utf-8")


DEFAULT_CLASSIFIER_PROMPT_TEMPLATE = _DEFAULT_USER_TEMPLATE


def _format_participant_messages(messages: List[Message]) -> str:
    if not messages:
        return "(No participant messages yet)"

    lines = []
    for message in messages:
        lines.append(f"- [{message.timestamp.isoformat()}] {message.content}")
    return "\n".join(lines)


def build_classifier_system_prompt(chatroom_context: str = "") -> str:
    prompt = _SYSTEM_TEMPLATE
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    return prompt


def build_classifier_user_prompt(
    *,
    participant_messages: List[Message],
    agent_message: str,
    prompt_template: Optional[str] = None,
    chatroom_context: str = "",
) -> str:
    template = (
        prompt_template
        if isinstance(prompt_template, str) and prompt_template.strip()
        else _DEFAULT_USER_TEMPLATE
    )
    prompt = template
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    prompt = prompt.replace("{PARTICIPANT_MESSAGES}", _format_participant_messages(participant_messages))
    prompt = prompt.replace("{AGENT_MESSAGE}", agent_message)
    return prompt


def _coerce_optional_bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
        if lowered in {"null", "none", "unknown", "n/a"}:
            return None
    return None


def parse_classifier_response(raw: str) -> Dict[str, Optional[object]]:
    if not raw:
        raise ValueError("Classifier response is empty")

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    json_str = fence_match.group(1).strip() if fence_match else raw.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Classifier response is not valid JSON: {exc}\nRaw: {raw[:500]}")

    if not isinstance(data, dict):
        raise ValueError("Classifier response must be a JSON object")

    raw_incivil = data.get("is_incivil", data.get("incivil"))
    is_incivil = _coerce_optional_bool(raw_incivil)
    if is_incivil is None:
        raise ValueError("Classifier response missing boolean 'is_incivil'")

    raw_like_minded = data.get("is_like_minded", data.get("like_minded"))
    is_like_minded = _coerce_optional_bool(raw_like_minded)

    stance_raw = data.get("inferred_participant_stance", data.get("participant_stance"))
    inferred_participant_stance = str(stance_raw).strip() if stance_raw is not None else None
    if inferred_participant_stance == "":
        inferred_participant_stance = None

    rationale_raw = data.get("rationale", data.get("reasoning"))
    rationale = str(rationale_raw).strip() if rationale_raw is not None else None
    if rationale == "":
        rationale = None

    confidence_raw = data.get("stance_confidence")
    valid_confidence = {"high", "medium", "low"}
    if isinstance(confidence_raw, str) and confidence_raw.strip().lower() in valid_confidence:
        stance_confidence = confidence_raw.strip().lower()
    else:
        stance_confidence = None

    return {
        "is_incivil": is_incivil,
        "is_like_minded": is_like_minded,
        "stance_confidence": stance_confidence,
        "inferred_participant_stance": inferred_participant_stance,
        "classification_rationale": rationale,
    }
