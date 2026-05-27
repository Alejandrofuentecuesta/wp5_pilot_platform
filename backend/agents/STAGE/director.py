"""Director module — three-call pipeline: Update → Evaluate → Action.

The Director is split into three LLM calls per turn:
  1. Update    — update the last-acting performer's profile
  2. Evaluate  — evaluate conversation against validity criteria
  3. Action    — select performer, action type, target, and generate O/M/D instruction

All three calls use the same director_llm manager with different prompt templates.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from models import Message, Agent
from agents.STAGE.prompts.prompt_renderer import render as _render_prompt


# Load unified templates at import time
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_UPDATE_TEMPLATE = (_PROMPTS_DIR / "director_update_prompt.md").read_text(encoding="utf-8")
_EVALUATE_TEMPLATE = (_PROMPTS_DIR / "director_evaluate_prompt.md").read_text(encoding="utf-8")
_ACTION_TEMPLATE = (_PROMPTS_DIR / "director_action_prompt.md").read_text(encoding="utf-8")
_BOOSTED_ACTION_TEMPLATE = (_PROMPTS_DIR / "director_action_boosted_prompt.md").read_text(encoding="utf-8")


def _format_chat_message_content(message: Message) -> str:
    """Format message content for Director prompts, compacting seeded news items."""
    if message.sender != "[news]":
        return message.content

    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    headline = str(metadata.get("headline", "")).strip()
    if headline:
        return f"Headline shared earlier: {headline}"

    single_line = " ".join((message.content or "").split())
    if len(single_line) <= 120:
        return single_line
    return single_line[:117].rstrip() + "..."


# ── Chat log formatting ─────────────────────────────────────────────────────

def format_chat_log(messages: List[Message]) -> str:
    """Format messages into a chat log string the Director can reason over.

    Each line includes the message_id so the Director can reference it
    for reply/like targets.
    """
    if not messages:
        return "(No messages yet)"

    lines = []
    for m in messages:
        meta = []
        if m.reply_to:
            meta.append(f"replying to {m.reply_to}")
        if m.mentions:
            meta.append(f"@mentions {', '.join(m.mentions)}")
        if m.liked_by:
            meta.append(f"liked by {', '.join(sorted(m.liked_by))}")

        meta_str = f" ({'; '.join(meta)})" if meta else ""
        line = f"[{m.message_id}] {m.sender}{meta_str}: {_format_chat_message_content(m)}"
        lines.append(line)
    return "\n".join(lines)


def format_agent_profiles(
    profiles: Dict[str, str],
    traits: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    """Format performer profiles into a compact one-line summary per agent."""
    if not profiles:
        return "(No performer profiles yet — this is the start of the session.)"

    lines = []
    for name, profile in profiles.items():
        trait_bits = []
        if traits:
            trait = traits.get(name)
            if trait:
                ideology = trait.get("ideology")
                incivility = trait.get("incivility")
                alignment_cell = trait.get("alignment_cell")
                if alignment_cell:
                    trait_bits.append(f"cell={alignment_cell}")
                if ideology:
                    trait_bits.append(f"ideology={ideology}")
                if incivility:
                    trait_bits.append(f"tone={incivility}")

        if profile:
            compact_profile = " ".join(profile.split())
            if len(compact_profile) > 90:
                compact_profile = compact_profile[:87].rstrip() + "..."
            trait_bits.append(f"recent={compact_profile}")
        else:
            trait_bits.append("recent=not acted yet")

        lines.append(f"**{name}**: {', '.join(trait_bits)}")
    return "\n\n".join(lines)


def format_target_constraints_by_speaker(
    constraints_by_speaker: Dict[str, Dict[str, object]],
) -> str:
    """Format per-speaker target constraints for the Director Action prompt."""
    if not constraints_by_speaker:
        return "(No speaker-specific target constraints available.)"

    lines = ["Target constraints by speaker:"]
    for speaker in sorted(constraints_by_speaker.keys()):
        data = constraints_by_speaker.get(speaker) or {}
        valid_targets = data.get("valid_targets") or []
        forbidden_targets = data.get("forbidden_targets") or []
        best_anchor = data.get("best_reply_anchor")
        participant_target_mode = str(data.get("participant_target_mode") or "allowed")

        valid_text = ", ".join(valid_targets) if valid_targets else "(none)"
        forbidden_text = ", ".join(forbidden_targets) if forbidden_targets else "(none)"
        anchor_text = str(best_anchor or "(no clear reply anchor)")

        lines.append(
            f"- {speaker}: valid direct agent targets={valid_text}; "
            f"forbidden same-cell targets={forbidden_text}; "
            f"participant target={participant_target_mode}; "
            f"best recent anchor={anchor_text}; "
            "if engaging a different-cell agent, attack the same issue from your own cell's frame rather than agreeing with them"
        )
    return "\n".join(lines)


def format_participant_hint(participant_stance_hint: Optional[str]) -> str:
    """Format the participant's pre-session self-report for the Director."""
    if not participant_stance_hint:
        return "(No pre-session stance survey was provided.)"

    labels = {
        "favor": "participant self-report: in favor of the article",
        "against": "participant self-report: against the article",
        "qualified_favor": "participant self-report: broadly in favor of the article's direction, but with important reservations about the specific measure",
        "qualified_against": "participant self-report: broadly against the measure as framed, but not necessarily aligned with the opposite ideological camp",
        "skeptical": "participant self-report: skeptical / unsure about the article",
    }
    return labels.get(participant_stance_hint, f"participant self-report: {participant_stance_hint}")


def format_participant_alignment_cell(participant_alignment_cell: Optional[str]) -> str:
    """Format the resolved participant alignment cell for Director prompts."""
    if not participant_alignment_cell:
        return "participant alignment cell: unclear / mixed"
    return f"participant alignment cell: {participant_alignment_cell}"


def format_treatment_fidelity_summary(messages: List[Message]) -> str:
    """Summarise classifier-derived treatment fidelity signals for the Director."""
    agent_messages = [m for m in messages if m.is_incivil is not None or m.is_like_minded is not None]
    if not agent_messages:
        return "(No classifier-derived treatment metrics yet.)"

    classified_incivility = [m for m in agent_messages if m.is_incivil is not None]
    stance_classified = [m for m in agent_messages if m.is_like_minded is not None]

    def _pct(num: int, den: int) -> Optional[float]:
        return round(100.0 * num / den, 1) if den > 0 else None

    incivil_count = sum(1 for m in classified_incivility if m.is_incivil)
    like_minded_count = sum(1 for m in stance_classified if m.is_like_minded)

    lines = [
        f"Agent messages with classifier output: {len(agent_messages)}",
        f"Incivil messages: {incivil_count}/{len(classified_incivility)}"
        + (
            f" ({_pct(incivil_count, len(classified_incivility))}%)"
            if classified_incivility
            else ""
        ),
        f"Stance-classified messages: {len(stance_classified)}",
        f"Like-minded messages: {like_minded_count}/{len(stance_classified)}"
        + (
            f" ({_pct(like_minded_count, len(stance_classified))}%)"
            if stance_classified
            else ""
        ),
    ]

    latest = next((m for m in reversed(messages) if m.is_incivil is not None or m.is_like_minded is not None), None)
    if latest:
        extra = []
        if latest.inferred_participant_stance:
            extra.append(f"participant stance={latest.inferred_participant_stance}")
        confidence = None
        if isinstance(latest.metadata, dict):
            confidence = latest.metadata.get("stance_confidence")
        if confidence is None:
            confident_message = next(
                (
                    m
                    for m in reversed(messages)
                    if isinstance(m.metadata, dict) and m.metadata.get("stance_confidence") is not None
                ),
                None,
            )
            if confident_message and isinstance(confident_message.metadata, dict):
                confidence = confident_message.metadata.get("stance_confidence")
        if confidence:
            extra.append(f"confidence={confidence}")
        if extra:
            lines.append(f"Latest classifier read: {', '.join(extra)}")

    return "\n".join(f"- {line}" for line in lines)


# ── Update prompts (Call 1) ─────────────────────────────────────────────────

def build_update_system_prompt(chatroom_context: str = "") -> str:
    """Build the Director Update system prompt (session-static)."""
    prompt = _render_prompt(_UPDATE_TEMPLATE, "system")
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    return prompt


def format_last_action(message: Optional[Message]) -> str:
    """Format a single message as the last performer's action.

    Returns a one-line summary suitable for the Director Update prompt.
    """
    if message is None:
        return "(No action to display)"

    meta = []
    if message.reply_to:
        meta.append(f"replying to {message.reply_to}")
    if message.mentions:
        meta.append(f"@mentions {', '.join(message.mentions)}")

    meta_str = f" ({'; '.join(meta)})" if meta else ""
    return f"[{message.message_id}] {message.sender}{meta_str}: {message.content}"


def build_update_user_prompt(
    last_action: Optional[Message],
    last_agent: str = "",
    last_agent_profile: str = "",
    last_agent_traits: Optional[dict] = None,
    chatroom_context: str = "",
) -> str:
    """Build the Director Update user prompt with dynamic data."""
    action_str = format_last_action(last_action)
    profile_str = last_agent_profile or "(This performer has not acted yet.)"

    if last_agent_traits:
        traits_parts = []
        if last_agent_traits.get("stance"):
            traits_parts.append(f"stance={last_agent_traits['stance']}")
        if last_agent_traits.get("ideology"):
            traits_parts.append(f"ideology={last_agent_traits['ideology']}")
        if last_agent_traits.get("incivility"):
            traits_parts.append(f"incivility={last_agent_traits['incivility']}")
        if last_agent_traits.get("topic_stance"):
            traits_parts.append(f"topic_stance={last_agent_traits['topic_stance']}")
        if last_agent_traits.get("policy_stance"):
            traits_parts.append(f"policy_stance={last_agent_traits['policy_stance']}")
        if last_agent_traits.get("alignment_cell"):
            traits_parts.append(f"alignment_cell={last_agent_traits['alignment_cell']}")
        traits_str = f"[Fixed traits: {', '.join(traits_parts)}]" if traits_parts else ""
    else:
        traits_str = ""

    prompt = _render_prompt(_UPDATE_TEMPLATE, "user")
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    prompt = prompt.replace("{LAST_AGENT}", last_agent)
    prompt = prompt.replace("{LAST_AGENT_TRAITS}", traits_str)
    prompt = prompt.replace("{LAST_AGENT_PROFILE}", profile_str)
    prompt = prompt.replace("{LAST_ACTION}", action_str)

    return prompt


def parse_update_response(raw: str) -> dict:
    """Extract and validate the JSON from the Director's Update response.

    Returns dict with key: performer_profile_update
    """
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    json_str = fence_match.group(1).strip() if fence_match else raw.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Director Update response is not valid JSON: {e}\nRaw: {raw[:500]}")

    if "performer_profile_update" not in data:
        raise ValueError("Director Update response missing 'performer_profile_update'")

    return data


# ── Evaluate prompts (Call 2) ───────────────────────────────────────────────

def build_evaluate_system_prompt(
    internal_validity_criteria: str,
    ecological_criteria: str,
    chatroom_context: str = "",
    participant_stance_hint: str = "",
    participant_alignment_cell: str = "",
    participant_name: str = "",
    template: Optional[str] = None,
) -> str:
    """Build the Director Evaluate system prompt (session-static)."""
    raw = template if (isinstance(template, str) and template.strip()) else _EVALUATE_TEMPLATE
    prompt = _render_prompt(raw, "system")
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    prompt = prompt.replace("{PARTICIPANT_STANCE_HINT}", participant_stance_hint)
    prompt = prompt.replace("{PARTICIPANT_ALIGNMENT_CELL}", participant_alignment_cell)
    prompt = prompt.replace("{INTERNAL_VALIDITY_CRITERIA}", internal_validity_criteria)
    prompt = prompt.replace("{ECOLOGICAL_VALIDITY_CRITERIA}", ecological_criteria)
    participant_note = f"\n\nThe human participant's name is **{participant_name}**. Use this name (not 'participant') when referring to them in your evaluations." if participant_name else ""
    prompt = prompt.replace("{PARTICIPANT_NAME_NOTE}", participant_note)
    return prompt


def format_participation_summary(
    performer_counts: Dict[str, int],
    exclude_performer: Optional[str] = None,
) -> str:
    """Format per-performer action counts into a summary string.

    Optionally excludes a performer (e.g. the human participant) so the
    Director is not pressured to select them for equal-participation goals.
    """
    if not performer_counts:
        return "(No participation yet)"

    filtered = {k: v for k, v in performer_counts.items() if k != exclude_performer}
    total = sum(filtered.values())
    if total == 0:
        return "(No actions yet)"

    parts = []
    for name in sorted(filtered.keys()):
        count = filtered[name]
        parts.append(f"{name}: {count} actions")
    return ", ".join(parts)


def format_action_summary(action_counts: Dict[str, int]) -> str:
    """Format running action counts into a concise summary string."""
    total = sum(action_counts.values())
    if total == 0:
        return "(No actions yet)"

    parts = []
    for action_type in ["message", "reply", "@mention", "like"]:
        count = action_counts.get(action_type, 0)
        pct = round(100 * count / total) if total else 0
        parts.append(f"{count} {action_type} ({pct}%)")
    return f"{total} actions so far: {', '.join(parts)}"


def build_evaluate_user_prompt(
    messages: List[Message],
    previous_internal: str = "",
    previous_ecological: str = "",
    internal_validity_criteria: str = "",
    ecological_criteria: str = "",
    chatroom_context: str = "",
    participant_stance_hint: str = "",
    participant_alignment_cell: str = "",
    treatment_fidelity_summary: str = "",
    action_counts: Optional[Dict[str, int]] = None,
    performer_counts: Optional[Dict[str, int]] = None,
    participation_summary: str = "",
    exclude_performer: Optional[str] = None,
    template: Optional[str] = None,
) -> str:
    """Build the Director Evaluate user prompt with dynamic data."""
    chat_log = format_chat_log(messages)
    prev_internal = previous_internal or "No actions have occurred yet. No assessment available."
    prev_ecological = previous_ecological or "No actions have occurred yet. No assessment available."
    action_summary = format_action_summary(action_counts) if action_counts else "(No actions yet)"
    participation_summary = (
        participation_summary
        or (
            format_participation_summary(performer_counts, exclude_performer=exclude_performer)
            if performer_counts else "(No actions yet)"
        )
    )

    raw = template if (isinstance(template, str) and template.strip()) else _EVALUATE_TEMPLATE
    prompt = _render_prompt(raw, "user")
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    prompt = prompt.replace("{PARTICIPANT_STANCE_HINT}", participant_stance_hint)
    prompt = prompt.replace("{PARTICIPANT_ALIGNMENT_CELL}", participant_alignment_cell)
    prompt = prompt.replace("{INTERNAL_VALIDITY_CRITERIA}", internal_validity_criteria)
    prompt = prompt.replace("{ECOLOGICAL_VALIDITY_CRITERIA}", ecological_criteria)
    prompt = prompt.replace("{PREVIOUS_INTERNAL_VALIDITY_EVALUATION}", prev_internal)
    prompt = prompt.replace("{PREVIOUS_ECOLOGICAL_VALIDITY_EVALUATION}", prev_ecological)
    prompt = prompt.replace("{TREATMENT_FIDELITY_SUMMARY}", treatment_fidelity_summary)
    prompt = prompt.replace("{ACTION_SUMMARY}", action_summary)
    prompt = prompt.replace("{PARTICIPATION_SUMMARY}", participation_summary)
    prompt = prompt.replace("{RECENT_CHAT_LOG}", chat_log)

    return prompt


def parse_evaluate_response(raw: str) -> dict:
    """Extract and validate the JSON from the Director's Evaluate response.

    Returns dict with keys: internal_validity_evaluation, ecological_validity_evaluation
    """
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    json_str = fence_match.group(1).strip() if fence_match else raw.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Director Evaluate response is not valid JSON: {e}\nRaw: {raw[:500]}")

    required = ["internal_validity_evaluation", "ecological_validity_evaluation"]
    for key in required:
        if key not in data:
            raise ValueError(f"Director Evaluate response missing '{key}'")

    return data


# ── Action prompts (Call 3) ─────────────────────────────────────────────────

def build_action_system_prompt(
    chatroom_context: str = "",
    participant_stance_hint: str = "",
    participant_alignment_cell: str = "",
    participant_name: str = "",
    template: Optional[str] = None,
) -> str:
    """Build the Director Action system prompt (session-static).

    The Action call does NOT receive raw validity criteria —
    it receives the evaluations from Call 2 instead.
    """
    raw = template if (isinstance(template, str) and template.strip()) else _ACTION_TEMPLATE
    prompt = _render_prompt(raw, "system")
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    prompt = prompt.replace("{PARTICIPANT_STANCE_HINT}", participant_stance_hint)
    prompt = prompt.replace("{PARTICIPANT_ALIGNMENT_CELL}", participant_alignment_cell)
    participant_note = f"\n\nThe human participant's name is **{participant_name}**. Always use this name (not 'participant') when referring to them in `target_user` or instructions." if participant_name else ""
    prompt = prompt.replace("{PARTICIPANT_NAME_NOTE}", participant_note)
    return prompt


def build_action_user_prompt(
    messages: List[Message],
    agent_profiles: Dict[str, str],
    internal_validity_summary: str,
    ecological_validity_summary: str,
    chatroom_context: str = "",
    participant_stance_hint: str = "",
    participant_alignment_cell: str = "",
    treatment_fidelity_summary: str = "",
    performer_counts: Optional[Dict[str, int]] = None,
    action_counts: Optional[Dict[str, int]] = None,
    participation_summary: str = "",
    target_constraints_by_speaker: str = "",
    exclude_performer: Optional[str] = None,
    agent_traits: Optional[Dict[str, Dict[str, str]]] = None,
    template: Optional[str] = None,
) -> str:
    """Build the Director Action user prompt with dynamic data."""
    chat_log = format_chat_log(messages)
    profiles_str = format_agent_profiles(agent_profiles, traits=agent_traits)
    participation_summary = (
        participation_summary
        or (
            format_participation_summary(performer_counts, exclude_performer=exclude_performer)
            if performer_counts else "(No actions yet)"
        )
    )
    action_summary = format_action_summary(action_counts) if action_counts else "(No actions yet)"

    raw = template if (isinstance(template, str) and template.strip()) else _ACTION_TEMPLATE
    prompt = _render_prompt(raw, "user")
    prompt = prompt.replace("{CHATROOM_CONTEXT}", chatroom_context)
    prompt = prompt.replace("{PARTICIPANT_STANCE_HINT}", participant_stance_hint)
    prompt = prompt.replace("{PARTICIPANT_ALIGNMENT_CELL}", participant_alignment_cell)
    prompt = prompt.replace("{INTERNAL_VALIDITY_SUMMARY}", internal_validity_summary)
    prompt = prompt.replace("{ECOLOGICAL_VALIDITY_SUMMARY}", ecological_validity_summary)
    prompt = prompt.replace("{TREATMENT_FIDELITY_SUMMARY}", treatment_fidelity_summary)
    prompt = prompt.replace("{AGENT_PROFILES}", profiles_str)
    prompt = prompt.replace("{PARTICIPATION_SUMMARY}", participation_summary)
    prompt = prompt.replace("{ACTION_SUMMARY}", action_summary)
    prompt = prompt.replace("{CHAT_LOG}", chat_log)
    prompt = prompt.replace("{TARGET_CONSTRAINTS_BY_SPEAKER}", target_constraints_by_speaker)

    return prompt


def parse_action_response(raw: str) -> dict:
    """Extract and validate the JSON from the Director's Action response.

    Returns dict with standard Director output fields:
        next_performer, action_type, target_user, target_message_id, performer_instruction,
        priority, performer_rationale, action_rationale
    """
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    json_str = fence_match.group(1).strip() if fence_match else raw.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Director Action response is not valid JSON: {e}\nRaw: {raw[:500]}")

    # Validate required fields
    if "next_performer" not in data:
        raise ValueError("Director Action response missing 'next_performer'")
    if "action_type" not in data:
        raise ValueError("Director Action response missing 'action_type'")

    action_type = data["action_type"]
    valid_types = {"message", "reply", "@mention", "like"}
    if action_type not in valid_types:
        raise ValueError(f"Director returned invalid action_type: '{action_type}'. Must be one of {valid_types}")

    # Validate target fields based on action type
    if action_type == "reply" and not data.get("target_message_id"):
        raise ValueError("Director chose 'reply' but did not provide 'target_message_id'")
    if action_type == "like" and not data.get("target_message_id"):
        raise ValueError("Director chose 'like' but did not provide 'target_message_id'")
    if action_type == "@mention" and not data.get("target_user"):
        raise ValueError("Director chose '@mention' but did not provide 'target_user'")

    # Validate performer_instruction for non-like actions
    if action_type != "like":
        pi = data.get("performer_instruction")
        if not pi:
            raise ValueError(f"Director chose '{action_type}' but did not provide 'performer_instruction'")
        if not isinstance(pi, dict):
            raise ValueError(f"performer_instruction must be a dict, got {type(pi).__name__}")
        missing = {"objective", "motivation", "directive"} - pi.keys()
        if missing:
            raise ValueError(f"performer_instruction missing keys: {missing}")

    return data
